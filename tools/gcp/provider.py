from tools.gcp.ssh_utils import ssh_connect, ssh_run_command, ssh_upload_file, wait_for_ssh
from tools.gcp.ssh_key_utils import ensure_ssh_key_exists
from tools.types import Validator, Instance, Disk
from googleapiclient import discovery
from google.oauth2 import service_account
import time
import yaml
import os
from typing import List


class GCPProvider:
    def __init__(self, project: str, zone: str, credentials_path: str):
        """
        Provider for managing GCP compute resources and deploying validator containers.
        """
        self.project = project
        self.zone = zone
        self.credentials_path = credentials_path
        self.compute = discovery.build(
            'compute',
            'v1',
            credentials=service_account.Credentials.from_service_account_file(credentials_path)
        )

        # Ensure SSH key exists and is added to GCP project-wide metadata
        ensure_ssh_key_exists(
            project_id=project,
            credentials_path=credentials_path,
            key_path='~/.ssh/interop.pem',
            username='ubuntu'
        )

        # Ensure we can connect via SSH (creates firewall rule if missing)
        self._ensure_firewall_rule()

    def create_instance(self, validator: Validator) -> Instance:
        """
        Create an instance for a validator if it does not exist.
        Returns a minimal instance dict with the instance name.
        """
        name = validator["node_name"]
        print(f"🌐 Creating GCP instance: {name}")

        existing = self.compute.instances().list(project=self.project, zone=self.zone).execute()
        if any(i["name"] == name for i in existing.get("items", [])):
            print(f"⚠️ Instance '{name}' already exists, skipping creation.")
            return {"name": name}

        config = {
            "name": name,
            "machineType": f"zones/{self.zone}/machineTypes/e2-medium",
            "disks": [{
                "boot": True,
                "autoDelete": True,
                "initializeParams": {
                    "sourceImage": "projects/debian-cloud/global/images/family/debian-11"
                }
            }],
            "networkInterfaces": [{
                "network": "global/networks/default",
                "accessConfigs": [{"type": "ONE_TO_ONE_NAT", "name": "External NAT"}]
            }],
            "tags": {"items": ["validator"]},
            "labels": {"team": validator["team"], "node": name}
        }

        op = self.compute.instances().insert(project=self.project, zone=self.zone, body=config).execute()
        _wait_for_operation(self.compute, self.project, self.zone, op["name"])
        return {"name": name}

    def create_volume(self, validator: Validator, disk_size: int = 50) -> str:
        """
        Create a persistent disk for the validator's data if needed.
        Returns the disk name.
        """
        name = f"{validator['node_name']}-db"
        print(f"💾 Creating GCP persistent disk: {name}")

        existing = self.compute.disks().list(project=self.project, zone=self.zone).execute()
        if any(d["name"] == name for d in existing.get("items", [])):
            print(f"⚠️ Disk '{name}' already exists, skipping creation.")
            return name

        config = {
            "name": name,
            "sizeGb": str(disk_size),
            "type": f"projects/{self.project}/zones/{self.zone}/diskTypes/pd-standard",
            "labels": {
                "role": "validator-db",
                "team": validator["team"],
                "node": validator["node_name"]
            }
        }

        op = self.compute.disks().insert(project=self.project, zone=self.zone, body=config).execute()
        _wait_for_operation(self.compute, self.project, self.zone, op["name"])
        return name

    def attach_volume(self, instance: Instance, volume_name: str):
        """
        Attach the data disk to the given instance, if not already attached.
        """
        name = instance["name"]
        print(f"🔗 Attaching disk {volume_name} to instance {name}")
        inst = self.compute.instances().get(project=self.project, zone=self.zone, instance=name).execute()
        if any(disk.get("source", "").endswith(volume_name) for disk in inst.get("disks", [])):
            print(f"⚠️ Disk already attached to '{name}', skipping.")
            return

        config: Disk = {
            "source": f"projects/{self.project}/zones/{self.zone}/disks/{volume_name}",
            "autoDelete": False,
            "boot": False
        }

        op = self.compute.instances().attachDisk(
            project=self.project, zone=self.zone, instance=name, body=config
        ).execute()
        _wait_for_operation(self.compute, self.project, self.zone, op["name"])

    def deploy_validator(self, instance: Instance, validator: Validator, peer_addrs: str = "", validator_addrs: str = ""):
        """
        Deploy or redeploy the validator container on the instance.
        - Ensures Docker is installed
        - Uploads identity file and mounts persistent disk
        - Publishes ports derived from validator listen_addresses
        - Renders command with placeholders including {{peer_addrs}} and {{validator_addrs}}
        """
        name = validator["node_name"]
        ip = self.get_instance_ip(name)
        print(f"📦 Deploying validator on {name} ({ip})")

        wait_for_ssh(ip)
        client = ssh_connect(ip)

        # Ensure Docker is installed
        ssh_run_command(
            client,
            "if ! command -v docker > /dev/null; then sudo apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io; fi"
        )

        # Allow user to use Docker without sudo (if SSH_USERNAME set)
        ssh_user = os.environ.get("SSH_USERNAME")
        if ssh_user:
            ssh_run_command(client, f"sudo groupadd -f docker && sudo usermod -aG docker {ssh_user}")
            # Ensure current socket permissions are correct (immediate convenience; full effect on next login)
            ssh_run_command(client, "if [ -S /var/run/docker.sock ]; then sudo chown root:docker /var/run/docker.sock && sudo chmod 660 /var/run/docker.sock; fi")

        # Upload identity file
        local_identity_path = f"validators/{validator['team']}/id_{validator['address']}.json"
        remote_identity_path = "/home/ubuntu/identity.json"
        ssh_upload_file(client, local_identity_path, remote_identity_path)

        # Fix permissions to ensure Docker can access it
        ssh_run_command(client, f"sudo chown ubuntu:ubuntu {remote_identity_path} && sudo chmod 644 {remote_identity_path}")

        # Load runtime config
        run_file = f"validators/{validator['team']}/run.yaml"
        with open(run_file) as f:
            config = yaml.safe_load(f)

        # === Volume handling ===
        identity_target = config.get("p2p_identity_path", "/identity.json")
        container_data_dir = config["data_dir"]
        host_data_dir = f"/mnt/disks/{name}"

        # Wait for disk device to become available
        _wait_for_disk(client, f"{name}-db")

        # Mount persistent disk
        ssh_run_command(client, f"sudo mkdir -p {host_data_dir}")
        ssh_run_command(client, f"sudo mount -o discard,defaults /dev/disk/by-id/google-{name}-db {host_data_dir}")
        ssh_run_command(client, f"sudo chown ubuntu:ubuntu {host_data_dir}")

        # === Compose docker run command ===
        cmd = "sudo docker run -d --restart unless-stopped \\\n"
        cmd += f"  -v {host_data_dir}:{container_data_dir} \\\n"
        cmd += f"  -v {remote_identity_path}:{identity_target} \\\n"

        # Publish ports derived from listen_addresses
        published = set()
        for addr in validator.get("listen_addresses", []):
            parts = addr.strip().split("/")
            # ['', 'ip4', '127.0.0.1', 'tcp', '50001', ...]
            if len(parts) >= 5:
                proto = parts[4 - 1]  # 'tcp' or 'udp' at index 3
                port = parts[5 - 1]   # port at index 4
                if proto in ("tcp", "udp") and port.isdigit():
                    key = (proto, port)
                    if key in published:
                        continue
                    published.add(key)
                    cmd += f"  -p {port}:{port}/{proto} \\\n"

        # Environment variables
        for k, v in config.get("env", {}).items():
            cmd += f"  -e {k}={v} \\\n"

        cmd += f"  --name {name} {config['image']} \\\n"

        # Command with templating (including peer_addrs and validator_addrs)
        for arg in config["cmd"]:
            rendered = arg.replace("{{address}}", validator["address"]) \
                          .replace("{{node_name}}", name) \
                          .replace("{{peer_id}}", validator["peer_id"]) \
                          .replace("{{team}}", validator["team"]) \
                          .replace("{{listen_addresses}}", ",".join(validator["listen_addresses"])) \
                          .replace("{{peer_addrs}}", peer_addrs or "") \
                          .replace("{{validator_addrs}}", validator_addrs or "")
            cmd += f"  {rendered} \\\n"

        cmd = cmd.rstrip(" \\\n")

        # Restart validator container with latest image
        ssh_run_command(client, f"sudo docker stop {name} 2>/dev/null || true && sudo docker rm {name} 2>/dev/null || true")
        ssh_run_command(client, f"sudo docker pull {config['image']}")
        ssh_run_command(client, cmd)

        client.close()

    def _get_instance_ip(self, name: str) -> str:
        """
        Internal: Fetch public IP for an instance if already assigned.
        Raises a descriptive error if the structure is missing.
        """
        inst = self.compute.instances().get(project=self.project, zone=self.zone, instance=name).execute()
        nics = inst.get("networkInterfaces", [])
        if not nics:
            raise RuntimeError(f"Instance '{name}' has no network interfaces")
        access_configs = nics[0].get("accessConfigs", [])
        if not access_configs:
            raise RuntimeError(f"Instance '{name}' has no external access config; cannot fetch public IP")
        ip = access_configs[0].get("natIP")
        if not ip:
            raise RuntimeError(f"Public IP not yet assigned for instance '{name}'")
        return ip

    def get_instance_ip(self, name: str) -> str:
        """
        Public wrapper to fetch the instance public IP.
        - If the instance is stopped, start it and wait until RUNNING.
        - If there is no external access config, add one.
        - Poll until a natIP is assigned or timeout.
        """
        # Ensure instance exists and is running
        inst = self.compute.instances().get(project=self.project, zone=self.zone, instance=name).execute()
        status = inst.get("status")
        if status != "RUNNING":
            print(f"▶️ Instance '{name}' status is {status}; starting it...")
            op = self.compute.instances().start(project=self.project, zone=self.zone, instance=name).execute()
            _wait_for_operation(self.compute, self.project, self.zone, op["name"])
            # Wait until status is RUNNING
            deadline = time.time() + 180
            while time.time() < deadline:
                inst = self.compute.instances().get(project=self.project, zone=self.zone, instance=name).execute()
                if inst.get("status") == "RUNNING":
                    break
                time.sleep(2)
            else:
                raise RuntimeError(f"Instance '{name}' did not reach RUNNING state in time")

        # Ensure there is an external access config
        inst = self.compute.instances().get(project=self.project, zone=self.zone, instance=name).execute()
        nics = inst.get("networkInterfaces", [])
        if not nics:
            raise RuntimeError(f"Instance '{name}' has no network interfaces")
        nic_name = nics[0].get("name", "nic0")
        access_configs = nics[0].get("accessConfigs", [])
        if not access_configs:
            print(f"➕ Adding external access config to instance '{name}' on {nic_name} ...")
            body = {"type": "ONE_TO_ONE_NAT", "name": "External NAT"}
            op = self.compute.instances().addAccessConfig(
                project=self.project,
                zone=self.zone,
                instance=name,
                networkInterface=nic_name,
                body=body
            ).execute()
            _wait_for_operation(self.compute, self.project, self.zone, op["name"])

        # Poll until natIP is populated
        print(f"⏳ Waiting for public IP of instance '{name}' ...")
        deadline = time.time() + 180
        last_err = None
        while time.time() < deadline:
            try:
                inst = self.compute.instances().get(project=self.project, zone=self.zone, instance=name).execute()
                nics = inst.get("networkInterfaces", [])
                if nics and nics[0].get("accessConfigs"):
                    ip = nics[0]["accessConfigs"][0].get("natIP")
                    if ip:
                        return ip
            except Exception as e:
                last_err = e
            time.sleep(2)
        raise RuntimeError(
            f"Failed to obtain public IP for instance '{name}' within timeout. Last error: {last_err}"
        )

    def list_instances(self) -> List[Instance]:
        """
        List instances in the configured project/zone.
        """
        return self.compute.instances().list(project=self.project, zone=self.zone).execute().get("items", [])

    def _ensure_firewall_rule(self) -> None:
        """
        Ensure an SSH ingress firewall rule exists to allow tcp:22 to instances tagged 'validator'.
        """
        print("🌐 Checking for SSH firewall rule...")
        firewalls = self.compute.firewalls().list(project=self.project).execute()
        if any(rule["name"] == "allow-ssh" for rule in firewalls.get("items", [])):
            print("✅ Firewall rule 'allow-ssh' already exists.")
            return

        print("🛡️  Creating firewall rule to allow SSH (tcp:22)...")
        rule_body = {
            "name": "allow-ssh",
            "allowed": [{"IPProtocol": "tcp", "ports": ["22"]}],
            "direction": "INGRESS",
            "sourceRanges": ["0.0.0.0/0"],
            "targetTags": ["validator"],
            "description": "Allow SSH access to validator nodes"
        }
        op = self.compute.firewalls().insert(project=self.project, body=rule_body).execute()
        # FIX: Call the instance method to wait for global operation
        self._wait_for_global_operation(op["name"])
        print("✅ SSH firewall rule created.")

    def ensure_p2p_firewall(self, port_specs: List[dict]) -> None:
        """
        Ensure an ingress firewall rule that allows validator-to-validator P2P traffic
        on the specified ports/protocols. Uses the 'validator' network tag for both
        source and target. Port specs are dicts with keys: 'port' (str/int), 'protocol' ('tcp'|'udp').
        """
        # Build allowed entries grouped by protocol
        by_proto = {}
        for p in port_specs or []:
            proto = str(p.get("protocol", "tcp")).lower()
            port = str(p.get("port"))
            if not port or not port.isdigit():
                continue
            by_proto.setdefault(proto, set()).add(port)

        allowed = [{"IPProtocol": proto, "ports": sorted(list(ports))} for proto, ports in by_proto.items() if ports]
        if not allowed:
            print("ℹ️ No P2P ports to allow; skipping P2P firewall.")
            return

        rule_name = "allow-validator-p2p"
        print(f"🌐 Ensuring firewall rule '{rule_name}' for validator P2P: {allowed}")

        firewalls = self.compute.firewalls().list(project=self.project).execute()
        if any(rule["name"] == rule_name for rule in (firewalls.get("items") or [])):
            print(f"✅ Firewall rule '{rule_name}' already exists.")
            return

        body = {
            "name": rule_name,
            "allowed": allowed,
            "direction": "INGRESS",
            "sourceTags": ["validator"],
            "targetTags": ["validator"],
            "description": "Allow P2P traffic between validator nodes",
        }
        op = self.compute.firewalls().insert(project=self.project, body=body).execute()
        self._wait_for_global_operation(op["name"])
        print(f"✅ Firewall rule '{rule_name}' created.")

    def _wait_for_global_operation(self, operation_name: str):
        """
        Wait for a global operation to complete.
        """
        print(f"⏳ Waiting for global operation {operation_name} to complete...")
        while True:
            result = self.compute.globalOperations().get(
                project=self.project,
                operation=operation_name
            ).execute()

            if result.get("status") == "DONE":
                if "error" in result:
                    raise Exception(f"❌ Global operation failed: {result['error']}")
                print("✅ Global operation completed.")
                break
            time.sleep(2)


def _wait_for_operation(compute, project, zone, operation_name):
    """
    Wait for a zonal operation to complete.
    """
    print(f"⏳ Waiting for operation {operation_name} to complete...")
    while True:
        result = compute.zoneOperations().get(
            project=project,
            zone=zone,
            operation=operation_name
        ).execute()

        if result.get('status') == 'DONE':
            if 'error' in result:
                raise Exception(f"❌ Operation failed: {result['error']}")
            print("✅ Operation completed.")
            break
        time.sleep(2)

def _wait_for_disk(client, disk_name, timeout=30):
    """
    Wait for the udev device for the given persistent disk to settle on the VM.
    """
    print(f"⏳ Waiting for disk device google-{disk_name} to become available...")
    cmd = f"sudo udevadm settle --timeout={timeout}"
    stdin, stdout, stderr = client.exec_command(cmd)
    exit_code = stdout.channel.recv_exit_status()
    if exit_code != 0:
        raise RuntimeError(f"Disk device /dev/disk/by-id/google-{disk_name} did not settle within {timeout}s")


# TODO: Why some of these wait functions are in the class and some are not?