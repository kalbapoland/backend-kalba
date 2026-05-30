from datetime import UTC, datetime, timedelta


async def _create_workshop(client, trainer_token, payload):
    resp = await client.post(
        "/api/v1/workshops/",
        json=payload,
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _workshop_payload(**overrides):
    payload = {
        "title": "Morning Meditation",
        "description": "A relaxing session",
        "start_time": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "duration_minutes": 60,
        "price": "10.00",
        "max_participants": 10,
    }
    payload.update(overrides)
    return payload


async def test_my_kalba_schedule_returns_enrolled_workshops(
    client, trainer_token, user_token, group, regular_user, subscribe
):
    workshop_id = await _create_workshop(
        client,
        trainer_token,
        _workshop_payload(title="Scheduled Workshop", group_id=str(group.id)),
    )
    await subscribe(group, regular_user)

    enroll_resp = await client.post(
        f"/api/v1/workshops/{workshop_id}/enroll",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert enroll_resp.status_code == 200

    resp = await client.get(
        "/api/v1/users/me/my-kalba/schedule",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == workshop_id
    assert body[0]["is_enrolled"] is True


async def test_my_kalba_dashboard_returns_goal_and_stats(
    client, trainer_token, user_token, group, regular_user, subscribe
):
    workshop_id = await _create_workshop(
        client,
        trainer_token,
        _workshop_payload(title="Dashboard Workshop", group_id=str(group.id)),
    )
    await subscribe(group, regular_user)

    await client.post(
        f"/api/v1/workshops/{workshop_id}/enroll",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    resp = await client.get(
        "/api/v1/users/me/my-kalba/dashboard",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["goal"]["monthly_target"] == 4
    assert body["stats"]["monthly_target"] == 4
    assert body["stats"]["completed_this_week"] == 0
    assert body["stats"]["completed_this_month"] == 0


async def test_my_kalba_reschedule_creates_notification(
    client, trainer_token, user_token, group, regular_user, subscribe
):
    workshop_id = await _create_workshop(
        client,
        trainer_token,
        _workshop_payload(title="Reschedule Workshop", group_id=str(group.id)),
    )
    await subscribe(group, regular_user)

    enroll_resp = await client.post(
        f"/api/v1/workshops/{workshop_id}/enroll",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert enroll_resp.status_code == 200

    new_start_time = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    update_resp = await client.patch(
        f"/api/v1/workshops/{workshop_id}",
        json={"start_time": new_start_time},
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert update_resp.status_code == 200

    notif_resp = await client.get(
        "/api/v1/users/me/my-kalba/notifications?unread_only=true",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert notif_resp.status_code == 200
    notifications = notif_resp.json()
    assert len(notifications) == 1
    assert notifications[0]["type"] == "workshop_rescheduled"
    assert workshop_id in notifications[0]["payload"]["workshop_id"]
