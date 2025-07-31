#!/usr/bin/env python3

import os
import sys
import json
import importlib
import yaml
from pathlib import Path

# Ensure the repo root is in the Python path
sys.path.append(str(Path(__file__).resolve().parents[1]))

# Provider modules are in tools/cloud/
CLOUD_PROVIDERS = {
    "gcp": "tools.cloud.gcp.provider.GCPProvider"
}

# Paths
VALIDATORS_FILE = "network-config/validators.json"
DEPLOY_STATE_FILE = ".deployed-state.json"

def load_validators():
    with open(VALIDATORS_FILE) as f:
        return json.load(f)

def save_state(state):
    with open(DEPLOY_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def load_state():
    if Path(DEPLOY_STATE_FILE).exists():
        with open(DEPLOY_STATE_FILE) as f:
            return json.load(f)
    return {}

def get_provider(provider_name):
    if provider_name not in CLOUD_PROVIDERS:
        print(f"❌ Unknown provider: {provider_name}")
        sys.exit(1)

    module_path, class_name = CLOUD_PROVIDERS[provider_name].rsplit(".", 1)
    module = importlib.import_module(module_path)
    provider_class = getattr(module, class_name)

    if provider_name == "gcp":
        project = os.environ.get("GCP_PROJECT")
        zone = os.environ.get("GCP_ZONE")
        credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not project or not zone or not credentials_path:
            print("❌ Please set GCP_PROJECT, GCP_ZONE, and GOOGLE_APPLICATION_CREDENTIALS in your environment.")
            sys.exit(1)
        return provider_class(project=project, zone=zone, credentials_path=credentials_path)
    else:
        print(f"❌ Unsupported provider: {provider_name}")
        sys.exit(1)

def main():
    if len(sys.argv) < 2:
        print("Usage: python deploynet.py <provider>")
        print("Supported providers: gcp")
        sys.exit(1)

    provider_name = sys.argv[1]
    provider = get_provider(provider_name)
    validators = load_validators()
    #previous_state = load_state()
    new_state = {}

    for validator in validators:
        name = validator["node_name"]

        # Load per-node run.yaml config
        run_file = f"validators/{validator['team']}/run.yaml"
        with open(run_file) as f:
            config = yaml.safe_load(f)

        disk_size = config.get("db_disk_gb", 50)

        # Provision resources
        instance = provider.create_instance(validator)
        volume = provider.create_volume(validator, disk_size)
        provider.attach_volume(instance, volume)
        provider.deploy_validator(instance, validator)

        new_state[name] = {
            "address": validator["address"],
            "node_name": name
        }

    save_state(new_state)
    print("✅ Deployment complete.")

if __name__ == "__main__":
    main()
