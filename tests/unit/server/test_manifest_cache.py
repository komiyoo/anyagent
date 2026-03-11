from __future__ import annotations

import asyncio
from unittest.mock import patch

from anyagent.server.manifest_cache import ManifestCache, build_manifest_cache_key, extract_requested_tool_names


def test_build_manifest_cache_key_normalizes_order_and_whitespace() -> None:
    key1 = build_manifest_cache_key(
        tenant_id="  tenant-a ",
        agent_id="main",
        session_key="  sess-1 ",
        enabled_skills=[" skill-b ", "skill-a", "", "skill-a"],
        requested_tool_names=["tool.z", " tool.a ", "tool.z"],
        context={"b": 2, "a": 1},
    )
    key2 = build_manifest_cache_key(
        tenant_id="tenant-a",
        agent_id="main",
        session_key="sess-1",
        enabled_skills=["skill-a", "skill-b"],
        requested_tool_names=["tool.a", "tool.z"],
        context={"a": 1, "b": 2},
    )

    assert key1 == key2


def test_extract_requested_tool_names_filters_invalid_items() -> None:
    assert extract_requested_tool_names(
        [
            {"name": " core.web_fetch "},
            {"name": ""},
            {"nope": "ignored"},
            "bad",
            {"name": "exec"},
        ]
    ) == ["core.web_fetch", "exec"]


def test_manifest_cache_returns_deep_clone() -> None:
    async def _run() -> None:
        cache = ManifestCache(ttl_seconds=10.0)
        key = build_manifest_cache_key(
            tenant_id=None,
            agent_id="main",
            session_key="sess-1",
            enabled_skills=["skill-a"],
            requested_tool_names=["exec"],
            context={"x": 1},
        )
        original_tools = [{"name": "exec", "meta": {"kind": "command"}}]
        await cache.put(key, (original_tools, 3))

        original_tools[0]["meta"]["kind"] = "mutated-after-put"
        cached = await cache.get(key)
        assert cached is not None
        tools, version = cached
        tools[0]["meta"]["kind"] = "mutated-after-get"

        cached_again = await cache.get(key)
        assert cached_again is not None
        assert version == 3
        assert cached_again[0][0]["meta"]["kind"] == "command"

    asyncio.run(_run())


def test_manifest_cache_expires_entries() -> None:
    async def _run() -> None:
        cache = ManifestCache(ttl_seconds=1.0)
        key = build_manifest_cache_key(
            tenant_id=None,
            agent_id="main",
            session_key="sess-1",
            enabled_skills=None,
            requested_tool_names=None,
            context={},
        )
        with patch("anyagent.server.manifest_cache.time.monotonic", side_effect=[100.0, 100.5, 101.5]):
            await cache.put(key, ([{"name": "exec"}], 1))
            assert await cache.get(key) == ([{"name": "exec"}], 1)
            assert await cache.get(key) is None

    asyncio.run(_run())
