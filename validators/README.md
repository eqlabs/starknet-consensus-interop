# Validator Configuration

This directory contains configuration files for different validator implementations. Each team can have their own subdirectory with specific configurations.

## Directory Structure

Each team should create a subdirectory under `validators/` with the following structure:

```
validators/<team>/
├── validator_0xNNNN.json     # Validator metadata
├── id_0xNNNN.json            # libp2p identity keypair
├── run_validator.yaml        # Runtime Docker configuration
├── boot.json                 # Boot node metadata (optional)
├── id_boot.json              # Boot node identity (optional)
└── run_boot.yaml             # Boot node runtime config (optional)
```

## Configuration Files

### 1. Validator Metadata (`validator_0xNNNN.json`)

Defines one validator for your team. One file per validator.

**Required fields:**
- `team` (string): Team slug; must match the directory name
- `node_name` (string): DNS-safe, unique across all validators
- `address` (string): Hex address from your team's assigned range
- `peer_id` (string): libp2p PeerId corresponding to your identity file
- `listen_addresses` (string[]): libp2p multiaddrs the node will listen on

**Example:**
```json
{
  "team": "pathfinder",
  "node_name": "pathfinder-alice",
  "address": "0x4001",
  "listen_addresses": ["/ip4/0.0.0.0/tcp/50001"],
  "peer_id": "12D3KooWDJryKaxjwNCk6yTtZ4GbtbLrH7JrEUTngvStaDttLtid"
}
```

### 2. Runtime Configuration (`run_validator.yaml`)

Defines how your validator container runs. Copy from `run_validator.template.yaml` and customize.

**Key fields:**
- `image`: Docker image to use
- `data_dir`: Container data directory path
- `db_disk_gb`: Size of persistent disk in GB
- `p2p_identity_path`: Where to mount the identity file
- `env`: Environment variables
- `cmd`: Command-line arguments with placeholders

**Available placeholders:**
- `{{address}}`: Validator address
- `{{node_name}}`: Node name
- `{{peer_id}}`: Peer ID
- `{{team}}`: Team name
- `{{listen_addresses}}`: Comma-separated listen addresses
- `{{bootstrap_addrs}}`: Bootstrap peer addresses
- `{{validator_addrs}}`: Other validator addresses
- `{{network}}`: Network name

**Example:**
```yaml
image: eqlabs/pathfinder:latest
data_dir: /usr/share/pathfinder/data
db_disk_gb: 50
p2p_identity_path: /identity.json

env:
  RUST_LOG: info

cmd:
  - "--validator-address={{address}}"
  - "--p2p.consensus.identity-config-file=/identity.json"
  - "--p2p.consensus.listen-on={{listen_addresses}}"
```

### 3. Identity Files (`id_0xNNNN.json`)

libp2p identity keypairs for P2P networking. The `peer_id` in your validator metadata should match the public key in this file.

## Snapshot Support

**Validators only** can automatically download and extract database snapshots during deployment, significantly reducing sync time. Boot nodes do not support snapshots as they don't use persistent storage.

### Configuration

Add a `snapshot` section to your `run_validator.yaml`:

```yaml
snapshot:
    # URL to download the snapshot from
    url: "https://example.com/snapshot.sqlite.zst"
    # Optional SHA256 checksum to verify download integrity
    checksum: "sha256:abc123..."
    # Command to extract the snapshot (required)
    # Use {filename} placeholder for the downloaded file and {target} for the target path
    extract_command: "zstd -T0 -d {filename} -o {target}"
    # Relative path within data_dir where the extracted file should be placed
    # Example: "mainnet.sqlite" (will be placed at data_dir/mainnet.sqlite)
    target_path: "mainnet.sqlite"
```

**Note**: Both `extract_command` and `target_path` are required when using snapshots. The `extract_command` should use the `{target}` placeholder, which gets replaced with the full path: `data_dir + target_path`. For example, if your `data_dir` is `/usr/share/pathfinder/data` and `target_path` is `mainnet.sqlite`, then `{target}` becomes `/usr/share/pathfinder/data/mainnet.sqlite`.

**Example**:
```yaml
data_dir: /usr/share/pathfinder/data
snapshot:
    extract_command: "zstd -T0 -d {filename} -o {target}"
    target_path: "mainnet.sqlite"
```

When deployed, `{target}` gets replaced with `/usr/share/pathfinder/data/mainnet.sqlite`, so the actual command becomes:
```bash
zstd -T0 -d downloaded_file.zst -o /usr/share/pathfinder/data/mainnet.sqlite
```

### Space Efficiency

**Streaming commands (recommended):** Use commands that can stream directly from the URL without creating temporary files:
```yaml
extract_command: "zstd -d | tar -xvf - -C /var/lib/node && mv /var/lib/node/*/* {target}"
```

**File-based commands (less efficient):** Commands that require a local filename will create a temporary file:
```yaml
extract_command: "zstd -T0 -d {filename} -o {target}"
```

The system automatically detects which approach to use and warns when temporary files are created.

### Supported Formats

- **Zstandard (.zst)**: Compressed SQLite files
- **Tar Streams**: Compressed archives
- **Plain Files**: Uncompressed database files

### How It Works

1. During deployment, if a snapshot URL is configured, the system will:
   - Download the snapshot directly to the target location
   - Verify the checksum if provided
   - Extract the snapshot in-place using streaming extraction
   - Clean up any temporary files

2. The snapshot file is placed directly in the persistent volume

3. The validator container starts with the pre-synced database

### Examples

#### Pathfinder
```yaml
snapshot:
    url: "https://rpc.pathfinder.equilibrium.co/snapshots/latest/mainnet.sqlite.zst"
    checksum: "sha256:abc123..."
    extract_command: "zstd -T0 -d {filename} -o {target}"
    target_path: "mainnet.sqlite"  # Relative to data_dir
```

#### Juno
```yaml
snapshot:
    url: "https://juno-snapshots.nethermind.io/files/mainnet/latest"
    extract_command: "zstd -d | tar -xvf - -C /var/lib/juno && mv /var/lib/juno/*/* {target}"
    target_path: "juno.db"  # Relative to data_dir
```

## Boot Node Configuration

Boot nodes help validators discover peers. They are optional - if none are configured, validators will bootstrap from other validators.

### Files
- `boot.json`: Boot node metadata
- `run_boot.yaml`: Runtime configuration (copy from `run_boot.template.yaml`)
- `id_boot.json`: Boot node identity

### Configuration
```yaml
image: org/boot-node:latest
data_dir: /var/lib/bootnode
p2p_identity_path: /identity.json

env:
  RUST_LOG: info

cmd:
  - "--network={{network}}"
  - "--listen-on={{listen_addresses}}"
  - "--identity-config-file=/identity.json"
```

## Best Practices

1. **Naming**: Use descriptive node names like `<team>-<purpose>` (e.g., `pathfinder-mainnet`)
2. **Ports**: Ensure `listen_addresses` includes the correct P2P ports
3. **Disk Sizing**: Set `db_disk_gb` appropriately for your validator's storage needs
4. **Snapshots**: Use checksums when available for integrity verification
5. **Testing**: Test your configuration locally before submitting

## Deployment

Once your configuration is merged to `main`:
1. CI validates and aggregates all validator files
2. `tools/deploynet.py` uses your configs to deploy to GCP
3. Instances, disks, and containers are created automatically
4. Snapshots are downloaded and extracted if configured
5. Validators start with your specified configuration
