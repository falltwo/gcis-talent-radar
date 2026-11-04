"""Shared transaction-safe workflow helpers."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid4())


def fail(message):
    raise HTTPException(409, message)
