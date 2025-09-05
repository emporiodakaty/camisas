# camisas/utils.py
from __future__ import annotations

import json
import secrets
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.fields.files import FieldFile
from django.utils import timezone


# ====== Tokens / Identificadores ======

def gen_approval_token() -> str:
    """Token hex (64 chars) para aprovação pública de orçamento."""
    return secrets.token_hex(32)


def gen_artwork_token() -> str:
    """Token hex (64 chars) para aprovação pública de arte."""
    return secrets.token_hex(32)


def gerar_numero_orcamento(prefix: str = "ORC") -> str:
    """
    Gera um identificador legível para orçamentos.
    Ex.: ORC-20250825-123456
    """
    today = timezone.localdate()
    seq = secrets.randbelow(10**6)  # 000000–999999
    return f"{prefix}-{today.strftime('%Y%m%d')}-{seq:06d}"


# ====== Serialização segura (para JSON / templates) ======

def _to_primitive(val: Any):
    if isinstance(val, FieldFile):
        # Nunca usar .url aqui; se não há arquivo, .url levanta erro.
        return val.name or None
    if isinstance(val, Decimal):
        # Mantemos como string para valores monetários precisos.
        return str(val)
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return val


def primitivize(obj: Any):
    if isinstance(obj, dict):
        return {k: primitivize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [primitivize(v) for v in obj]
    return _to_primitive(obj)


def jsonsafe(payload: Any):
    """Converte qualquer payload em estrutura JSON-safe (sem Decimal/datetime/FieldFile)."""
    return json.loads(json.dumps(primitivize(payload), cls=DjangoJSONEncoder))


__all__ = [
    "gen_approval_token",
    "gen_artwork_token",
    "gerar_numero_orcamento",
    "primitivize",
    "jsonsafe",
]
