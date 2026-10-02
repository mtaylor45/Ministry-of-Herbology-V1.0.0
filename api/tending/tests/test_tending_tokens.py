"""The only credential this application issues."""

from __future__ import annotations

from tending import tokens


def test_a_token_is_minted_from_secrets_and_is_never_repeated():
    minted = {tokens.mint() for _ in range(200)}
    assert len(minted) == 200
    assert all(len(token) >= 40 for token in minted)


def test_a_token_compares_equal_to_itself_and_nothing_else():
    token = tokens.mint()
    assert tokens.matches(token, token)
    assert not tokens.matches(token, tokens.mint())


def test_redaction_leaves_nothing_to_fetch_with():
    token = tokens.mint()
    redacted = tokens.redact(token)
    assert redacted.endswith("…")
    assert len(redacted) < 8
    assert token not in redacted


def test_the_subscribe_url_is_webcal_and_the_fetch_url_is_https():
    token = "abc123"
    assert tokens.webcal_url("https://example.net", token) == (
        f"webcal://example.net/api/v1/calendar/{token}.ics"
    )
    assert tokens.https_url("https://example.net/", token) == (
        f"https://example.net/api/v1/calendar/{token}.ics"
    )


def test_a_plain_http_deployment_still_gets_a_webcal_subscribe_url():
    """Apple and Google act on the scheme, and a self-hosted stack may be http."""
    assert tokens.webcal_url("http://localhost:8000", "t").startswith("webcal://")


def test_this_package_has_no_way_to_log_anything(repo_root):
    """Not a style check. A token in a log file is a token that has escaped.

    The package handles the only credential the application issues, so it does
    no logging at all rather than relying on every future line being careful.
    """
    package = repo_root / "api" / "tending"
    forbidden = ("import logging", "getLogger", "print(")
    for path in sorted(package.glob("*.py")):
        source = path.read_text()
        for needle in forbidden:
            assert needle not in source, f"{path.name} can emit output: {needle}"


def test_the_feed_response_never_carries_the_token_as_a_field():
    """It belongs in the URL a subscriber pastes, and in nothing else."""
    from tending import schemas

    token = tokens.mint()
    out = schemas.feed_out(
        {
            "id": "f1",
            "member_id": "m1",
            "name": "All rounds",
            "token": token,
            "filters": {},
            "push_target": "none",
            "last_rendered_at": None,
            "revoked_at": None,
        },
        base_url="https://example.net",
    )
    assert "token" not in out
    assert token in out["https_url"]


def test_a_revoked_feed_publishes_no_url_at_all():
    from datetime import UTC, datetime

    from tending import schemas

    out = schemas.feed_out(
        {
            "id": "f1",
            "member_id": "m1",
            "name": "Old phone",
            "token": tokens.mint(),
            "filters": {},
            "push_target": "none",
            "last_rendered_at": None,
            "revoked_at": datetime.now(UTC),
        },
        base_url="https://example.net",
    )
    assert out["revoked"] is True
    assert out["webcal_url"] == "" and out["https_url"] == ""
