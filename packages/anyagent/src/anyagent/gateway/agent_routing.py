from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Literal


class AgentRoutingError(Exception):
    pass


RoutingStrategy = Literal[
    "thread_binding",
    "message_hint",
    "channel_mapping",
    "static_bot_mapping",
    "default",
]


_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")
_HINT_SLASH_RE = re.compile(r"(?:^|\\s)/agent\\s+(?P<agent>[a-zA-Z0-9_.-]{1,64})(?:\\s|$)")
_HINT_DOLLAR_RE = re.compile(r"(?:^|\\s)\\$agent:(?P<agent>[a-zA-Z0-9_.-]{1,64})(?:\\s|$)")
_HINT_AT_RE = re.compile(r"(?:^|\\s)@(?P<agent>[a-zA-Z0-9_.-]{1,64})(?:\\s|$)")


def validate_agent_id(agent_id: str) -> str:
    if not isinstance(agent_id, str):
        raise AgentRoutingError("agent_id must be a string")
    agent_id = agent_id.strip()
    if not _AGENT_ID_RE.match(agent_id):
        raise AgentRoutingError("invalid agent_id (expected 1..64 chars of [a-zA-Z0-9_.-])")
    return agent_id


def channel_mapping_key(*, provider: str, chat_id: str) -> str:
    provider = provider.strip() if isinstance(provider, str) else ""
    chat_id = chat_id.strip() if isinstance(chat_id, str) else ""
    if not provider:
        raise AgentRoutingError("provider must be non-empty")
    if not chat_id:
        raise AgentRoutingError("chat_id must be non-empty")
    # 与 requirements.md 例子保持一致：feishu:chat_id=oc_123
    return f"{provider}:chat_id={chat_id}"


def thread_binding_key(*, provider: str, account_id: str, chat_id: str, thread_id: str | None) -> str:
    provider = provider.strip() if isinstance(provider, str) else ""
    account_id = account_id.strip() if isinstance(account_id, str) else ""
    chat_id = chat_id.strip() if isinstance(chat_id, str) else ""
    thread = thread_id.strip() if isinstance(thread_id, str) else ""
    if not provider:
        raise AgentRoutingError("provider must be non-empty")
    if not account_id:
        raise AgentRoutingError("account_id must be non-empty")
    if not chat_id:
        raise AgentRoutingError("chat_id must be non-empty")
    if not thread:
        # 平台不支持 thread 时：退化到 chat 维度的一次性绑定
        thread = chat_id
    return f"{provider}::{account_id}::{chat_id}::{thread}"


@dataclass(frozen=True)
class AgentRoutingDecision:
    agent_id: str
    strategy: RoutingStrategy
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


class ThreadBindingStore:
    """
    Thread Binding：对某个 thread 做一次性绑定（req-6-4）。
    v0 提供最小接口；具体持久化/TTL 由 Gateway 工程实现选择。
    """

    async def get(self, key: str) -> str | None:  # pragma: no cover
        raise NotImplementedError

    async def set(self, key: str, agent_id: str) -> None:  # pragma: no cover
        raise NotImplementedError


class InMemoryThreadBindingStore(ThreadBindingStore):
    def __init__(self) -> None:
        self._mu = asyncio.Lock()
        self._data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        async with self._mu:
            return self._data.get(key)

    async def set(self, key: str, agent_id: str) -> None:
        async with self._mu:
            # 一次性绑定：存在则不覆盖（保证“可解释”且避免被消息投毒）。
            self._data.setdefault(key, agent_id)


@dataclass(frozen=True)
class AgentRouterConfig:
    default_agent_id: str = "main"
    allow_at_hint: bool = False
    bind_thread_on_hint: bool = True

    static_bot_mapping: dict[str, str] = field(default_factory=dict)
    channel_mapping: dict[str, str] = field(default_factory=dict)


