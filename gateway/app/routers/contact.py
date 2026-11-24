# Copyright 2017-present, The Visdom Authors
import hmac
from datetime import timedelta
from ipaddress import ip_address
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import or_
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


def _quota_keys(address: str) -> list[str]:
    return [
        hmac.digest(settings.JWT_SECRET.encode(), f"contact:{slot}:{address}".encode(), "sha256").hex()
        for slot in range(MESSAGES_PER_WINDOW)
    ]


@router.post("/contact", status_code=204)
def submit_contact(payload: ContactForm, request: Request, db: Session = Depends(get_db)):
    if payload.website:
        return Response(status_code=204)

    peer_keys = _quota_keys(request.client.host if request.client else "unknown")
    try:
        proxy_keys = _quota_keys(str(ip_address(request.headers.get("x-real-ip", ""))))
    except ValueError:
        proxy_keys = []

    now = utcnow()
    matching = db.query(ContactMessage).filter(or_(
        ContactMessage.sender_key.in_(peer_keys), ContactMessage.proxy_sender_key.in_(proxy_keys)
    ))
    matching.filter(ContactMessage.created_at <= now - RATE_WINDOW).update(
        {ContactMessage.sender_key: None, ContactMessage.proxy_sender_key: None}, synchronize_session=False
    )
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else postgres_insert
    message = insert(ContactMessage).values(**payload.model_dump(exclude={"website"}), created_at=now)
    for peer_key in peer_keys:
        for proxy_key in proxy_keys or [None]:
            attempt = message.values(sender_key=peer_key, proxy_sender_key=proxy_key).on_conflict_do_nothing()
            if db.execute(attempt.returning(ContactMessage.id)).scalar_one_or_none() is not None:
                db.commit()
                return Response(status_code=204)

    raise HTTPException(
        429, "Too many messages. Please try again later.",
        headers={"Retry-After": str(int(RATE_WINDOW.total_seconds()))},
    )
