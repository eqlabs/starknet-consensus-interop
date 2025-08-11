# Consensus Interop Network

A full-scale testnet deployment framework to spin up validator nodes across teams using cloud infrastructure.

---

## 🧠 Overview

This project automates the process of defining, validating, and deploying validator nodes for a shared consensus testnet. It is designed to scale, support team-specific configuration, and deploy to GCP in a reproducible way.

---

## 👥 Team Contributions

Each team must add their validator configuration under the `validators/<team>` directory and submit a pull request to `main`.

### Each team's directory must include:

- `validator_0xNNNN.json`: Metadata for each validator
- `id_0xNNNN.json`: libp2p identity keypair
- `run.yaml`: Runtime Docker config for the node

Once merged to `main`, a CI workflow will validate and aggregate all validator files.

> 🛑 **Do not modify `network-config/validators.json` manually.**  
> It is automatically generated from the per-team files during CI.


### Validator Address Allocation

To prevent collisions and make validator ownership clear, each team is assigned a hex address range:

| Team       | Address Range (Hex) | _(Prefix)_ |
|------------|---------------------|------------|
| Apollo     | 0x1000 – 0x10FF     | 0x1000     |
| Juno       | 0x2000 – 0x20FF     | 0x2000     |
| Madara     | 0x3000 – 0x30FF     | 0x3000     |
| Pathfinder | 0x4000 – 0x40FF     | 0x4000     |

Each validator metadata file must use an address from your team's assigned range.


---

## 🚀 Deploying the Network

Deployment is handled via `tools/deploynet.py`, which provisions GCP resources and deploys validator containers using team configs.

### 1. Install Python dependencies

```bash
cd tools
pip install -r requirements.txt
```

### 2. Set required environment variables

```bash
export GCP_PROJECT=<your-gcp-project-id>
export GCP_ZONE=<your-preferred-zone>    # e.g. europe-west1-b
export GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/your/service-account.json
```

### 3. Two-stage deployment

You can run provisioning and app deployment separately or together.

- Infra only:
```bash
python3 tools/deploynet.py --stage infra
```

- App only (uses previously saved state):
```bash
python3 tools/deploynet.py --stage app
```

- All (infra + app):
```bash
python3 tools/deploynet.py
```

What happens:

- Infra:
  - Creates/reuses GCP instances (tagged `validator`)
  - Creates/reuses/attaches persistent disks
  - Resolves and saves public IPs to `.deployed-state.json`

- App:
  - Uploads identity files
  - Mounts disks and pulls images
  - Starts each node container with team-specific `run.yaml`
  - Injects a peers list via `{{peer_addrs}}` (all other nodes’ public IPs)

> ✅ Re-running is safe: existing instances/disks are reused, containers are restarted cleanly.

### State file

The deployer writes `.deployed-state.json` with instance IPs and metadata:

```json
{
    "metadata": {
        "project": "your-project",
        "zone": "your-zone",
        "generated_at": "2025-08-08T12:34:56+00:00",
        "version": 1
    },
    "validators": {
        "pathfinder-alice": {
            "node_name": "pathfinder-alice",
            "team": "pathfinder",
            "address": "0x1001",
            "peer_id": "12D3Koo...",
            "ip": "34.123.45.67"
        }
    }
}
```

#### Why this file exists and how to use it

- **Purpose**: Decouples provisioning from app deployment.
  - Caches public IPs so we can render `{{peer_addrs}}` without re-querying GCP.
  - Enables quick, idempotent `--stage app` redeploys.

- **What’s inside**: Only public information (project, zone, node metadata, public IPs). No secrets.

- **Sharing**: Safe to share internally with teammates who have the right GCP access and SSH key.
  - Avoid publishing externally; it exposes live public IPs.
  - Teammates can run `--stage app` using this file to redeploy containers, but still need valid GCP credentials and SSH access.

- **Versioning**: Environment-specific artifact. Do not commit it.
  - By default, `.deployed-state.json` is already in `.gitignore`.
  - You can delete it anytime; `--stage infra` will regenerate it.

- **Drift/refresh**: If IPs change (recreates), re-run `--stage infra` to refresh the file. `--stage app` will also live-lookup any missing IPs as a fallback.

## 🧩 Team Runtime Config (`validators/<team>/run.yaml`)

- **Location**: `validators/<team>/run.yaml`
- **Purpose**: Defines how your team’s validator container runs on each VM.
- **Required keys**
    - `image`: Docker image to run.
    - `data_dir`: Container path where validator stores persistent data.
    - `cmd`: List of CLI args (supports placeholders).
- **Optional keys**
    - `db_disk_gb`: Size of the persistent disk in GB (default 50).
    - `p2p_identity_path`: Where to mount the uploaded identity in the container (default `/identity.json`). Must match your CLI flag.
    - `env`: Map of environment variables.
    - `ports`: List of port mappings: `{ host, container, protocol? }` used for docker `-p` (no firewall opened by default).
- **Placeholders you can use in `cmd`**
    - `{{address}}`, `{{node_name}}`, `{{peer_id}}`, `{{team}}`, `{{listen_addresses}}`, `{{peer_addrs}}`
    - `{{listen_addresses}}` is a CSV from `validators.json`.
    - `{{peer_addrs}}` is a CSV of other nodes’ public IPs (self excluded) from `.deployed-state.json`.

Example `run.yaml`

```yaml
image: eqlabs/pathfinder:latest

data_dir: /usr/share/pathfinder/data
db_disk_gb: 50

# Must match the CLI flag below
p2p_identity_path: /identity.json

env:
    RUST_LOG: info

# Optional; adds docker -p mappings (no firewall opened automatically)
# ports:
#     - { host: 50001, container: 50001, protocol: tcp }

cmd:
    - "--validator-address={{address}}"
    - "--p2p.consensus.identity-config-file=/identity.json"
    - "--p2p.consensus.listen-on={{listen_addresses}}"
    - "--bootstrap-peers={{peer_addrs}}"
```

- **Networking note**: Only SSH (tcp:22) is open by default. If your node needs public p2p ports, add them in `ports` and coordinate firewall rules in GCP.
- **Identity note**: The deployer uploads `validators/<team>/id_<address>.json` and mounts it at `p2p_identity_path`. Ensure your CLI flag uses the same path.
- **Templating source**: Values come from `network-config/validators.json` and the saved `.deployed-state.json` created during `--stage infra`.


## 🐣 New Here?

Make sure you have:
- A GCP project and enabled Compute Engine API
- A service account with compute permissions
