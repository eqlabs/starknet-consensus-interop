from typing import List, TypedDict

class Validator(TypedDict):
    address: str
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
