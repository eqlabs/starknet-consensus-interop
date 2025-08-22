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

## 🧾 Validator Configuration

**For complete validator setup documentation, see [`validators/README.md`](validators/README.md).**

### Quick Overview

Each team creates a subdirectory under `validators/` with:

- `validator_0xNNNN.json` - Validator metadata (address, peer_id, etc.)
- `id_0xNNNN.json` - libp2p identity keypair
- `run_validator.yaml` - Runtime Docker configuration
- Optional: `boot.json`, `id_boot.json`, `run_boot.yaml` for boot nodes

### Required Fields

- `team` (string): Team slug matching directory name
- `node_name` (string): DNS-safe, unique name (e.g., `pathfinder-alice`)
- `address` (string): Hex address from your team's assigned range
- `peer_id` (string): libp2p PeerId from your identity file
- `listen_addresses` (string[]): libp2p multiaddrs for P2P networking

### Example

```json
{
  "team": "pathfinder",
  "node_name": "pathfinder-alice",
  "address": "0x4001",
  "listen_addresses": ["/ip4/0.0.0.0/tcp/50001"],
  "peer_id": "12D3KooWDJryKaxjwNCk6yTtZ4GbtbLrH7JrEUTngvStaDttLtid"
}
```

---

## 🌐 _(Optional)_ Boot Nodes

Boot nodes help validators discover peers. They are optional: if none are configured, validators will bootstrap from other validators.

### Quick Setup

- `boot.json` - Boot node metadata
- `run_boot.yaml` - Runtime configuration (copy from `run_boot.template.yaml`)
- `id_boot.json` - Boot node identity

**For detailed boot node configuration, see [`validators/README.md`](validators/README.md).**

---

## 📥 Snapshot Downloads

Validators can now automatically download and extract database snapshots during deployment, significantly reducing sync time. This feature is completely optional and maintains full backward compatibility.

**For detailed configuration and examples, see [`validators/README.md`](validators/README.md).**

### Quick Start

Add a `snapshot` section to your `run_validator.yaml`:

```yaml
snapshot:
    url: "https://example.com/snapshot.sqlite.zst"
    extract_command: "zstd -T0 -d {filename} -o {target}"
    target_path: "mainnet.sqlite"
```

The system automatically downloads, extracts, and places snapshots before starting your validator containers.

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
  - Downloads and extracts database snapshots if configured in `run_validator.yaml`
  - Starts each node container with team-specific `run_*` files
  - Injects bootstrap peers via `{{bootstrap_addrs}}` (boot nodes if present; otherwise other validators)
  - Injects validator set via `{{validator_addrs}}` (CSV of other validators' addresses)
  - Injects `{{network}}` from `NETWORK_NAME` (default `sepolia-testnet`)

> ✅ Re-running is safe: existing instances/disks are reused, containers are restarted cleanly.

### State file

The deployer writes `.deployed-state.json` with instance IPs and metadata.
