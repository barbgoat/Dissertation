# server/protocol.py
import json
from dataclasses import dataclass, asdict
from typing import Any, Optional, Dict, List, Union


@dataclass
class UplinkFrame:
    devaddr: int
    payload: str
    tx_end_ts: int


@dataclass
class Beacon:
    sf_id: int
    gw_ts: int


@dataclass
class Sack:
    sf_id: int
    acked_nodes: List[int]


def encode(obj: Any) -> bytes:
    """
    Codifica um objeto (dataclass ou dict) em JSON bytes.
    NÃO inclui '\n' (o transport/driver adiciona '\n').
    """
    if hasattr(obj, "__dataclass_fields__"):
        payload = asdict(obj)
    elif isinstance(obj, dict):
        payload = obj
    else:
        payload = getattr(obj, "__dict__", {"value": str(obj)})

    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def decode(data: Union[bytes, str]) -> Optional[Dict[str, Any]]:
    """
    Decodifica uma linha (bytes/str) para dict JSON.
    Ignora linhas vazias e logs tipo 'LOG: ...'.
    """
    if isinstance(data, bytes):
        s = data.decode("utf-8", errors="ignore")
    else:
        s = data

    s = s.strip()  # remove \r\n e espaços
    if not s:
        return None

    # Ignorar logs/debug do nó
    if s.startswith("LOG:"):
        return None

    # JSON deve ser objeto
    if not (s.startswith("{") and s.endswith("}")):
        return None

    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None

    return obj if isinstance(obj, dict) else None