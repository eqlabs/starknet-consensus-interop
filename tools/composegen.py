import yaml
import json
from pathlib import Path

def load_validators(path="network-config/validators.json"):
    if not Path(path).exists():
        print(f"⚠️ No validators.json found at {path}")
        return []

    with open(path) as f:
        try:
            validators = json.load(f)
            if not isinstance(validators, list) or len(validators) == 0:
                print(f"⚠️ validators.json is empty or not a list")
                return []
            return validators
        except json.JSONDecodeError:
            print(f"❌ Failed to parse validators.json — is it valid JSON?")
            return []

def load_run_configs(base_dir="nodes"):
    run_configs = {}
    for run_file in Path(base_dir).rglob("run.yaml"):
        team = run_file.parent.name
        with open(run_file) as f:
            config = yaml.safe_load(f)
            run_configs[team] = config
    return run_configs

def format_command(cmd_template, validator):
    substitutions = {
        "address": validator["address"],
        "peer_id": validator["peer_id"],
        "node_name": validator["node_name"],
        "team": validator["team"],
        "listen_addresses": ",".join(validator.get("listen_addresses", [])),
    }

    def fill_placeholders(arg):
        for key, value in substitutions.items():
            arg = arg.replace(f"{{{{{key}}}}}", str(value))
        return arg

    return [fill_placeholders(arg) for arg in cmd_template]

def build_service(validator, base_config):
    name = validator["node_name"]
    service = {
        "image": base_config["image"],
    }

    if "ports" in base_config:
        service["ports"] = [f"{p['host']}:{p['container']}" for p in base_config["ports"]]

    volumes = base_config.get("volumes", []).copy()
    identity_file = f"./validators/{validator['team']}/id_{validator['address']}.json"
    volumes.append(f"{identity_file}:/identity.json")
    service["volumes"] = [f"{v['host']}:{v['container']}" if isinstance(v, dict) else v for v in volumes]

    if "env" in base_config:
        service["environment"] = base_config["env"]

    if "cmd" in base_config:
        service["command"] = format_command(base_config["cmd"], validator)

    return name, service

def generate_compose(validators, run_configs):
    services = {}
    for val in validators:
        team = val["team"]
        if team not in run_configs:
            print(f"⚠️ Skipping validator {val['address']} (no run.yaml for team '{team}')")
            continue
        name, service = build_service(val, run_configs[team])
        services[name] = service
    return {
        "services": services
    }

def main():
    validators = load_validators()
    if not validators:
        print("ℹ️ No validators found. Exiting without generating docker-compose.yml.")
        return

    run_configs = load_run_configs()
    compose = generate_compose(validators, run_configs)

    with open("docker-compose.yml", "w") as f:
        yaml.dump(compose, f, sort_keys=False)

    print(f"✅ Generated docker-compose.yml with {len(compose['services'])} services")

if __name__ == "__main__":
    main()