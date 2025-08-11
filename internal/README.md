## Internal Tools

The `internal/` subdirectory contains helper scripts used in CI workflows:

- `merge_validators.py`: Aggregates all individual validator metadata files into the canonical `validators.json`.
- `validate_validators.py`: Validates structure, naming, and content of validator and identity files before merging.
