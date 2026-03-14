from __future__ import annotations

from anyagent.protocol.stage_events import summarize_command, summarize_payload


def test_summarize_command_hides_secret_like_preview() -> None:
    summary = summarize_command("curl https://example.com -H 'Authorization: Bearer super-secret-token'")

    assert summary.bytes > 0
    assert summary.sha256
    assert summary.preview is None
    assert summary.preview_truncated is False


def test_summarize_payload_only_exposes_object_keys_preview() -> None:
    summary = summarize_payload(
        {
            "authorization": "Bearer super-secret-token",
            "password": "secret-password",
            "nested": {"api_key": "sk-hidden"},
        }
    )

    assert summary.bytes > 0
    assert summary.sha256
    assert summary.preview == "object keys: authorization,nested,password"
    assert "super-secret-token" not in (summary.preview or "")
    assert "secret-password" not in (summary.preview or "")
