
import json
from pathlib import Path

def main():
    base_dir = Path("validators")
    output_file = Path("network-config/validators.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    merged = []

    for team_dir in base_dir.iterdir():
        if not team_dir.is_dir():
            continue
        for file in team_dir.glob("validator_0x*.json"):
            try:
                with open(file) as f:
                    validator = json.load(f)
                    merged.append(validator)
            except Exception as e:
                print(f"⚠️ Skipping {file}: {e}")

    # Sort by address for readability
    merged.sort(key=lambda v: int(v["address"], 16))

    with open(output_file, "w") as f:
        json.dump(merged, f, indent=2)
    print(f"✅ Wrote {len(merged)} validators to {output_file}")

if __name__ == "__main__":
    main()
