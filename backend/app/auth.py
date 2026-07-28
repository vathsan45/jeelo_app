"""Clerk session-token verification.

Every authenticated endpoint depends on get_current_player(), which is the
ONLY place player identity is ever derived from — never trust a player_id
passed in a URL or request body. This is what closes the IDOR hole where
anyone could read/mutate another player's data just by knowing their UUID.
"""

import os
import time

import jwt
import requests
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session as DBSession

from .database import get_db
from .models import Player

CLERK_ISSUER = os.environ.get("CLERK_ISSUER", "").rstrip("/")
_JWKS_URL = f"{CLERK_ISSUER}/.well-known/jwks.json"

_jwks_cache = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL_SECONDS = 3600  # Clerk's signing keys rotate rarely; cache an hour


def _get_jwks():
    now = time.time()
    if _jwks_cache["keys"] is None or now - _jwks_cache["fetched_at"] > _JWKS_TTL_SECONDS:
        resp = requests.get(_JWKS_URL, timeout=5)
        resp.raise_for_status()
        _jwks_cache["keys"] = resp.json()["keys"]
        _jwks_cache["fetched_at"] = now
    return _jwks_cache["keys"]


def _verify_token(token: str) -> dict:
    """Decode + verify a Clerk session JWT. Raises jwt.PyJWTError (or a
    KeyError if the key id isn't found) on any failure — caller turns that
    into a 401."""
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header["kid"]

    keys = _get_jwks()
    jwk = next((k for k in keys if k["kid"] == kid), None)
    if jwk is None:
        # signing keys may have rotated since our cache was built — refresh
        # once and retry before giving up
        _jwks_cache["keys"] = None
        keys = _get_jwks()
        jwk = next((k for k in keys if k["kid"] == kid), None)
        if jwk is None:
            raise jwt.InvalidKeyError(f"no matching JWKS key for kid={kid}")

    public_key = jwt.PyJWK.from_dict(jwk).key
    return jwt.decode(
        token,
        key=public_key,
        algorithms=["RS256"],
        issuer=CLERK_ISSUER,
        # small clock-skew tolerance on exp/iat/nbf — Clerk's own backend
        # SDKs apply the same leeway, since strict zero-tolerance comparison
        # against two different servers' clocks is a common false rejection
        leeway=10,
        options={"verify_aud": False},  # Clerk session tokens don't set aud
    )


def get_current_player(
    authorization: str = Header(None),
    db: DBSession = Depends(get_db),
) -> Player:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()

    try:
        claims = _verify_token(token)
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"invalid token: {e}")

    auth_user_id = claims.get("sub")
    if not auth_user_id:
        raise HTTPException(status_code=401, detail="token missing sub claim")

    player = db.query(Player).filter_by(auth_user_id=auth_user_id).first()
    if player is None:
        # first request from this Clerk user — create their player row now,
        # seeded at the standard starting rating like any new player
        name = claims.get("name") or claims.get("email") or "Player"
        player = Player(auth_user_id=auth_user_id, name=name)
        db.add(player)
        db.commit()
        db.refresh(player)

    return player
