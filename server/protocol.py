import json
from dataclasses import dataclass, asdict
from typing import Any, Optional


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
    acked_nodes: list[int]


def encode(obj: Any) -> bytes:
    """
    Codifica um objeto (dataclass ou dict) em JSON bytes.
    NÃO adiciona '\n' aqui se o driver já tratar; mas para consistência de linha,
    preferimos que o driver adicione '\n'. (Mantemos sem '\n' por compatibilidade.)
    """
    if hasattr(obj, "__dataclass_fields__"):
        payload = asdict(obj)
    elif isinstance(obj, dict):
        payload = obj
    else:
        # fallback
        payload = obj.__dict__

    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def decode(data: bytes) -> Optional[dict]:
    """
    Decodifica uma linha (bytes) para dict JSON.
    Ignora linhas vazias e logs tipo 'LOG: ...'.
    """
    s = data.decode("utf-8", errors="ignore").strip()
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
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None