from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

from anyagent.protocol.tool_runtime import ChannelContext

from .sequencer import KeyedSequencer


class SessionBindingError(Exception):
    pass


_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


def _encode_part(v: str, *, label: str) -> str:
    if not isinstance(v, str):
        raise SessionBindingError(f"{label} must be a string")
    v = v.strip()
    if not v:
        raise SessionBindingError(f"{label} must be non-empty")
    if len(v) > 256:
        raise SessionBindingError(f"{label} too long (max 256)")
    # 只允许一小部分安全字符，其余统一 percent-encode，避免分隔符冲突与日志污染。
    return quote(v, safe="-._~")


def session_key_for_thread(
    *,
    provider: str,
    account_id: str,
    chat_id: str,
    thread_id: str | None,
) -> str:
    """
    将“平台 thread”映射为稳定的 session_key（req-6-3）。

    约定：
    - provider/account_id/chat_id 必须存在
    - thread_id 为空时，按 chat_id 退化（平台不支持 thread 的场景）
    """
    thread = thread_id.strip() if isinstance(thread_id, str) else ""
    thread = thread if thread else chat_id

    p = _encode_part(provider, label="provider")
    a = _encode_part(account_id, label="account_id")
    c = _encode_part(chat_id, label="chat_id")
    t = _encode_part(thread, label="thread_id")

    # 前缀用于避免与用户自定义 session_key 冲突，也便于日志识别。
    return f"channel_thread::{p}::{a}::{c}::{t}"


def session_key_from_channel_context(channel: ChannelContext) -> str:
    if not isinstance(channel, ChannelContext):
        raise SessionBindingError("channel must be a ChannelContext")
    return session_key_for_thread(
        provider=channel.provider or "",
        account_id=channel.account_id or "",
        chat_id=channel.chat_id or "",
        thread_id=channel.thread_id,
    )


def session_partition_key(*, agent_id: str, session_key: str) -> str:
    """
    按固定规则生成 session_partition_key（req-6-3 / requirements.md 4.3.1）：
    - `session_partition_key = "{agent_id}::{session_key}"`
    """
    if not isinstance(session_key, str) or not session_key.strip():
        raise SessionBindingError("session_key must be non-empty")
    agent_id = agent_id.strip() if isinstance(agent_id, str) else ""
    if not _AGENT_ID_RE.match(agent_id):
        raise SessionBindingError("invalid agent_id (expected 1..64 chars of [a-zA-Z0-9_.-])")
    if session_key.startswith("::") or session_key.endswith("::"):
        raise SessionBindingError("invalid session_key")
    return f"{agent_id}::{session_key}"


@dataclass(frozen=True)
class SessionBinding:
    session_key: str
    session_partition_key: str


def bind_session(
    *,
    agent_id: str,
    provider: str,
    account_id: str,
    chat_id: str,
    thread_id: str | None,
) -> SessionBinding:
    sk = session_key_for_thread(
        provider=provider,
        account_id=account_id,
        chat_id=chat_id,
        thread_id=thread_id,
    )
    spk = session_partition_key(agent_id=agent_id, session_key=sk)
    return SessionBinding(session_key=sk, session_partition_key=spk)


def bind_session_from_tool_context(
    *,
    agent_id: str,
    tool_context: dict[str, Any],
) -> SessionBinding:
    """
    适配 ToolContext（protocol/tool_runtime.py）形态的最小 helper：
    - 从 tool_context["channel"] 读取 provider/account_id/chat_id/thread_id
    """
    if not isinstance(tool_context, dict):
        raise SessionBindingError("tool_context must be an object")
    channel = tool_context.get("channel")
    if not isinstance(channel, dict):
        raise SessionBindingError("tool_context.channel must be an object")

    return bind_session(
        agent_id=agent_id,
        provider=str(channel.get("provider") or ""),
        account_id=str(channel.get("account_id") or ""),
        chat_id=str(channel.get("chat_id") or ""),
        thread_id=channel.get("thread_id") if isinstance(channel.get("thread_id"), str) else None,
    )


async def run_in_session(
    sequencer: KeyedSequencer,
    binding: SessionBinding,
    fn: Callable[[], Awaitable[Any]],
) -> Any:
    """
    便捷封装：用 session_partition_key 做会话内串行化（req-6-3）。
    """
    return await sequencer.run(binding.session_partition_key, fn)
