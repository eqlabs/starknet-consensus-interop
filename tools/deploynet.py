#!/usr/bin/env python3

import os
import sys
import json
import yaml
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import List

# Ensure the repo root is in the Python path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from tools.types import Validator, BootNode
from tools.gcp.provider import GCPProvider

# Paths
VALIDATORS_FILE = "network-config/validators.json"
BOOT_NODES_FILE = "network-config/boot_nodes.json"
DEPLOY_STATE_FILE = ".deployed-state.json"


def load_validators() -> List[Validator]:
    """
    Load validators from network-config/validators.json.
    """
    with open(VALIDATORS_FILE) as f:
        return json.load(f)


def load_boot_nodes() -> List[BootNode]:
    """
    Load boot nodes from validators/<team>/boot.json files if present; otherwise empty list.
    """
    boot_nodes: List[BootNode] = []
    validators_dir = Path("validators")
    if not validators_dir.exists():
        return boot_nodes
    for team_dir in validators_dir.iterdir():
        if not team_dir.is_dir():
            continue
        boot_file = team_dir / "boot.json"
        if boot_file.exists():
            with open(boot_file) as f:
                data = json.load(f)
                # ensure team is present
                data.setdefault("team", team_dir.name)
                boot_nodes.append(data)
    return boot_nodes