class AgentRouter:
    """
    多策略 agent_id 路由（req-6-4）：
    - Static Bot Mapping
    - Channel Mapping
    - Message Hint（/agent、$agent:...；@... 默认为关闭）
    - Thread Binding（一旦绑定则优先）

    目标：返回可解释、可审计的 decision（strategy + reason + details）。
    """

    def __init__(self, config: AgentRouterConfig, *, bindings: ThreadBindingStore | None = None) -> None:
        self._cfg = config
        self._bindings = bindings

        # 启动期 fail-fast：避免线上出现配置拼错导致 silent fallback
        validate_agent_id(self._cfg.default_agent_id)
        for k, v in self._cfg.static_bot_mapping.items():
            if not isinstance(k, str) or not k.strip():
                raise AgentRoutingError("static_bot_mapping keys must be non-empty strings")
            validate_agent_id(v)
        for k, v in self._cfg.channel_mapping.items():
            if not isinstance(k, str) or not k.strip():
                raise AgentRoutingError("channel_mapping keys must be non-empty strings")
            validate_agent_id(v)

    @staticmethod
    def _extract_hint_agent_id(message_text: str, *, allow_at_hint: bool) -> str | None:
        if not isinstance(message_text, str) or not message_text.strip():
            return None

        for pat in (_HINT_SLASH_RE, _HINT_DOLLAR_RE):
            m = pat.search(message_text)
            if m:
                return m.group("agent")

        if allow_at_hint:
            m = _HINT_AT_RE.search(message_text)
            if m:
                return m.group("agent")

        return None

    async def route(
        self,
        *,
        provider: str,
        account_id: str,
        bot_id: str | None,
        chat_id: str,
        thread_id: str | None,
        message_text: str | None,
    ) -> AgentRoutingDecision:
        provider = provider or ""
        account_id = account_id or ""
        chat_id = chat_id or ""
        thread_id = thread_id if isinstance(thread_id, str) else None
        bot_id = bot_id if isinstance(bot_id, str) else None
        message_text = message_text if isinstance(message_text, str) else ""

        # 1) Thread binding（最高优先级）
        if self._bindings is not None:
            key = thread_binding_key(
                provider=provider,
                account_id=account_id,
                chat_id=chat_id,
                thread_id=thread_id,
            )
            bound = await self._bindings.get(key)
            if bound is not None:
                return AgentRoutingDecision(
                    agent_id=validate_agent_id(bound),
                    strategy="thread_binding",
                    reason="thread already bound to agent_id",
                    details={"binding_key": key},
                )

        # 2) Message hint
        hinted = self._extract_hint_agent_id(message_text, allow_at_hint=self._cfg.allow_at_hint)
        if hinted is not None:
            hinted = validate_agent_id(hinted)
            details = {"hint": hinted}
            # 一次性绑定：把 hint 固化到 thread，后续自动复用
            if self._bindings is not None and self._cfg.bind_thread_on_hint:
                key = thread_binding_key(
                    provider=provider,
                    account_id=account_id,
                    chat_id=chat_id,
                    thread_id=thread_id,
                )
                await self._bindings.set(key, hinted)
                details["binding_key"] = key
                details["binding_action"] = "set_if_absent"
            return AgentRoutingDecision(
                agent_id=hinted,
                strategy="message_hint",
                reason="explicit hint parsed from message_text",
                details=details,
            )

        # 3) Channel mapping
        ckey = channel_mapping_key(provider=provider, chat_id=chat_id)
        mapped = self._cfg.channel_mapping.get(ckey)
        if mapped is not None:
            return AgentRoutingDecision(
                agent_id=validate_agent_id(mapped),
                strategy="channel_mapping",
                reason="matched channel mapping",
                details={"channel_key": ckey},
            )

        # 4) Static bot mapping
        if bot_id is not None and bot_id.strip():
            mapped = self._cfg.static_bot_mapping.get(bot_id.strip())
            if mapped is not None:
                return AgentRoutingDecision(
                    agent_id=validate_agent_id(mapped),
                    strategy="static_bot_mapping",
                    reason="matched static bot mapping",
                    details={"bot_id": bot_id.strip()},
                )

        # 5) Default
        return AgentRoutingDecision(
            agent_id=validate_agent_id(self._cfg.default_agent_id),
            strategy="default",
            reason="fallback to default_agent_id",
            details={},
        )

