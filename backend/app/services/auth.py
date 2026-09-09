"""JWT auth — verifies Supabase access tokens via JWKS (ES256 by default)."""
import uuid as _uuid

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient

from app.config import settings


def get_current_user(request: Request) -> str:
    """Returns the authenticated user's uuid (sub claim) or raises 401."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = auth.removeprefix("Bearer ").strip()

    try:
        # Supabase exposes its public keys as a JWKS; handles kid/alg rotation
        jwks = PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json")
        key = jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, key.key, algorithms=["ES256", "HS256"], options={"verify_aud": False},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"invalid token: {e}")
    except Exception as e:
        raise HTTPException(401, f"auth backend unreachable or malformed: {e}")

    sub = claims.get("sub")
    if claims.get("role") != "authenticated" or not sub:
        raise HTTPException(401, "not a user access token")
    try:
        _uuid.UUID(sub)
    except ValueError:
        raise HTTPException(401, "malformed subject")
    return sub
