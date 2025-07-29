# Starknet Interop Testnet

Shared repository for running interoperability consensus tests across Starknet node implementations.

## Structure

- `validators/<team>/`: directory containing validator metadata and identity files
  - `validator_0xNNNN.json`: metadata (address, peer ID, etc.)
  - `id_0xNNNN.json`: testnet-only private key for that validator

- `network-config/validators.json`: aggregated list of all validators

- `tools/`: helper scripts  
  - `validate_validators.py`: checks all validator files  
  - `merge_validators.py`: builds the canonical `validators.json`

\* _Do not use production keys. Testnet only!_

## How to Contribute

1. Add your validator files in `validators/`:
   - `validator_0xNNNN.json`
   - `id_0xNNNN.json`
2. Ensure they are correct by running the validation locally:
    ```bash
    python tools/validate_validators.py
    ```
3. Open a PR to `main`.

## Validator Address Allocation

To prevent collisions and make validator ownership clear, each team is assigned a hex address range:

| Team       | Address Range (Hex) | Prefix |
|------------|---------------------|--------|
| Apollo     | 0x1000 – 0x10FF     | 0x1000 |
| Juno       | 0x2000 – 0x20FF     | 0x2000 |
| Madara     | 0x3000 – 0x30FF     | 0x3000 |
| Pathfinder | 0x4000 – 0x40FF     | 0x4000 |

Each validator metadata file must use an address from your team's assigned range.

## Merged File Format

Each entry in `validators.json`:

```json
{
  "address": "0x1000",
  "peer_id": "12D3KooW...",
  "listen_addresses": ["/ip4/127.0.0.1/tcp/50001"],
  "team": "team-a",
  "node_name": "alpha"
}
```