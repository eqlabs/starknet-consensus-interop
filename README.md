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

## 🧾 Validator metadata file (`validators/<team>/validator_0xNNNN.json`)

Defines one validator for your team. One file per validator.

- **Filename**: `validator_<address>.json` (e.g., `validator_0x4001.json`)
- **Location**: `validators/<team>/`
- **Required fields**
  - `team` (string): Team slug; must match the directory name (e.g., `pathfinder`).
  - `node_name` (string): DNS-safe, unique across all validators; used for GCP instance, disk, and container names. Suggested format: `<team>-<name>` (e.g., `pathfinder-alice`).
  - `address` (string): Hex address assigned to your team (e.g., `0x4001`).
  - `peer_id` (string): libp2p PeerId corresponding to your identity file.
  - `listen_addresses` (string[]): libp2p multiaddrs the node will listen on (e.g., `/ip4/0.0.0.0/tcp/50001`). Multiple allowed.
- **Identity file**
  - Place `id_<address>.json` alongside this file (e.g., `id_0x4001.json`). It’s uploaded to the VM and mounted at `p2p_identity_path` (default `/identity.json`).
  - The `peer_id` in this JSON should match the identity’s public key.
- **How it’s used**
  - These files are aggregated into `network-config/validators.json` by CI.
  - `tools/deploynet.py` uses them to:
    - Create/label instances and disks.
    - Render CLI args (`{{address}}`, `{{node_name}}`, `{{peer_id}}`, `{{listen_addresses}}`, etc.).
    - Inject bootstrap peers (`{{peer_addrs}}`, libp2p multiaddrs, excludes self).
    - Inject validator set (`{{validator_addrs}}`, other validator addresses, excludes self).

Example:
```json
{
  "team": "pathfinder",
  "node_name": "pathfinder-alice",
  "address": "0x4001",
  "listen_addresses": [
    "/ip4/0.0.0.0/tcp/50001"
  ],
  "peer_id": "12D3KooWDJryKaxjwNCk6yTtZ4GbtbLrH7JrEUTngvStaDttLtid"
}
```

Notes:
- If you expose P2P ports, ensure `listen_addresses` includes the correct ports. The deployer will publish these ports in Docker and open a GCP firewall rule between validator instances automatically.
- Do not edit `network-config/validators.json` directly; it’s generated.


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
  - Creates a GCP firewall rule `allow-validator-p2p` that allows the ports present in `listen_addresses` between validator instances

- App:
  - Uploads identity files
  - Mounts disks and pulls images
  - Starts each node container with team-specific `run.yaml`
  - Injects bootstrap peers via `{{peer_addrs}}` (libp2p multiaddrs with `/p2p/<peer_id>`)
  - Injects validator set via `{{validator_addrs}}` (CSV of other validators’ addresses)

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
- **Placeholders you can use in `cmd`**
    - `{{address}}`, `{{node_name}}`, `{{peer_id}}`, `{{team}}`, `{{listen_addresses}}`, `{{peer_addrs}}`, `{{validator_addrs}}`
    - `{{listen_addresses}}`: CSV from `validators.json`.
    - `{{peer_addrs}}`: CSV of libp2p multiaddrs built from each peer’s listen address + public IP + `/p2p/<peer_id>` (excludes self).
    - `{{validator_addrs}}`: CSV of other validators’ addresses (excludes self).

Example `run.yaml`

```yaml
image: eqlabs/pathfinder:latest

data_dir: /usr/share/pathfinder/data
db_disk_gb: 50

# Must match the CLI flag below
p2p_identity_path: /identity.json

env:
    RUST_LOG: info

cmd:
    - "--validator-address={{address}}"
    - "--p2p.consensus.identity-config-file=/identity.json"
    - "--p2p.consensus.listen-on={{listen_addresses}}"
    - "--bootstrap-peers={{peer_addrs}}"
    - "--validators={{validator_addrs}}"
```

- **Networking note**: P2P ports are derived from `listen_addresses`. The deployer publishes these in Docker and creates a GCP firewall rule between validator instances automatically.
- **Identity note**: The deployer uploads `validators/<team>/id_<address>.json` and mounts it at `p2p_identity_path`. Ensure your CLI flag uses the same path.
- **Templating source**: Values come from `network-config/validators.json` and the saved `.deployed-state.json` created during `--stage infra`.


## 🐣 New Here?

Make sure you have:
- A GCP project and enabled Compute Engine API
- A service account with compute permissions
