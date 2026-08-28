"""Signed approval tokens (JWT).

FastAPI mints a short-lived JWT per processed document; n8n embeds the token in
the broker's draft email as `/approve/{token}`. On click, FastAPI verifies the
signature + expiry, then approves (with a double-approval guard).
"""
from __future__ import annotations

import datetime as dt

import jwt

from config import settings


class TokenExpired(Exception):
    pass


class TokenInvalid(Exception):
    pass


def create_approval_token(document_id: str, brokerage_id: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "document_id": document_id,
        "brokerage_id": brokerage_id,
        "scope": "approve",
        "iat": now,
        "exp": now + dt.timedelta(hours=settings.approval_token_ttl_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_approval_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpired() from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalid() from exc
    if payload.get("scope") != "approve":
        raise TokenInvalid()
    return payload
