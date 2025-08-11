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

from tools.types import Validator
from tools.gcp.provider import GCPProvider

# Paths
VALIDATORS_FILE = "network-config/validators.json"
DEPLOY_STATE_FILE = ".deployed-state.json"

def load_validators() -> List[Validator]:
    """
    Load validators from network-config/validators.json.
    """
    with open(VALIDATORS_FILE) as f:
        return json.load(f)

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
    Read db_disk_gb from the team's run.yaml, defaulting to 50.
    """
    run_file = f"validators/{team}/run.yaml"
    with open(run_file) as f:
        config = yaml.safe_load(f)
    return int(config.get("db_disk_gb", 50))

def _collect_ips(provider: GCPProvider, validators: List[Validator]) -> dict:
    """
    Resolve and return a map of node_name -> public IP address.
    """
    name_to_ip = {}
    for v in validators:
        name = v["node_name"]
        name_to_ip[name] = provider.get_instance_ip(name)
    return name_to_ip

def provision_infra(provider: GCPProvider, validators: List[Validator]) -> None:
    """
    Stage 1: Create instances, create/attach disks, and persist instance IPs to state.
    """
    state = {
        "metadata": {
            "project": provider.project,
            "zone": provider.zone,
            "generated_at": _utc_now_iso(),
            "version": 1
        },
        "validators": {}
    }

    for v in validators:
        name = v["node_name"]

        # Load team's run.yaml config for disk size
        disk_size = _get_disk_size(v["team"])

        # Create resources
        instance = provider.create_instance(v)
        volume_name = provider.create_volume(v, disk_size)
        provider.attach_volume(instance, volume_name)

        state["validators"][name] = {
            "node_name": name,
            "team": v["team"],
            "address": v["address"],
            "peer_id": v["peer_id"]
        }

    # Collect and persist public IPs after all instances exist
    ips = _collect_ips(provider, validators)
    for name, ip in ips.items():
        if name in state["validators"]:
            state["validators"][name]["ip"] = ip

    save_state(state)
    print("✅ Infra provisioning complete and state saved.")

def deploy_apps(provider: GCPProvider, validators: List[Validator]) -> None:
    """
    Stage 2: Deploy validator containers, injecting peer addresses from saved instance IPs.
    """
    state = load_state()
    name_to_ip = {name: info.get("ip") for name, info in state.get("validators", {}).items()}

    # Fallback to live lookup if any IP missing
    for v in validators:
        name = v["node_name"]
        if not name_to_ip.get(name):
            name_to_ip[name] = provider.get_instance_ip(name)

    for v in validators:
        name = v["node_name"]
        peer_addrs = ",".join(ip for n, ip in name_to_ip.items() if n != name and ip)
        # provider.deploy_validator expects an instance dict with a name
        provider.deploy_validator({"name": name}, v, peer_addrs=peer_addrs)

def main():
    """
    Deploy validators to GCP in stages.
    Usage:
      --stage infra  : create/update instances and disks, record IPs
      --stage app    : deploy containers, injecting peer_addrs
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

    if args.stage in ("infra", "all"):
        provision_infra(provider, validators)
    if args.stage in ("app", "all"):
        deploy_apps(provider, validators)

if __name__ == "__main__":
    main()
