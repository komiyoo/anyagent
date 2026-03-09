from __future__ import annotations

import re
from fnmatch import fnmatchcase
from typing import Any

import jsonschema

from .models import RegisteredTool, ToolCategory, ToolDefinition, ToolHandler


RESERVED_NAMES = {
    # v0 允许的系统保留工具名（Codex 风格 multi-agent 原语）
    "spawn_agent",
    "send_input",
    "wait",
    "close_agent",
    "resume_agent",
    # 统一命令执行入口（沙箱路由，core 类别）
    "exec",
}

TOOL_NAME_RE = re.compile(r"^[a-z0-9_.-]+$")
TOOL_PREFIX_RE = re.compile(r"^[a-z0-9_.-]+\\.$")


class ToolRegistrationError(Exception):
    pass


class ToolNameValidationError(ToolRegistrationError):
    pass


class ToolRegistry:
    """
    v0 Tool Registry（单一真源）：
    - 工具注册：register_tool
    - 查询：list/get
    - 参数 schema 校验（jsonschema）
    - toolset_version：用于 manifest/execute 的一致性快照
    """

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._namespace_routes: dict[str, str] = {}
        self._toolset_version: int = 1

    @property
    def toolset_version(self) -> int:
        return self._toolset_version

    @staticmethod
    def _expected_category_for_name(name: str) -> ToolCategory | None:
        if name in RESERVED_NAMES:
            return "core"
        if name.startswith("core."):
            return "core"
        # Privileged internal tools (v1 Credential Vault).
        if name.startswith("admin."):
            return "core"
        if name.startswith("app."):
            return "app"
        if name.startswith("sandbox."):
            return "sandbox"
        # channel：用 <channel>.* 作为命名空间（feishu/discord/telegram/web 等）
        if "." in name:
            return "channel"
        return None

    @staticmethod
    def _validate_tool_name(name: str) -> None:
        if name in RESERVED_NAMES:
            # 保留名例外：允许 snake_case，但必须精确命中集合，不允许扩展/变体。
            return
        if not TOOL_NAME_RE.match(name):
            raise ToolNameValidationError(f"invalid tool name: {name}")
        if name.startswith(".") or name.endswith(".") or ".." in name:
            raise ToolNameValidationError(f"invalid tool name: {name}")

    @staticmethod
    def _validate_parameters_schema(schema: dict[str, Any]) -> None:
        if not isinstance(schema, dict):
            raise ToolRegistrationError("parameters must be an object")
        if schema.get("type") != "object":
            raise ToolRegistrationError("parameters.type must be 'object'")
        if schema.get("additionalProperties") is not False:
            raise ToolRegistrationError("parameters.additionalProperties must be false")
        if "required" not in schema or not isinstance(schema["required"], list):
            raise ToolRegistrationError("parameters.required must be explicitly provided as a list")

        # 基础 JSON Schema 校验（避免明显不合法）
        try:
            jsonschema.Draft7Validator.check_schema(schema)
        except Exception as e:  # noqa: BLE001
            raise ToolRegistrationError(f"invalid parameters schema: {e}") from e

    def register_tool(self, tool: ToolDefinition, handler: ToolHandler) -> None:
        self._validate_tool_name(tool.name)

        expected = self._expected_category_for_name(tool.name)
        if expected is None:
            raise ToolRegistrationError(f"cannot infer category from tool name: {tool.name}")
        if tool.category != expected:
            raise ToolRegistrationError(
                f"tool.category mismatch: name={tool.name} expected={expected} got={tool.category}"
            )

        self._validate_parameters_schema(tool.parameters)

        if tool.name in self._tools:
            # v0 强制：禁止覆盖/替换，避免投毒与 schema 漂移
            raise ToolRegistrationError(f"duplicate tool registration: {tool.name}")

        self._tools[tool.name] = RegisteredTool(definition=tool, handler=handler)
        self._toolset_version += 1

    # ---- Cross-language friendly aliases (v0) ----
    def registerTool(self, tool: ToolDefinition, handler: ToolHandler) -> None:  # noqa: N802
        self.register_tool(tool, handler)

    def register_namespace_route(self, prefix: str, executor_id: str) -> None:
        """
        可选：显式声明某个前缀由哪个 executor 处理（用于联邦路由与后续拆分）。
        v0 约束：
        - 常规前缀：prefix 必须以 '.' 结尾，且不允许使用通配符。
        - 保留名：允许使用保留工具名作为“精确命中路由表项”。
        """
        if not isinstance(prefix, str) or not prefix:
            raise ToolRegistrationError("prefix must be a non-empty string")
        if prefix in RESERVED_NAMES:
            # 精确命中：不要求以 '.' 结尾
            pass
        else:
            if not TOOL_PREFIX_RE.match(prefix):
                raise ToolRegistrationError(f"invalid prefix: {prefix}")
            if "*" in prefix or "?" in prefix or "[" in prefix:
                raise ToolRegistrationError("wildcards are not allowed in prefix")
        if not isinstance(executor_id, str) or not executor_id.strip():
            raise ToolRegistrationError("executor_id must be a non-empty string")
        self._namespace_routes[prefix] = executor_id.strip()

    def registerNamespaceRoute(self, prefix: str, executor_id: str) -> None:  # noqa: N802
        self.register_namespace_route(prefix, executor_id)

    def resolve_namespace_route(self, tool_name: str) -> str | None:
        """
        返回匹配 tool_name 的 executor_id（最长前缀优先）。保留名必须精确命中。
        """
        if tool_name in RESERVED_NAMES:
            return self._namespace_routes.get(tool_name)
        best: tuple[int, str] | None = None
        for prefix, executor_id in self._namespace_routes.items():
            if prefix.endswith(".") and tool_name.startswith(prefix):
                cand = (len(prefix), executor_id)
                if best is None or cand[0] > best[0]:
                    best = cand
            elif "*" in prefix and fnmatchcase(tool_name, prefix):
                cand = (len(prefix), executor_id)
                if best is None or cand[0] > best[0]:
                    best = cand
        return best[1] if best else None

    def list_tools(self) -> list[ToolDefinition]:
        return [rt.definition for _, rt in sorted(self._tools.items(), key=lambda kv: kv[0])]

    def listTools(self) -> list[ToolDefinition]:  # noqa: N802
        return self.list_tools()

    def get_tool(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def getTool(self, name: str) -> RegisteredTool | None:  # noqa: N802
        return self.get_tool(name)
