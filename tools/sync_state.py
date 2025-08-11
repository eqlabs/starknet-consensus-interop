#!/usr/bin/env python3

import json
import argparse
from tools.cloud.gcp.provider import GCPProvider

STATE_FILE = ".deployed_state.json"

def sync_state(provider: GCPProvider):
    print("🔄 Syncing deployed state with GCP...")

    instances = (
        provider.compute.instances()
        .list(project=provider.project, zone=provider.zone)
        .execute()
        .get("items", [])
    )

    state = {}
    for inst in instances:
        name = inst["name"]
        if not name.startswith("pathfinder-"):
            continue

        # Try to extract address from metadata (optional enhancement)
        node_info = {
            "node_name": name,
            "address": "UNKNOWN"
        }

        state[name] = node_info

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    print(f"✅ Synced {len(state)} instance(s) into {STATE_FILE}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync-state", action="store_true", help="Sync local state with deployed instances")
    args = parser.parse_args()

    provider = GCPProvider()

    if args.sync_state:
        sync_state(provider)
    else:
        from tools.deploynet import main as deploy_main
        deploy_main()

if __name__ == "__main__":
    main()
