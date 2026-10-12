"""Provider kind names shared by the config schema and the model registry.

Kept separate so schema models do not import the resolution helpers.
"""

from __future__ import annotations

from typing import Literal


ModelProviderKind = Literal["openai", "openai_chat", "anthropic", "gemini"]
