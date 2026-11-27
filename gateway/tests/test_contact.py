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


def test_hourly_limit_without_real_ip_uses_the_peer_and_expires(client, db_session, monkeypatch):
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


def test_each_visitor_behind_one_proxy_has_three_slots(client, db_session):
    client._transport.client = ("172.19.0.2", 50000)
    addresses = ["192.0.2.10", "192.0.2.11", "2001:db8::12"]
    for _ in range(3):
        for address in addresses:
            response = client.post(URL, json=MESSAGE, headers={"X-Real-IP": address})
            assert response.status_code == 204
    assert client.post(URL, json=MESSAGE, headers={"X-Real-IP": addresses[0]}).status_code == 429
    assert db_session.query(ContactMessage).count() == 9


def test_same_visitor_keeps_one_quota_with_or_without_a_real_ip_header(client):
    address = "192.0.2.20"
    client._transport.client = (address, 50000)
    assert client.post(URL, json=MESSAGE).status_code == 204
    client._transport.client = ("172.19.0.2", 50000)
    for _ in range(2):
        assert client.post(URL, json=MESSAGE, headers={"X-Real-IP": address}).status_code == 204
    assert client.post(URL, json=MESSAGE, headers={"X-Real-IP": address}).status_code == 429


def test_malformed_real_ip_falls_back_to_the_peer(client):
    for _ in range(3):
        assert client.post(URL, json=MESSAGE).status_code == 204
    assert client.post(URL, json=MESSAGE, headers={"X-Real-IP": "invalid"}).status_code == 429


def test_recent_messages_with_old_proxy_keys_count_until_expiry(client, db_session, monkeypatch):
    start = utcnow()
    address = "192.0.2.15"
    for peer_key, visitor_key in zip(contact._quota_keys("172.19.0.2"), contact._quota_keys(address), strict=True):
        db_session.add(ContactMessage(**MESSAGE, created_at=start, sender_key=peer_key, proxy_sender_key=visitor_key))
    db_session.commit()
    headers = {"X-Real-IP": address}
    monkeypatch.setattr(contact, "utcnow", lambda: start + timedelta(minutes=59))
    assert client.post(URL, json=MESSAGE, headers=headers).status_code == 429
    monkeypatch.setattr(contact, "utcnow", lambda: start + timedelta(hours=1))
    assert client.post(URL, json=MESSAGE, headers=headers).status_code == 204
