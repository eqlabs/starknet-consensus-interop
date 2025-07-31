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

Deployment is handled via the Python tool in `tools/deploynet.py`, which uses the canonical validator metadata to provision and start all validator nodes in GCP.

### 1. Install Python dependencies

```bash
cd tools
pip install -r requirements.txt
```

### 2. Set required environment variables

```bash
export GCP_PROJECT=<your-gcp-project-id>
export GCP_ZONE=<your-preferred-zone>  # e.g. europe-west1-b
export GCP_CREDENTIALS_PATH=/absolute/path/to/your/service-account.json
```

### 3. Run the deployment script

```bash
python3 tools/deploynet.py gcp
```

This will:

- Provision GCP compute instances and persistent disks
- Mount disk volumes to store node data
- Upload identity keypairs
- Pull Docker images and run each validator node with team-specific configuration

> ✅ Existing nodes and disks will be reused — no data loss on redeploy.

---

## 📁 Directory Structure

```
validators/
  team-name/
    validator_0x1001.json
    id_0x1001.json
    run.yaml

network-config/
  validators.json     # auto-generated

tools/
  deploynet.py        # deploys all nodes to GCP
  composegen.py       # (optional) local docker-compose generation
  internal/           # validation and merge scripts
```

---

## 🐣 New Here?

Make sure you have:
- A GCP project and enabled Compute Engine API
- A service account with compute permissions
