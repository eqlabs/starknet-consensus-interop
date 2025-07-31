# Tools

This directory contains automation scripts for managing and deploying the consensus interop network.

## Scripts

### `composegen.py`
Generates a `docker-compose.yml` file from validator metadata and per-team `run.yaml` files.  
Used for running a local testnet with multiple validator nodes via Docker.

### `deploynet.py`
Deploys validator nodes to cloud providers (e.g., GCP) based on validator metadata and runtime configuration.  
Automatically provisions machines, sets up persistent disks, and runs the validator containers remotely.

## Internal Tools

The `internal/` subdirectory contains helper scripts used in CI workflows:

- `merge_validators.py`: Aggregates all individual validator metadata files into the canonical `validators.json`.
- `validate_validators.py`: Validates structure, naming, and content of validator and identity files before merging.
