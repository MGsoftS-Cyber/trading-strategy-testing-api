"""Authorized workflows commit input records and replay receipts atomically."""

import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .models import RequestRecord


def mutation(db, user, scope, key, payload, work):
    """Commit the business changes and replay receipt in one transaction.

    A database unique constraint also protects concurrent repeated requests.
    Any failed work is rolled back when the request-scoped session closes.
    """
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    existing = db.scalar(
        select(RequestRecord).where(
            RequestRecord.user_id == user.id, RequestRecord.scope == scope, RequestRecord.key == key
        )
    )
    if existing:
        if existing.payload_hash != fingerprint:
            raise HTTPException(409, "This request key was used with different data.")
        return existing.response
    try:
        result = work()
        db.add(RequestRecord(user_id=user.id, scope=scope, key=key, payload_hash=fingerprint, response=result))
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        winner = db.scalar(
            select(RequestRecord).where(
                RequestRecord.user_id == user.id, RequestRecord.scope == scope, RequestRecord.key == key
            )
        )
        if winner and winner.payload_hash == fingerprint:
            return winner.response
        raise HTTPException(
            409, "A conflicting write occurred. Refresh the data and retry with a new request key."
        ) from None
