from tools.cloud.provider_base import CloudProvider
from tools.cloud.gcp.ssh_utils import ssh_connect, ssh_run_command, ssh_upload_file, wait_for_ssh
from tools.cloud.gcp.ssh_key_utils import ensure_ssh_key_exists
from googleapiclient import discovery
from google.oauth2 import service_account
import time
import yaml


class GCPProvider(CloudProvider):
    def __init__(self, project, zone, credentials_path):
        self.project = project
        self.zone = zone
        self.credentials_path = credentials_path
        self.compute = discovery.build(
            'compute',
            'v1',
            credentials=service_account.Credentials.from_service_account_file(credentials_path)
        )

        # Ensure SSH key exists and is added to GCP metadata
        ensure_ssh_key_exists(
            project_id=project,
            credentials_path=credentials_path,
            key_path='~/.ssh/interop.pem',
            username='ubuntu'
        )

        # Ensure we can connect via SSH
        self._ensure_firewall_rule()

    def create_instance(self, validator):
        name = validator["node_name"]
        print(f"🌐 Creating GCP instance: {name}")

        # Skip if instance exists
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

    def create_volume(self, validator, disk_size=50):
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

    def attach_volume(self, instance, volume_name):
        name = instance["name"]
        print(f"🔗 Attaching disk {volume_name} to instance {name}")
        inst = self.compute.instances().get(project=self.project, zone=self.zone, instance=name).execute()
        if any(disk.get("source", "").endswith(volume_name) for disk in inst.get("disks", [])):
            print(f"⚠️ Disk already attached to '{name}', skipping.")
            return

        config = {
            "source": f"projects/{self.project}/zones/{self.zone}/disks/{volume_name}",
            "autoDelete": False,
            "boot": False
        }

        op = self.compute.instances().attachDisk(
            project=self.project, zone=self.zone, instance=name, body=config
        ).execute()
        _wait_for_operation(self.compute, self.project, self.zone, op["name"])

    def deploy_validator(self, instance, validator):
        name = validator["node_name"]
        ip = self._get_instance_ip(name)
        print(f"📦 Deploying validator on {name} ({ip})")

        wait_for_ssh(ip)
        client = ssh_connect(ip)

        # Ensure Docker is installed
        ssh_run_command(
            client,
            "if ! command -v docker > /dev/null; then sudo apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io; fi"
        )

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

        for k, v in config.get("env", {}).items():
            cmd += f"  -e {k}={v} \\\n"

        cmd += f"  --name {name} {config['image']} \\\n"

        for arg in config["cmd"]:
            rendered = arg.replace("{{address}}", validator["address"]) \
                        .replace("{{node_name}}", name) \
                        .replace("{{peer_id}}", validator["peer_id"]) \
                        .replace("{{team}}", validator["team"]) \
                        .replace("{{listen_addresses}}", ",".join(validator["listen_addresses"]))
            cmd += f"  {rendered} \\\n"

        cmd = cmd.rstrip(" \\\n")

        # Restart validator container with latest image
        ssh_run_command(client, f"sudo docker stop {name} 2>/dev/null || true && sudo docker rm {name} 2>/dev/null || true")
        ssh_run_command(client, f"sudo docker pull {config['image']}")
        ssh_run_command(client, cmd)

        client.close()


    def _get_instance_ip(self, name):
        inst = self.compute.instances().get(project=self.project, zone=self.zone, instance=name).execute()
        return inst["networkInterfaces"][0]["accessConfigs"][0]["natIP"]

    def list_instances(self):
        return self.compute.instances().list(project=self.project, zone=self.zone).execute().get("items", [])

    def _ensure_firewall_rule(self):
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
        _wait_for_global_operation(op["name"])
        print("✅ SSH firewall rule created.")


def _wait_for_operation(compute, project, zone, operation_name):
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
    print(f"⏳ Waiting for disk device google-{disk_name} to become available...")
    cmd = f"sudo udevadm settle --timeout={timeout}"
    stdin, stdout, stderr = client.exec_command(cmd)
    exit_code = stdout.channel.recv_exit_status()
    if exit_code != 0:
        raise RuntimeError(f"Disk device /dev/disk/by-id/google-{disk_name} did not settle within {timeout}s")

def _wait_for_global_operation(self, operation_name):
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

