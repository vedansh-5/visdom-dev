# Copyright 2017-present, The Visdom Authors
BILLING = "/api/v1/billing"


def test_list_plans(client):
    response = client.get(f"{BILLING}/plans")
    assert response.status_code == 200
    plans = response.json()
    assert [plan["id"] for plan in plans] == ["free", "pro", "enterprise"]

    free, pro, enterprise = plans
    assert free["price"] == 0
    assert free["limits"] == {"workspaces": 1, "members": 3, "api_keys": 2}
    assert pro["price"] == 29
    assert pro["limits"]["members"] is None
    assert enterprise["price"] is None
    assert enterprise["limits"] == {"workspaces": None, "members": None, "api_keys": None}
    assert all(plan["features"] for plan in plans)


def test_subscription_requires_auth(client):
    assert client.get(f"{BILLING}/subscription").status_code == 401
    assert client.post(f"{BILLING}/subscription", json={"tier": "pro"}).status_code == 401


def test_fresh_user_subscription(client, make_user):
    user = make_user()
    response = client.get(f"{BILLING}/subscription", headers=user["headers"])
    assert response.status_code == 200
    data = response.json()
    assert data["tier"] == "free"
    assert data["plan"]["id"] == "free"
    assert data["usage"] == {
        "workspaces": {"used": 0, "limit": 1},
        "members": {"used": 0, "limit": 3},
        "api_keys": {"used": 0, "limit": 2},
    }


def test_subscription_usage_counts(client, make_user, make_workspace, add_member):
    owner = make_user()
    member = make_user()
    pending = make_user()
    ws1 = make_workspace(owner)
    make_workspace(owner)
    add_member(owner, ws1, member)
    client.post(
        f"/api/v1/workspaces/{ws1['id']}/members",
        json={"email": pending["email"], "role": "member"},
        headers=owner["headers"],
    )
    client.post("/api/v1/keys", json={"name": "usage-key"}, headers=owner["headers"])

    usage = client.get(f"{BILLING}/subscription", headers=owner["headers"]).json()["usage"]
    assert usage["workspaces"]["used"] == 2
    assert usage["members"]["used"] == 1
    assert usage["api_keys"]["used"] == 1

    member_usage = client.get(f"{BILLING}/subscription", headers=member["headers"]).json()["usage"]
    assert member_usage["workspaces"]["used"] == 0
    assert member_usage["members"]["used"] == 0
    assert member_usage["api_keys"]["used"] == 0


def test_change_plan(client, make_user):
    user = make_user()

    upgraded = client.post(
        f"{BILLING}/subscription", json={"tier": "pro"}, headers=user["headers"]
    )
    assert upgraded.status_code == 200
    assert upgraded.json()["tier"] == "pro"
    assert upgraded.json()["plan"]["id"] == "pro"
    assert upgraded.json()["usage"]["workspaces"]["limit"] == 10

    persisted = client.get(f"{BILLING}/subscription", headers=user["headers"]).json()
    assert persisted["tier"] == "pro"
    assert client.get("/api/v1/auth/me", headers=user["headers"]).json()["tier"] == "pro"

    downgraded = client.post(
        f"{BILLING}/subscription", json={"tier": "free"}, headers=user["headers"]
    )
    assert downgraded.json()["tier"] == "free"


def test_change_plan_invalid_tier(client, make_user):
    user = make_user()
    response = client.post(
        f"{BILLING}/subscription", json={"tier": "platinum"}, headers=user["headers"]
    )
    assert response.status_code == 422


WORKSPACES = "/api/v1/workspaces"
KEYS = "/api/v1/keys"


def test_free_plan_refuses_a_second_workspace(client, make_user):
    user = make_user()
    first = client.post(
        WORKSPACES, json={"name": "One", "slug": "limit-one"}, headers=user["headers"]
    )
    assert first.status_code == 201

    second = client.post(
        WORKSPACES, json={"name": "Two", "slug": "limit-two"}, headers=user["headers"]
    )
    assert second.status_code == 402
    assert "workspace limit" in second.json()["detail"]


def test_upgrading_raises_the_workspace_ceiling(client, make_user):
    user = make_user()
    assert (
        client.post(
            WORKSPACES, json={"name": "One", "slug": "up-one"}, headers=user["headers"]
        ).status_code
        == 201
    )
    assert (
        client.post(
            WORKSPACES, json={"name": "Two", "slug": "up-two"}, headers=user["headers"]
        ).status_code
        == 402
    )

    client.post(f"{BILLING}/subscription", json={"tier": "pro"}, headers=user["headers"])

    assert (
        client.post(
            WORKSPACES, json={"name": "Two", "slug": "up-two"}, headers=user["headers"]
        ).status_code
        == 201
    )


def test_an_unlimited_plan_is_never_refused(client, make_user):
    user = make_user()
    client.post(
        f"{BILLING}/subscription", json={"tier": "enterprise"}, headers=user["headers"]
    )
    for n in range(3):
        created = client.post(
            WORKSPACES,
            json={"name": f"W{n}", "slug": f"unlimited-{n}"},
            headers=user["headers"],
        )
        assert created.status_code == 201, created.text


def test_free_plan_refuses_a_third_api_key(client, make_user):
    user = make_user()
    for n in range(2):
        made = client.post(
            KEYS, json={"name": f"key-{n}", "scope": "org"}, headers=user["headers"]
        )
        assert made.status_code == 201, made.text

    third = client.post(
        KEYS, json={"name": "key-3", "scope": "org"}, headers=user["headers"]
    )
    assert third.status_code == 402
    assert "API key limit" in third.json()["detail"]


def test_the_billing_page_and_the_refusal_agree(client, make_user):
    """The number someone is shown is the number they are held to."""
    user = make_user()
    client.post(
        WORKSPACES, json={"name": "One", "slug": "agree-one"}, headers=user["headers"]
    )

    shown = client.get(f"{BILLING}/subscription", headers=user["headers"]).json()
    assert shown["usage"]["workspaces"] == {"used": 1, "limit": 1}

    refused = client.post(
        WORKSPACES, json={"name": "Two", "slug": "agree-two"}, headers=user["headers"]
    )
    assert refused.status_code == 402
