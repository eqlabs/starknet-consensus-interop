import json
import os
import re
import sys
from pathlib import Path

HEX_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]+$")
PEER_ID_RE = re.compile(r"^12D3KooW[1-9A-HJ-NP-Za-km-z]{40,}$")
FILENAME_RE = re.compile(r"^validator_0x[0-9a-fA-F]+\.json$")

def validate_validator_entry(meta_path, keypair_path):
    errors = []

    if not FILENAME_RE.match(meta_path.name):
        errors.append(f"{meta_path}: Filename does not match expected pattern 'validator_0xNNNN.json'")
        return errors

    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except Exception as e:
        errors.append(f"Failed to read or parse {meta_path}: {e}")
        return errors

    address = meta.get("address")
    peer_id = meta.get("peer_id")
    listen_addresses = meta.get("listen_addresses")

    if not address or not HEX_ADDRESS_RE.match(address):
        errors.append(f"{meta_path}: 'address' is missing or not a valid hex string (e.g., 0x1000)")

    if not peer_id or not PEER_ID_RE.match(peer_id):
        errors.append(f"{meta_path}: 'peer_id' is missing or not a valid libp2p base58 string")

    if not isinstance(listen_addresses, list) or not listen_addresses:
        errors.append(f"{meta_path}: 'listen_addresses' must be a non-empty list")
    else:
        for addr in listen_addresses:
            if not isinstance(addr, str) or not addr.startswith("/"):
                errors.append(f"{meta_path}: invalid listen address format: {addr}")

    try:
        with open(keypair_path) as f:
            keypair = json.load(f)
    except Exception as e:
        errors.append(f"Failed to read or parse {keypair_path}: {e}")
        return errors

    if "private_key" not in keypair:
        errors.append(f"{keypair_path}: Missing 'private_key'")
    if "peer_id" not in keypair:
        errors.append(f"{keypair_path}: Missing 'peer_id'")

    if peer_id != keypair.get("peer_id"):
        errors.append(f"{meta_path} and {keypair_path} have mismatched peer_id")

    return errors


def main():
    base_dir = Path("validators")
    all_errors = []

    for team_dir in base_dir.iterdir():
        if not team_dir.is_dir():
            continue
        for file in team_dir.glob("validator_0x*.json"):
            if not FILENAME_RE.match(file.name):
                all_errors.append(f"Unexpected filename: {file.name} (must match 'validator_0xNNNN.json')")
                continue
            validator_id = file.stem.split("_")[1]
            keypair_file = team_dir / f"id_{validator_id}.json"
            if not keypair_file.exists():
                all_errors.append(f"Missing keypair file: {keypair_file}")
                continue
            errors = validate_validator_entry(file, keypair_file)
            all_errors.extend(errors)

    if all_errors:
        for error in all_errors:
            print("❌", error)
        sys.exit(1)
    else:
        print("✅ All validator metadata and keypair files are valid.")

if __name__ == "__main__":
    main()
