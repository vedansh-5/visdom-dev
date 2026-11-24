# Copyright 2017-present, The Visdom Authors
from datetime import timedelta

import pytest

from app.models import ContactMessage, utcnow
from app.routers import contact

URL = "/api/v1/contact"
MESSAGE = {"name": " Ana ", "email": "ana@fossasia.org", "topic": "Security", "message": " Can you help? "}


def test_contact_saved_without_sign_in(client, db_session):
    response = client.post(URL, json=MESSAGE)
    assert response.status_code == 204
    row = db_session.query(ContactMessage).one()
    assert (row.name, row.email, row.topic, row.message) == ("Ana", MESSAGE["email"], "Security", "Can you help?")
    assert row.handled is False
    assert row.sender_key and row.sender_key != "testclient"


@pytest.mark.parametrize(("field", "value"), [
    ("name", " "), ("name", "a" * 101), ("email", "invalid"), ("email", "a" * 249 + "@fossasia.org"),
    ("topic", "Sales"), ("topic", "a" * 60), ("message", ""), ("message", "a" * 5001), ("website", "a" * 201),
])
def test_rejects_invalid_fields(client, db_session, field, value):
    assert client.post(URL, json={**MESSAGE, field: value}).status_code == 422
    assert db_session.query(ContactMessage).count() == 0


def test_honeypot_silently_discards_and_leaves_the_quota_available(client, db_session):
    for _ in range(4):
        assert client.post(URL, json={**MESSAGE, "website": "spam"}).status_code == 204
    assert db_session.query(ContactMessage).count() == 0
    assert client.post(URL, json=MESSAGE).status_code == 204


def test_hourly_limit_is_per_peer_and_expires(client, db_session, monkeypatch):
    start = utcnow()
    monkeypatch.setattr(contact, "utcnow", lambda: start)
    for _ in range(3):
        assert client.post(URL, json=MESSAGE).status_code == 204
    refused = client.post(URL, json=MESSAGE, headers={"X-Forwarded-For": "198.51.100.8"})
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) == 3600
    assert db_session.query(ContactMessage).count() == 3
    client._transport.client = ("198.51.100.7", 54321)
    assert client.post(URL, json=MESSAGE).status_code == 204
    client._transport.client = ("testclient", 50000)
    monkeypatch.setattr(contact, "utcnow", lambda: start + timedelta(hours=1))
    assert client.post(URL, json=MESSAGE).status_code == 204


def test_retention_applies_to_open_and_handled_messages_and_expires_sender_keys(client, db_session, monkeypatch):
    start = utcnow()
    monkeypatch.setattr(contact, "utcnow", lambda: start)
    for handled in (True, False):
        assert client.post(URL, json=MESSAGE).status_code == 204
        row = db_session.query(ContactMessage).filter(ContactMessage.created_at == start).one()
        row.handled = handled
        row.created_at = start - timedelta(days=365)
        db_session.commit()
    assert client.post(URL, json=MESSAGE).status_code == 204
    db_session.query(ContactMessage).filter(ContactMessage.created_at == start).update(
        {"created_at": start - timedelta(hours=1)}
    )
    assert client.post(URL, json=MESSAGE).status_code == 204
    contact.expire(db_session)
    rows = db_session.query(ContactMessage).order_by(ContactMessage.created_at).all()
    assert len(rows) == 2
    assert rows[0].sender_key is None
    assert rows[1].sender_key


def test_gateway_and_overwritten_proxy_addresses_each_enforce_the_limit(client):
    for index in range(4):
        client._transport.client = (f"198.51.100.{index + 1}", 0)
        response = client.post(URL, json=MESSAGE, headers={"X-Real-IP": "192.0.2.10"})
        assert response.status_code == (204 if index < 3 else 429)
    client._transport.client = ("203.0.113.9", 59874)
    for index in range(4):
        response = client.post(URL, json=MESSAGE, headers={"X-Real-IP": f"192.0.2.{index + 20}"})
        assert response.status_code == (204 if index < 3 else 429)
