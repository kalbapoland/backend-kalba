"""Pure-unit tests for the notifications dispatch service.

No DB, no HTTP — exercises classification, redaction, and chunking
helpers in isolation. End-to-end behaviour is covered in
`tests/integration/test_notifications_dispatch.py`.
"""

import pytest

from app.services.notifications import (
    PushMessage,
    _BatchCounts,
    _build_message,
    _chunks,
    _classify_tickets,
    _redact_token,
)


# --- _redact_token ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ExponentPushToken[abcdef123456]", "ExponentPushToken[...3456]"),
        ("ExponentPushToken[ab]", "ExponentPushToken[...]"),
        ("garbage", "<malformed>"),
        ("", "<malformed>"),
    ],
)
def test_redact_token(raw: str, expected: str) -> None:
    assert _redact_token(raw) == expected


# --- _chunks ---


def test_chunks_evenly_divisible() -> None:
    assert list(_chunks(["a", "b", "c", "d"], 2)) == [["a", "b"], ["c", "d"]]


def test_chunks_with_remainder() -> None:
    assert list(_chunks(["a", "b", "c", "d", "e"], 2)) == [
        ["a", "b"],
        ["c", "d"],
        ["e"],
    ]


def test_chunks_empty_input() -> None:
    assert list(_chunks([], 10)) == []


def test_chunks_smaller_than_size() -> None:
    assert list(_chunks(["a"], 100)) == [["a"]]


# --- _build_message ---


def test_build_message_includes_required_fields() -> None:
    msg = PushMessage(title="t", body="b")
    out = _build_message("ExponentPushToken[xyz]", msg)
    assert out == {
        "to": "ExponentPushToken[xyz]",
        "title": "t",
        "body": "b",
        "sound": "default",
    }


def test_build_message_includes_data_when_provided() -> None:
    msg = PushMessage(title="t", body="b", data={"workshop_id": "abc"})
    out = _build_message("tok", msg)
    assert out["data"] == {"workshop_id": "abc"}


def test_build_message_omits_data_when_none() -> None:
    msg = PushMessage(title="t", body="b")
    out = _build_message("tok", msg)
    assert "data" not in out


# --- _classify_tickets ---


def test_classify_all_ok() -> None:
    counts, invalid = _classify_tickets(
        ["t1", "t2"],
        [{"status": "ok", "id": "1"}, {"status": "ok", "id": "2"}],
    )
    assert counts == _BatchCounts(sent=2, invalidated=0, failed=0)
    assert invalid == []


def test_classify_device_not_registered_collected() -> None:
    counts, invalid = _classify_tickets(
        ["t1", "t2"],
        [
            {"status": "ok", "id": "1"},
            {"status": "error", "message": "gone", "details": {"error": "DeviceNotRegistered"}},
        ],
    )
    assert counts == _BatchCounts(sent=1, invalidated=1, failed=0)
    assert invalid == ["t2"]


def test_classify_other_error_kept_as_failed() -> None:
    counts, invalid = _classify_tickets(
        ["t1"],
        [
            {
                "status": "error",
                "message": "Message too big",
                "details": {"error": "MessageTooBig"},
            }
        ],
    )
    assert counts == _BatchCounts(sent=0, invalidated=0, failed=1)
    assert invalid == []


def test_classify_error_without_details_field() -> None:
    """Some Expo errors arrive without a `details` object."""
    counts, invalid = _classify_tickets(
        ["t1"], [{"status": "error", "message": "wat"}]
    )
    assert counts.failed == 1
    assert invalid == []


def test_classify_length_mismatch_marks_all_failed() -> None:
    """Transport error returned [], or partial response — be conservative."""
    counts, invalid = _classify_tickets(["t1", "t2", "t3"], [])
    assert counts == _BatchCounts(sent=0, invalidated=0, failed=3)
    assert invalid == []
