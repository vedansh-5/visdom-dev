# Copyright 2017-present, The Visdom Authors
import hmac
from datetime import timedelta
from ipaddress import ip_address
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_db
from app.models import ContactMessage, utcnow

router = APIRouter(tags=["contact"])
RATE_WINDOW = timedelta(hours=1)
MESSAGES_PER_WINDOW = 3
MESSAGE_RETENTION = timedelta(days=365)


class ContactForm(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100, pattern=r"^[^\x00]*$")
    email: EmailStr = Field(max_length=254)
    topic: Literal["General", "Billing", "Account", "Security", "Other"]
    message: str = Field(min_length=1, max_length=5000, pattern=r"^[^\x00]*$")
    website: str = Field(default="", max_length=200)


def expire(db: Session) -> None:
    now = utcnow()
    db.query(ContactMessage).filter(ContactMessage.created_at <= now - MESSAGE_RETENTION).delete()
    db.query(ContactMessage).filter(
        ContactMessage.sender_key.is_not(None), ContactMessage.created_at <= now - RATE_WINDOW
    ).update({ContactMessage.sender_key: None, ContactMessage.proxy_sender_key: None})
    db.commit()


def _visitor_address(request: Request) -> str:
    address = request.headers.get("x-real-ip", "").strip()
    if address:
        try:
            return str(ip_address(address))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def _quota_keys(address: str) -> list[str]:
    return [
        hmac.digest(settings.JWT_SECRET.encode(), f"contact:{slot}:{address}".encode(), "sha256").hex()
        for slot in range(MESSAGES_PER_WINDOW)
    ]


@router.post("/contact", status_code=204)
def submit_contact(payload: ContactForm, request: Request, db: Session = Depends(get_db)):
    if payload.website:
        return Response(status_code=204)

    keys = _quota_keys(_visitor_address(request))
    now = utcnow()
    cutoff = now - RATE_WINDOW
    db.query(ContactMessage).filter(
        ContactMessage.sender_key.in_(keys), ContactMessage.created_at <= cutoff
    ).update({ContactMessage.sender_key: None, ContactMessage.proxy_sender_key: None}, synchronize_session=False)
    previous_proxy_keys = set(db.scalars(select(ContactMessage.proxy_sender_key).where(
        ContactMessage.proxy_sender_key.in_(keys), ContactMessage.created_at > cutoff
    )))

    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else postgres_insert
    message = insert(ContactMessage).values(**payload.model_dump(exclude={"website"}), created_at=now)
    for key in keys:
        if key in previous_proxy_keys:
            continue
        attempt = message.values(sender_key=key).on_conflict_do_nothing(index_elements=[ContactMessage.sender_key])
        if db.execute(attempt.returning(ContactMessage.id)).scalar_one_or_none() is not None:
            db.commit()
            return Response(status_code=204)

    raise HTTPException(
        429, "Too many messages. Please try again later.",
        headers={"Retry-After": str(int(RATE_WINDOW.total_seconds()))},
    )
