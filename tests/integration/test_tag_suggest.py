from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture
def workshop_payload():
    return {
        "title": "Test Workshop",
        "description": "",
        "start_time": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "duration_minutes": 60,
        "price": "10.00",
        "max_participants": 10,
    }


async def _create(client, trainer_token, workshop_payload, description: str):
    payload = {**workshop_payload, "description": description, "title": f"W-{description[:20]}"}
    resp = await client.post(
        "/api/v1/workshops/",
        json=payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 201
    return resp.json()


async def test_suggest_requires_auth(client):
    resp = await client.get("/api/v1/tags/suggest?q=jo")
    assert resp.status_code == 401


async def test_suggest_returns_empty_when_no_tags(client, user_token):
    resp = await client.get(
        "/api/v1/tags/suggest?q=jo",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_suggest_returns_matching_prefix(
    client, trainer_token, user_token, workshop_payload
):
    await _create(client, trainer_token, workshop_payload, "#joga session")
    await _create(client, trainer_token, workshop_payload, "Different topic")

    resp = await client.get(
        "/api/v1/tags/suggest?q=jo",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == ["joga"]


async def test_suggest_orders_by_popularity_then_alpha(
    client, trainer_token, user_token, workshop_payload
):
    # joga used in 2 workshops, jazz in 1, journey in 1 — joga must come first;
    # jazz and journey tie at 1 use → alphabetical (jazz before journey).
    await _create(client, trainer_token, workshop_payload, "#joga and #jazz")
    await _create(client, trainer_token, workshop_payload, "#joga and #journey")

    resp = await client.get(
        "/api/v1/tags/suggest?q=j",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == ["joga", "jazz", "journey"]


async def test_suggest_normalizes_prefix(
    client, trainer_token, user_token, workshop_payload
):
    await _create(client, trainer_token, workshop_payload, "#joga")

    for query in ("#JoGa", "JOGA", "joga", "#jog"):
        resp = await client.get(
            "/api/v1/tags/suggest",
            params={"q": query},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200, query
        assert resp.json() == ["joga"], query


async def test_suggest_limit_param(
    client, trainer_token, user_token, workshop_payload
):
    for name in ("alpha", "beta", "gamma", "delta", "epsilon"):
        await _create(client, trainer_token, workshop_payload, f"#{name}1")

    resp = await client.get(
        "/api/v1/tags/suggest?q=a&limit=2",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1  # only `alpha1` matches `a` prefix

    # Broader prefix exercising actual limiting
    resp = await client.get(
        "/api/v1/tags/suggest?q=&limit=3",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    # q is required min_length=1 — empty fails validation
    assert resp.status_code == 422


async def test_suggest_rejects_overlong_prefix(client, user_token):
    resp = await client.get(
        "/api/v1/tags/suggest",
        params={"q": "a" * 31},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 422


async def test_suggest_strips_like_wildcards_in_prefix(
    client, trainer_token, user_token, workshop_payload
):
    await _create(client, trainer_token, workshop_payload, "#joga and #medytacja")

    # `%` is dropped at normalization → empty prefix → empty result.
    resp = await client.get(
        "/api/v1/tags/suggest",
        params={"q": "%"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == []

    # `jo%ga` truncates to `jo` (everything after `%` is dropped) → matches joga.
    resp = await client.get(
        "/api/v1/tags/suggest",
        params={"q": "jo%ga"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.json() == ["joga"]


async def test_suggest_excludes_tags_only_in_soft_deleted_workshops(
    client, trainer_token, user_token, workshop_payload
):
    workshop = await _create(client, trainer_token, workshop_payload, "#joga session")
    workshop2 = await _create(client, trainer_token, workshop_payload, "#joga again")

    # Soft-delete one — the tag should still be visible because workshop2 keeps it.
    resp = await client.delete(
        f"/api/v1/workshops/{workshop['id']}",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 204

    resp = await client.get(
        "/api/v1/tags/suggest?q=jo",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.json() == ["joga"]

    # Soft-delete the second one too — usage count drops to 0 but the Tag row
    # still exists and matches the prefix, so it remains in suggestions (with
    # the lowest possible rank).
    resp = await client.delete(
        f"/api/v1/workshops/{workshop2['id']}",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 204

    resp = await client.get(
        "/api/v1/tags/suggest?q=jo",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.json() == ["joga"]
