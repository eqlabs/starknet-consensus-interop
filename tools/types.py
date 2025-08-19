from typing import List, TypedDict, Optional

class SnapshotConfig(TypedDict, total=False):
    url: str
    checksum: Optional[str]
    extract_command: str
    target_path: str

class Validator(TypedDict):
    address: str
    peer_id: str
    listen_addresses: List[str]
    team: str
    node_name: str

class BootNode(TypedDict):
    peer_id: str
    listen_addresses: List[str]
    team: str
    node_name: str

class Instance(TypedDict):
    name: str

class Disk(TypedDict):
    source: str
    autoDelete: bool
    boot: bool 
