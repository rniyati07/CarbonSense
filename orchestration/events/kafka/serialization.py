from __future__ import annotations

import datetime
import json
from dataclasses import asdict
from typing import Any
from uuid import UUID


class _EventEncoder(json.JSONEncoder):
    def default(self, o: object) -> Any:
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime.datetime):
            return o.isoformat()
        return super().default(o)


def to_json_bytes(event: object) -> bytes:
    return json.dumps(asdict(event), cls=_EventEncoder).encode("utf-8")  # type: ignore[arg-type]


def from_json_dict(data: bytes) -> dict[str, Any]:
    return json.loads(data.decode("utf-8"))  # type: ignore[no-any-return]
