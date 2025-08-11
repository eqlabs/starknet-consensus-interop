import os
import subprocess
from googleapiclient import discovery
from google.oauth2 import service_account


def ensure_ssh_key_exists(project_id, credentials_path, key_path='~/.ssh/interop.pem', username='ubuntu'):
    key_path = os.path.expanduser(key_path)
    pub_path = key_path + '.pub'

    if not os.path.exists(key_path):
        print(f"🔐 SSH key not found at {key_path}, generating one...")
        subprocess.run(['ssh-keygen', '-t', 'rsa', '-f', key_path, '-N', '', '-C', 'interop'], check=True)
        os.chmod(key_path, 0o600)

    # Format required by GCP: <user>:<public-key>
    with open(pub_path, 'r') as pub_file:
        pub_key = pub_file.read().strip()
    gcp_format = f"{username}:{pub_key}"

    credentials = service_account.Credentials.from_service_account_file(credentials_path)
    compute = discovery.build('compute', 'v1', credentials=credentials)

    print("📡 Checking existing project metadata for SSH keys...")
    project = compute.projects().get(project=project_id).execute()
    metadata = project.get('commonInstanceMetadata', {})
    items = metadata.get('items', [])

    ssh_keys_item = next((i for i in items if i['key'] == 'ssh-keys'), None)
    existing_keys = ssh_keys_item['value'].split('\n') if ssh_keys_item else []

    if gcp_format in existing_keys:
        print("✅ SSH key already present in GCP project metadata.")
        return

    print("📝 Adding SSH key to GCP project metadata...")
    existing_keys.append(gcp_format)
    new_items = [i for i in items if i['key'] != 'ssh-keys']
    new_items.append({'key': 'ssh-keys', 'value': '\n'.join(existing_keys)})

    request_body = {
        'kind': 'compute#metadata',
        'items': new_items
    }

    op = compute.projects().setCommonInstanceMetadata(project=project_id, body=request_body).execute()
    print(f"✅ SSH key added. Metadata update operation: {op['name']}")
