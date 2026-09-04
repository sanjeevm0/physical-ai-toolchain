from __future__ import annotations

import uuid

_SERVER_ID = str(uuid.uuid4())


class MultiInstanceServerIdentity:
    def __init__(self) -> None:
        pass

    def get_server_id(self) -> str:
        return _SERVER_ID
