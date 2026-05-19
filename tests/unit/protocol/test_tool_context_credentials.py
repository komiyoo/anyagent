from __future__ import annotations

import pytest
from pydantic import ValidationError

from anyagent.protocol.tool_runtime import AuthRef, ToolContext


def test_tool_context_allows_credential_id_reference() -> None:
    context = ToolContext.model_validate(
        {
            "auth_ref": {"kind": "bearer_token", "ref": "cred_api"},
            "channel": {"provider": "demo"},
            "credential_id": "cred_api",
            "token_count": 42,
        }
    )

    assert context.auth_ref == AuthRef(kind="bearer_token", ref="cred_api")
    assert context.model_extra["credential_id"] == "cred_api"
    assert context.model_extra["token_count"] == 42


@pytest.mark.parametrize(
    "payload",
    [
        {"token": "secret-token"},
        {"channel": {"authorization": "Bearer secret-token"}},
        {"ext": [{"api_key": "secret-key"}]},
    ],
)
def test_tool_context_rejects_plaintext_secret_fields(payload: dict) -> None:
    with pytest.raises(ValidationError, match="auth_ref"):
        ToolContext.model_validate(payload)
