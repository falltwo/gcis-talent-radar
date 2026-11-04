"""Server-owned service credentials for this backend MVP, not a browser login."""
import hmac
import json
import os
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    actor_id: str
    role: str


bearer = HTTPBearer(auto_error=False)


def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Principal:
    try:
        config = json.loads(os.environ.get("RECRUITMENT_API_TOKENS_JSON", "{}"))
        if not isinstance(config, dict) or not config:
            raise ValueError()
        for token, identity in config.items():
            if (len(token) < 32 or not isinstance(identity, dict)
                    or set(identity) != {"tenant_id", "actor_id", "role"}
                    or not all(isinstance(v, str) and v.strip() for v in identity.values())
                    or identity["role"] not in {"hr", "recruiter"}):
                raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(503, "Recruitment credentials are not configured correctly") from None
    if credentials:
        for token, identity in config.items():
            if hmac.compare_digest(credentials.credentials.encode(), token.encode()):
                return Principal(**identity)
    raise HTTPException(401, "Invalid recruitment credentials", headers={"WWW-Authenticate": "Bearer"})


def require_hr(principal: Principal):
    if principal.role != "hr":
        raise HTTPException(403, "HR approval is required")
