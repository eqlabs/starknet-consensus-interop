# Consensus Interop Network

A full-scale testnet deployment framework to spin up validator nodes across teams using cloud infrastructure.

---

## 🧠 Overview

This project automates the process of defining, validating, and deploying validator nodes for a shared consensus testnet. It is designed to scale, support team-specific configuration, and deploy to GCP in a reproducible way.

---

## 👥 Team Contributions

Each team must add their validator configuration under the `validators/<team>` directory and submit a pull request to `main`.

> ✅ **Need a working example?** Check out [PR #1](https://github.com/eqlabs/starknet-consensus-interop/pull/1) for a complete example of adding validator nodes and a boot node for your team.

### Each team's directory must include:

- `validator_0xNNNN.json`: Metadata for each validator
- `id_0xNNNN.json`: libp2p identity keypair
- `run_validator.yaml`: Runtime Docker config for your validator node (see template)
- _(Optional)_ `boot.json`: Metadata for your boot node (one per team)
- _(Optional)_ `id_boot.json`: Identity for your boot node
- _(Optional)_ `run_boot.yaml`: Runtime Docker config for your boot node (see template)

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
    - Inject bootstrap peers (`{{bootstrap_addrs}}`, libp2p multiaddrs, excludes self).
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

## 🌐 _(Optional)_ Boot Nodes

Boot nodes help validators discover peers. They are optional: if none are configured, validators will bootstrap from other validators.

- **Where to add them**
  - Metadata: `validators/<team>/boot.json` (one per team)
  - Runtime config: `validators/<team>/run_boot.yaml` (copy from `boot_nodes/run-template.yaml`)
  - Identity file: `validators/<team>/id_boot.json`
- **Metadata fields**
  - `team` (string): Team slug _(optional; inferred from directory if omitted)_
  - `node_name` (string): Unique name (e.g., `<team>-boot`)
  - `peer_id` (string): libp2p PeerId corresponding to identity
  - `listen_addresses` (string[]): multiaddrs the boot node listens on
- **Deployment order**
  - Boot nodes are provisioned and deployed first.
  - Their IPs are saved to the state file and used to build `{{bootstrap_addrs}}` for validators.
- **Placeholders**
  - Boot node `run_boot.yaml` supports `{{listen_addresses}}`, `{{bootstrap_addrs}}` (if chaining boot nodes), and `{{network}}`.
- **Disks**
  - Boot nodes do not use persistent disks by default.

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
export NETWORK_NAME=sepolia-testnet   # project-wide; all nodes should use the same value
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
  - Creates/reuses/attaches persistent disks (validators only)
  - Resolves and saves public IPs to `.deployed-state.json`
  - Creates a GCP firewall rule `allow-validator-p2p` that allows the ports present in `listen_addresses` between instances

- App:
  - Deploys boot nodes first (if any), then validators
  - Uploads identity files
  - Mounts disks (validators) and pulls images
  - Starts each node container with team-specific `run_*` files
  - Injects bootstrap peers via `{{bootstrap_addrs}}` (boot nodes if present; otherwise other validators)
  - Injects validator set via `{{validator_addrs}}` (CSV of other validators’ addresses)
  - Injects `{{network}}` from `NETWORK_NAME` (default `sepolia-testnet`)

> ✅ Re-running is safe: existing instances/disks are reused, containers are restarted cleanly.

### State file

The deployer writes `.deployed-state.json` with instance IPs and metadata.

## 🧩 Team Runtime Config

- Validator run file: `validators/<team>/run_validator.yaml` (see `validators/run_validator.template.yaml`)
- Boot node run file _(optional):_ `validators/<team>/run_boot.yaml` (see `boot_nodes/run_boot.template.yaml`)

- **Placeholders you can use in validator `cmd`**
    - `{{address}}`, `{{node_name}}`, `{{peer_id}}`, `{{team}}`, `{{listen_addresses}}`, `{{bootstrap_addrs}}`, `{{validator_addrs}}`, `{{network}}`
- **Placeholders you can use in boot node `cmd`**
    - `{{node_name}}`, `{{peer_id}}`, `{{team}}`, `{{listen_addresses}}`, `{{bootstrap_addrs}}`, `{{network}}`

- **Networking note**: P2P ports are derived from `listen_addresses`. The deployer publishes these in Docker and creates a GCP firewall rule between instances automatically.
- **Identity note**: The deployer uploads the appropriate `id_*.json` and mounts it at `p2p_identity_path`. Ensure your CLI flag uses the same path.