def save_state(state):
    """
    Persist deployment state (including instance IPs) to DEPLOY_STATE_FILE.
    """
    with open(DEPLOY_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_state():
    """
    Load deployment state if present; otherwise return an empty dict.
    """
    if Path(DEPLOY_STATE_FILE).exists():
        with open(DEPLOY_STATE_FILE) as f:
            return json.load(f)
    return {}


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _get_disk_size(team: str) -> int:
    """
    Read db_disk_gb from the team's validator run config, defaulting to 50.
    Tries validators/<team>/run_validator.yaml first, then falls back to run.yaml for compatibility.
    """
    primary = Path(f"validators/{team}/run_validator.yaml")
    fallback = Path(f"validators/{team}/run.yaml")
    run_file = primary if primary.exists() else fallback
    with open(run_file) as f:
        config = yaml.safe_load(f)
    return int(config.get("db_disk_gb", 50))


def _collect_ips(provider: GCPProvider, nodes: List[dict]) -> dict:
    """
    Resolve and return a map of node_name -> (external_ip, internal_ip) for a list of nodes.
    """
    name_to_ips = {}
    for n in nodes:
        name = n["node_name"]
        external_ip = provider.get_instance_ip(name)
        internal_ip = provider.get_instance_internal_ip(name)
        name_to_ips[name] = {
            "external": external_ip,
            "internal": internal_ip
        }
    return name_to_ips


def _derive_p2p_ports_from_listen_addresses(nodes: List[dict]) -> List[dict]:
    """
    Derive unique ports and protocols from nodes' listen_addresses.
    Returns a list of dicts: {"port": <str>, "protocol": "tcp"|"udp"}
    """
    seen = set()
    ports = []
    for n in nodes:
        for addr in n.get("listen_addresses", []):
            parts = addr.strip().split("/")
            if len(parts) >= 5:
                proto = parts[4 - 1]
                port = parts[5 - 1]
                if proto in ("tcp", "udp") and port.isdigit():
                    key = (proto, port)
                    if key not in seen:
                        seen.add(key)
                        ports.append({"protocol": proto, "port": port})
    return ports


def provision_infra(provider: GCPProvider, validators: List[Validator], boot_nodes: List[BootNode]) -> None:
    """
    Stage 1: Create instances, create/attach disks (validators only), ensure P2P firewall, and persist instance IPs to state.
    Boot nodes are lightweight; no persistent disks are created for them.
    """
    state = {
        "metadata": {
            "project": provider.project,
            "zone": provider.zone,
            "generated_at": _utc_now_iso(),
            "version": 1
        },
        "boot_nodes": {},
        "validators": {}
    }

    # Provision boot nodes first (no disks)
    for b in boot_nodes:
        name = b["node_name"]
        instance = provider.create_instance(b)  # type: ignore[arg-type]
        state["boot_nodes"][name] = {
            "node_name": name,
            "team": b.get("team", ""),
            "peer_id": b["peer_id"]
        }

    # Then provision validators (with disks)
    for v in validators:
        name = v["node_name"]
        disk_size = _get_disk_size(v["team"])  # from validators/<team>/run.yaml
        instance = provider.create_instance(v)
        volume_name = provider.create_volume(v, disk_size)
        provider.attach_volume(instance, volume_name)
        state["validators"][name] = {
            "node_name": name,
            "team": v["team"],
            "address": v["address"],
            "peer_id": v["peer_id"]
        }

    # Ensure inter-node P2P firewall based on listen_addresses from both boot nodes and validators
    p2p_ports = _derive_p2p_ports_from_listen_addresses([*boot_nodes, *validators])
    provider.ensure_p2p_firewall(p2p_ports)

    # Collect and persist public IPs after all instances exist
    boot_ips = _collect_ips(provider, boot_nodes)
    for name, ips in boot_ips.items():
        state["boot_nodes"][name]["external_ip"] = ips["external"]
        state["boot_nodes"][name]["internal_ip"] = ips["internal"]

    val_ips = _collect_ips(provider, validators)
    for name, ips in val_ips.items():
        state["validators"][name]["external_ip"] = ips["external"]
        state["validators"][name]["internal_ip"] = ips["internal"]

    save_state(state)
    print("✅ Infra provisioning complete and state saved.")

def _normalize_multiaddr_with_internal_ip(listen_addr: str, internal_ip: str) -> str:
    """
    Replace 0.0.0.0 or 127.0.0.1 with the internal IP for internal communication.
    """
    parts = listen_addr.strip().split("/")
    if len(parts) >= 4 and parts[1] == "ip4":
        host = parts[2]
        if host in ("127.0.0.1", "0.0.0.0"):
            parts[2] = internal_ip
    return "/".join(parts)


def _build_bootstrap_multiaddrs(nodes: List[dict], name_to_ips: dict) -> dict:
    """
    For each node in `nodes`, produce a CSV of multiaddrs for all other nodes:
    - Always use internal IPs for internal communication
    - This ensures all validator-to-validator traffic stays within GCP's network
    """
    by_name = {n["node_name"]: n for n in nodes}
    result = {}
    for name, n in by_name.items():
        peers = []
        for peer_name, pn in by_name.items():
            if peer_name == name:
                continue
            ips = name_to_ips.get(peer_name)
            if not ips or not ips.get("internal"):
                continue
            internal_ip = ips["internal"]
            la_list = pn.get("listen_addresses", [])
            if not la_list:
                continue
            # Replace 0.0.0.0 with internal IP
            base = _normalize_multiaddr_with_internal_ip(la_list[0], internal_ip)
            peers.append(f"{base}/p2p/{pn['peer_id']}")
        # dedupe
        seen = set()
        uniq = []
        for a in peers:
            if a not in seen:
                seen.add(a)
                uniq.append(a)
        result[name] = ",".join(uniq)
    return result


def _build_boot_nodes_addrs_csv(boot_nodes: List[BootNode], name_to_ips: dict) -> str:
    """
    Build a CSV of all boot node multiaddrs using internal IPs.
    """
    addrs = []
    seen = set()
    for b in boot_nodes:
        ips = name_to_ips.get(b["node_name"]) or {}
        internal_ip = ips.get("internal")
        if not internal_ip:
            continue
        la_list = b.get("listen_addresses", [])
        if not la_list:
            continue
        base = _normalize_multiaddr_with_internal_ip(la_list[0], internal_ip)
        full = f"{base}/p2p/{b['peer_id']}"
        if full not in seen:
            seen.add(full)
            addrs.append(full)
    return ",".join(addrs)


def _build_validator_addrs(validators: List[Validator]) -> dict:
    result = {}
    by_name = {v["node_name"]: v for v in validators}
    for name, v in by_name.items():
        others = [ov["address"] for on, ov in by_name.items() if on != name]
        result[name] = ",".join(others)
    return result


def deploy_boot_nodes(provider: GCPProvider, boot_nodes: List[BootNode]) -> None:
    state = load_state()
    bn_state = state.get("boot_nodes", {})
    name_to_ips = {name: {"external": info.get("external_ip"), "internal": info.get("internal_ip")} 
                   for name, info in bn_state.items()}

    # Fallback to live lookup
    for b in boot_nodes:
        name = b["node_name"]
        if not name_to_ips.get(name):
            external_ip = provider.get_instance_ip(name)
            internal_ip = provider.get_instance_internal_ip(name)
            name_to_ips[name] = {"external": external_ip, "internal": internal_ip}

    # Build bootstrap multiaddrs among boot nodes using internal IPs
    bootstrap_map = _build_bootstrap_multiaddrs(boot_nodes, name_to_ips)

    for b in boot_nodes:
        name = b["node_name"]
        peer_addrs = bootstrap_map.get(name, "")
        provider.deploy_boot_node({"name": name}, b, peer_addrs=peer_addrs, network=os.environ.get("NETWORK_NAME", "sepolia-testnet"))


def deploy_apps(provider: GCPProvider, validators: List[Validator], boot_nodes: List[BootNode]) -> None:
    state = load_state()
    val_state = state.get("validators", {})
    bn_state = state.get("boot_nodes", {})

    name_to_ips_vals = {name: {"external": info.get("external_ip"), "internal": info.get("internal_ip")} 
                        for name, info in val_state.items()}
    name_to_ips_boot = {name: {"external": info.get("external_ip"), "internal": info.get("internal_ip")} 
                        for name, info in bn_state.items()}

    for v in validators:
        name = v["node_name"]
        if not name_to_ips_vals.get(name):
            name_to_ips_vals[name] = provider.get_instance_ip(name)

    for b in boot_nodes:
        name = b["node_name"]
        if not name_to_ips_boot.get(name):
            name_to_ips_boot[name] = provider.get_instance_ip(name)

    # Build bootstrap addresses for validators:
    if boot_nodes:
        # Use all boot nodes for every validator
        bootstrap_addrs_all = _build_boot_nodes_addrs_csv(boot_nodes, name_to_ips_boot)
        bootstrap_map = None
    else:
        # Fall back to using other validators as peers (self excluded per map)
        bootstrap_map = _build_bootstrap_multiaddrs(validators, name_to_ips_vals)
        bootstrap_addrs_all = ""

    validator_addrs_map = _build_validator_addrs(validators)

    for v in validators:
        name = v["node_name"]
        if boot_nodes:
            bootstrap_addrs = bootstrap_addrs_all
        else:
            bootstrap_addrs = (bootstrap_map or {}).get(name, "")
        validator_addrs = validator_addrs_map.get(name, "")
        provider.deploy_validator({"name": name}, v,
                                  peer_addrs=bootstrap_addrs,
                                  validator_addrs=validator_addrs,
                                  network=os.environ.get("NETWORK_NAME", "sepolia-testnet"))


def main():
    """
    Deploy validators to GCP in stages.
    Usage:
      --stage infra  : create/update instances and disks, record IPs, ensure P2P firewall
      --stage app    : deploy boot nodes first, then validators
      --stage all    : run both stages (default)
    """
    parser = argparse.ArgumentParser(description="Deploy validators to GCP")
    parser.add_argument("--stage", choices=["infra", "app", "all"], default="all", help="Which stage(s) to run")
    args = parser.parse_args()

    project = os.environ.get("GCP_PROJECT")
    zone = os.environ.get("GCP_ZONE")
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not project or not zone or not credentials_path:
        print("❌ Please set GCP_PROJECT, GCP_ZONE, and GOOGLE_APPLICATION_CREDENTIALS in your environment.")
        sys.exit(1)

    provider = GCPProvider(project=project, zone=zone, credentials_path=credentials_path)
    validators = load_validators()
    boot_nodes = load_boot_nodes()

    if args.stage in ("infra", "all"):
        provision_infra(provider, validators, boot_nodes)
    if args.stage in ("app", "all"):
        if boot_nodes:
            deploy_boot_nodes(provider, boot_nodes)
        deploy_apps(provider, validators, boot_nodes)


if __name__ == "__main__":
    main()
