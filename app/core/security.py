"""Hashing de passwords y emision/verificacion de JWT.

Sin passlib (sin mantencion desde 2020 y roto con bcrypt >= 4.1) y sin
python-jose (sin releases desde 2021). Son ~40 lineas sobre `bcrypt` y `PyJWT`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

#  bcrypt trunca/rechaza sobre 72 bytes segun version; se corta explicito para
#  que el comportamiento no dependa de la version instalada.
_BCRYPT_MAX_BYTES = 72


class TokenError(Exception):
    """Token ausente, mal formado, vencido o con firma invalida."""


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    raw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(raw, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        #  Hash corrupto o de otro algoritmo: no autentica, pero no revienta.
        return False


def create_access_token(subject: str, role: str) -> tuple[str, int]:
    """Devuelve (token, segundos_de_vida)."""
    expires_in = settings.access_token_expire_minutes * 60
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    if payload.get("type") != "access":
        raise TokenError("tipo de token invalido")
    return payload
