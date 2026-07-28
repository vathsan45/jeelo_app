"""Shared test-auth helper: mints fake-but-valid Clerk-shaped JWTs and
monkeypatches app.auth's JWKS fetch to accept them, so integration tests
never need a real browser sign-in or network call to Clerk.

Import test_auth.py's approach is duplicated here (rather than imported)
so each test script stays runnable standalone.
"""

import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

FAKE_KID = "test-key-1"
_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def patch_jwks(auth_module):
    """Point auth._get_jwks() at our fake key instead of the real network
    call. Call once, right after importing app.auth (or app.main, which
    imports it transitively)."""
    fake_jwk = {
        **jwt.algorithms.RSAAlgorithm.to_jwk(_private_key.public_key(), as_dict=True),
        "kid": FAKE_KID, "use": "sig", "alg": "RS256",
    }
    auth_module._get_jwks = lambda: [fake_jwk]


def make_token(sub, name="Test Player", issuer=None, auth_module=None):
    payload = {
        "sub": sub,
        "name": name,
        "iss": issuer or (auth_module.CLERK_ISSUER if auth_module else "test-issuer"),
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, _private_key, algorithm="RS256", headers={"kid": FAKE_KID})


def auth_headers(sub, name="Test Player", auth_module=None):
    return {"Authorization": f"Bearer {make_token(sub, name, auth_module=auth_module)}"}
