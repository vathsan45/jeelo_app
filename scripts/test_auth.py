"""Unit test for Clerk JWT verification (auth.py), with no real Clerk network
calls or browser sign-in needed: a throwaway RSA key pair signs a fake token
in the same shape Clerk issues, and the JWKS fetch is monkeypatched to
"publish" that key pair's public half instead of hitting the real endpoint.

Run: python scripts/test_auth.py
"""

import os
import sys
import tempfile
import time
from pathlib import Path

tmp_db = Path(tempfile.gettempdir()) / "auth_test_scratch.db"
if tmp_db.exists():
    tmp_db.unlink()
os.environ["ELO_DB_PATH"] = str(tmp_db)
os.environ.setdefault("CLERK_ISSUER", "https://test-instance.clerk.accounts.dev")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from app import auth  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Player  # noqa: E402

Base.metadata.create_all(bind=engine)

failures = []


def check(label, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        failures.append(label)


# --- build a fake Clerk signing key + a token to match ---
private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
FAKE_KID = "test-key-1"

fake_jwks_response = {
    "keys": [{**jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True),
              "kid": FAKE_KID, "use": "sig", "alg": "RS256"}]
}

# monkeypatch the network fetch so auth._get_jwks() returns our fake key set
auth._get_jwks = lambda: fake_jwks_response["keys"]


def make_token(sub="user_abc123", name="Asha", issuer=None, exp_delta=3600, kid=FAKE_KID):
    headers = {"kid": kid}
    payload = {
        "sub": sub,
        "name": name,
        "iss": issuer or auth.CLERK_ISSUER,
        "iat": int(time.time()),
        "exp": int(time.time()) + exp_delta,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers=headers)


print("1) valid token verifies and extracts claims")
token = make_token(sub="user_valid")
claims = auth._verify_token(token)
check("sub claim extracted", claims["sub"] == "user_valid")

print("\n2) wrong issuer rejected")
bad = make_token(issuer="https://someone-elses-app.clerk.accounts.dev")
try:
    auth._verify_token(bad)
    check("wrong issuer rejected", False)
except jwt.PyJWTError:
    check("wrong issuer rejected", True)

print("\n3) expired token rejected")
expired = make_token(exp_delta=-60)  # well past the 10s clock-skew leeway
try:
    auth._verify_token(expired)
    check("expired token rejected", False)
except jwt.PyJWTError:
    check("expired token rejected", True)

print("\n4) unknown kid rejected (not just silently accepted)")
try:
    auth._verify_token(make_token(kid="some-other-key"))
    check("unknown kid rejected", False)
except (jwt.PyJWTError, KeyError):
    check("unknown kid rejected", True)

print("\n5) tampered signature rejected")
tampered = token[:-4] + ("AAAA" if token[-4:] != "AAAA" else "BBBB")
try:
    auth._verify_token(tampered)
    check("tampered signature rejected", False)
except jwt.PyJWTError:
    check("tampered signature rejected", True)

print("\n6) get_current_player creates a new Player on first sight")
db = SessionLocal()
before_count = db.query(Player).count()
player = auth.get_current_player(authorization=f"Bearer {make_token(sub='user_new_1')}", db=db)
check("player created", db.query(Player).count() == before_count + 1)
check("auth_user_id stored", player.auth_user_id == "user_new_1")
check("seeded at default rating", player.theta_overall == 1200.0 and player.rd_overall == 350.0)

print("\n7) get_current_player returns the SAME player on a second token for the same user")
player2 = auth.get_current_player(authorization=f"Bearer {make_token(sub='user_new_1')}", db=db)
check("same player_id returned", player2.player_id == player.player_id)
check("no duplicate row created", db.query(Player).filter_by(auth_user_id="user_new_1").count() == 1)

print("\n8) missing/malformed Authorization header rejected")
from fastapi import HTTPException  # noqa: E402

for bad_header in (None, "", "Bearer", "Basic abc123", "Bearer "):
    try:
        auth.get_current_player(authorization=bad_header, db=db)
        check(f"rejected header={bad_header!r}", False)
    except HTTPException as e:
        check(f"rejected header={bad_header!r} (401)", e.status_code == 401)

db.close()

print("\n" + ("ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILURES: {failures}"))
sys.exit(0 if not failures else 1)
