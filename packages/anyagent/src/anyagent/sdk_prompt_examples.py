from __future__ import annotations

import hashlib
import json
from typing import Any

from anyagent.protocol.context_fragments import ContextFragment
from anyagent.protocol.openai_responses import build_minimal_openai_response_json
from anyagent.protocol.prompt_context import PromptEnvelope
from anyagent.protocol.stage_events import summarize_command, summarize_payload
from anyagent.types import (
    AnyAgentCommandPlannedEvent,
    AnyAgentCommandResultEvent,
    AnyAgentDoneEvent,
    AnyAgentFunctionToolParam,
    AnyAgentModelStreamEvent,
    AnyAgentPromptContextEvent,
    AnyAgentToolPlannedEvent,
    AnyAgentToolResultEvent,
    InternalPromptBundlePreviewResponse,
    PolicyHint,
    PromptRunBundleExplanation,
    PromptRunBundleExplanationStep,
    PromptRunBundleExampleOptions,
    PromptRunBundleExampleResponse,
    PromptRunBundleScenario,
    PromptRunBundleScenarioDescriptor,
    PromptRunBundleToolLoopItem,
    RequesterContext,
    StageEvent,
    ToolContext,
    TraceContext,
)


def _validate_request(model_type, data):
    if isinstance(data, model_type):
        return data
    return model_type.model_validate(data)


def build_example_run_bundle(
    *,
    agent_id: str,
    session_key: str,
    model: str,
    scenario: PromptRunBundleScenario,
    options: PromptRunBundleExampleOptions,
) -> PromptRunBundleExampleResponse:
    """
    组装一个纯本地的 run bundle 示例。

    这条链路故意不依赖真实运行时：
    - 不访问 server
    - 不访问 event store
    - 不访问真实 MCP / tool runtime
    """

    response_id = f"resp_example_{agent_id}_{scenario}"
    scenario_spec = _build_example_scenario_spec(scenario=scenario, model=model, session_key=session_key)
    _apply_example_options(scenario_spec=scenario_spec, options=options)
    request_body = scenario_spec["request_body"]
    tool_call_id = scenario_spec["tool_call_id"]

    tool_context = ToolContext(
        trace=TraceContext(trace_id="trace-example-run-bundle"),
        requester=RequesterContext(id="user_demo", display_name="Demo User", is_owner=True),
        policy=PolicyHint(allow_tools=list(scenario_spec["requested_tool_names"]), deny_tools=["admin.*"]),
    )
    selected_skill_ids = [
        _example_skill_stable_id(slug=str(item["slug"]))
        for item in scenario_spec["skills"]
    ]
    prompt_envelope = PromptEnvelope(
        prompt_cache_key=_example_prompt_cache_key(
            agent_id=agent_id,
            model=model,
            scenario_spec=scenario_spec,
            selected_skill_ids=selected_skill_ids,
        ),
        fragments=tuple(
            _build_example_context_fragments(
                agent_id=agent_id,
                scenario_spec=scenario_spec,
                selected_skill_ids=selected_skill_ids,
            )
        ),
    )

    manifest_tools = [AnyAgentFunctionToolParam.model_validate(item) for item in scenario_spec["manifest_tools"]]

    effective_body = dict(request_body)
    applied_body = prompt_envelope.apply_to_body(body=effective_body)
    prompt_bundle = InternalPromptBundlePreviewResponse(
        agent_id=agent_id,
        session_key=session_key,
        model=model,
        prompt_cache_key=prompt_envelope.prompt_cache_key,
        instruction_role="developer",
        selected_skill_ids=selected_skill_ids,
        manifest_tools=manifest_tools,
        manifest_tool_names=[tool.name for tool in manifest_tools],
        mcp_servers=list(scenario_spec["mcp_servers"].keys()),
        tool_context=tool_context.model_dump(exclude_none=True),
        prompt_context=prompt_envelope.audit_metadata(),
        rendered_fragments=prompt_envelope.rendered_fragments(),
        effective_body=effective_body,
        applied_body=applied_body,
    )

    model_function_call = dict(scenario_spec["model_function_call"])
    tool_output_item = dict(scenario_spec["tool_output_item"])
    assistant_message = dict(scenario_spec["assistant_message"])
    tool_loop_items = [
        PromptRunBundleToolLoopItem(phase="model_function_call", item=model_function_call),
        PromptRunBundleToolLoopItem(phase="tool_output_to_model", item=tool_output_item),
        PromptRunBundleToolLoopItem(phase="assistant_message", item=assistant_message),
    ]

    model_response = build_minimal_openai_response_json(
        response_id=response_id,
        status="completed",
        model=model,
        tools=[tool.model_dump(exclude_none=True, by_alias=True) for tool in manifest_tools],
        tool_choice="auto",
        output=[assistant_message],
    )

    stage_events: list[StageEvent] = [
        AnyAgentPromptContextEvent.model_validate(
            {
                "type": "anyagent.prompt.context",
                "response_id": response_id,
                "trace_id": "trace-example-run-bundle",
                "seq": 1,
                "ts_ms": 1_730_000_000_001,
                **prompt_envelope.audit_metadata().model_dump(exclude_none=True),
            }
        ),
        AnyAgentToolPlannedEvent(
            response_id=response_id,
            trace_id="trace-example-run-bundle",
            seq=2,
            ts_ms=1_730_000_000_002,
            tool_call_id=tool_call_id,
            tool_name=str(model_function_call["name"]),
            arguments=summarize_payload(model_function_call.get("arguments")),
        ),
        AnyAgentCommandPlannedEvent(
            response_id=response_id,
            trace_id="trace-example-run-bundle",
            seq=3,
            ts_ms=1_730_000_000_003,
            command=summarize_command(str(scenario_spec["command_preview"])),
            workdir=scenario_spec.get("command_workdir"),
            timeout_ms=60000,
            source_tool_call_id=tool_call_id,
            source_tool_name=str(model_function_call["name"]),
        ),
        AnyAgentCommandResultEvent(
            response_id=response_id,
            trace_id="trace-example-run-bundle",
            seq=4,
            ts_ms=1_730_000_000_004,
            exit_code=int(scenario_spec["command_exit_code"]),
            stdout=summarize_payload(str(scenario_spec["command_stdout"])),
            stderr=summarize_payload(str(scenario_spec["command_stderr"])),
            duration_ms=int(scenario_spec["command_duration_ms"]),
            source_tool_call_id=tool_call_id,
            source_tool_name=str(model_function_call["name"]),
        ),
        AnyAgentToolResultEvent(
            response_id=response_id,
            trace_id="trace-example-run-bundle",
            seq=5,
            ts_ms=1_730_000_000_005,
            tool_call_id=tool_call_id,
            tool_name=str(model_function_call["name"]),
            status="completed",
            meta={"duration_ms": 240, "output_truncated": False, "audit_ref": "aud_example_exec"},
            output=summarize_payload(tool_output_item["output"]),
        ),
        AnyAgentModelStreamEvent(
            response_id=response_id,
            trace_id="trace-example-run-bundle",
            seq=6,
            ts_ms=1_730_000_000_006,
            sse_event="response.completed",
            payload={"type": "response.completed", "response": model_response},
        ),
        AnyAgentDoneEvent(
            response_id=response_id,
            trace_id="trace-example-run-bundle",
            seq=7,
            ts_ms=1_730_000_000_007,
        ),
    ]

    return PromptRunBundleExampleResponse(
        agent_id=agent_id,
        session_key=session_key,
        response_id=response_id,
        model=model,
        scenario=scenario,
        scenario_label=str(scenario_spec["scenario_label"]),
        options=options,
        prompt_bundle=prompt_bundle,
        tool_loop_items=tool_loop_items,
        stage_events=stage_events,
        model_response=model_response,
        explanation=_build_example_run_bundle_explanation(
            scenario=scenario,
            scenario_label=str(scenario_spec["scenario_label"]),
            manifest_tool_names=[tool.name for tool in manifest_tools],
            selected_skill_ids=selected_skill_ids,
        ),
    )


def _build_example_context_fragments(
    *,
    agent_id: str,
    scenario_spec: dict[str, Any],
    selected_skill_ids: list[str],
) -> list[ContextFragment]:
    fragments = [
        ContextFragment(
            kind="agents_instructions",
            role="developer",
            cache_class="stable_prefix",
            label="workspace",
            stable_id="agents://workspace",
            source_path="/example-workspace/AGENTS.md",
            source_hash="example-workspace-sha256",
            scope="workspace",
            body="这是 workspace 级协作规范。",
        ),
        ContextFragment(
            kind="agents_instructions",
            role="developer",
            cache_class="stable_prefix",
            label=f"agent:{agent_id}",
            stable_id=f"agents://{agent_id}",
            source_path=f"/example-workspace/.anyagent/agents/{agent_id}/AGENTS.md",
            source_hash="example-agent-sha256",
            scope="agent-pack",
            body="你是一个 coding agent，优先解释上下文，再在沙箱里执行命令。",
            metadata={"agent_id": agent_id},
        ),
    ]
    for label, raw_config in sorted(dict(scenario_spec["mcp_servers"]).items()):
        transport = "stdio" if raw_config.get("command") else "streamable_http"
        lines = [
            "<mcp_server_ref>",
            f"<label>{label}</label>",
            f"<transport>{transport}</transport>",
        ]
        if raw_config.get("url"):
            lines.append(f"<url>{raw_config['url']}</url>")
        if raw_config.get("command"):
            lines.append(f"<command>{raw_config['command']}</command>")
        lines.append("</mcp_server_ref>")
        fragments.append(
            ContextFragment(
                kind="mcp_server_ref",
                role="developer",
                cache_class="stable_prefix",
                label=str(label),
                stable_id=f"mcp://{label}",
                scope="agent-pack",
                body="\n".join(lines),
                metadata={"label": str(label), "transport": transport},
            )
        )
    if scenario_spec["sandbox_mode"] != "disabled" and "exec" in scenario_spec["requested_tool_names"]:
        fragments.append(
            ContextFragment(
                kind="sandbox_guidance",
                role="developer",
                cache_class="stable_prefix",
                label="sandbox",
                stable_id=f"sandbox://{agent_id}",
                scope="agent-pack",
                body="\n".join(
                    [
                        "<sandbox_guidance>",
                        f"<mode>{scenario_spec['sandbox_mode']}</mode>",
                        "<workspace_root>/workspace</workspace_root>",
                        f"<persistence_mode>{scenario_spec['persistence_mode']}</persistence_mode>",
                        "<exec_tool>exec</exec_tool>",
                        "Use the exec tool to run shell commands inside the sandbox.",
                        "Write files under /workspace when you want the session workspace to retain them.",
                        "The sandbox does not expose host credentials, private internal services, or raw secret values.",
                        "</sandbox_guidance>",
                    ]
                ),
                metadata={
                    "mode": str(scenario_spec["sandbox_mode"]),
                    "workspace_root": "/workspace",
                    "persistence_mode": str(scenario_spec["persistence_mode"]),
                    "tool": "exec",
                },
            )
        )
    for item, stable_id in zip(scenario_spec["skills"], selected_skill_ids, strict=False):
        requested_tools = ",".join(str(name) for name in scenario_spec["requested_tool_names"])
        metadata = {"name": str(item["name"])}
        if requested_tools:
            metadata["requested_tools"] = requested_tools
        fragments.append(
            ContextFragment(
                kind="skill",
                role="developer",
                cache_class="contextual",
                stable_id=stable_id,
                source_path=f"/example-workspace/.anyagent/skills/{item['slug']}/SKILL.md",
                source_hash=_sha256_text(str(item["body_markdown"])),
                scope=str(item["scope"]),
                body=str(item["body_markdown"]).rstrip(),
                metadata=metadata,
            )
        )
    fragments.append(
        ContextFragment(
            kind="environment_context",
            role="developer",
            cache_class="contextual",
            stable_id="environment://runtime",
            body="\n".join(
                [
                    "<environment_context>",
                    "<cwd>/example-workspace</cwd>",
                    f"<sandbox_mode>{scenario_spec['sandbox_mode']}</sandbox_mode>",
                    "</environment_context>",
                ]
            ),
        )
    )
    return fragments


def _example_skill_stable_id(*, slug: str) -> str:
    return f"/example-workspace/.anyagent/skills/{slug}/SKILL.md"


def _example_prompt_cache_key(
    *,
    agent_id: str,
    model: str,
    scenario_spec: dict[str, Any],
    selected_skill_ids: list[str],
) -> str:
    payload = {
        "protocol_version": "v0",
        "agent_id": agent_id,
        "model": model,
        "agents_md_sha256": "example-agent-sha256",
        "workspace_agents_md_sha256": "example-workspace-sha256",
        "sandbox_mode": scenario_spec["sandbox_mode"],
        "persistence_mode": scenario_spec["persistence_mode"],
        "requested_tool_names": list(scenario_spec["requested_tool_names"]),
        "selected_skill_ids": selected_skill_ids,
        "mcp_servers": sorted(str(label) for label in dict(scenario_spec["mcp_servers"])),
    }
    dumped = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _build_example_scenario_spec(
    *,
    scenario: PromptRunBundleScenario,
    model: str,
    session_key: str,
) -> dict[str, Any]:
    common_manifest_exec = {
        "type": "function",
        "name": "exec",
        "description": "Execute a shell command in the sandbox environment.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["cmd"],
            "properties": {
                "cmd": {"type": "string"},
                "workdir": {"type": "string"},
                "timeout": {"type": "integer"},
            },
        },
        "x-anyagent-kind": "command",
    }
    if scenario == "multi_skill_research":
        return {
            "scenario_label": "Multi Skill Research",
            "request_body": {
                "model": model,
                "input": "请先抓取两篇资料，再总结成一份研究提纲。",
                "stream": False,
                "metadata": {"session_key": session_key},
            },
            "tool_call_id": "call_exec_research",
            "requested_tool_names": ["exec", "core.web_fetch"],
            "sandbox_mode": "local-unsafe",
            "persistence_mode": "session_hot_cold",
            "mcp_servers": {
                "github": {"url": "https://mcp.example.test"},
                "docs": {"url": "https://docs.example.test"},
            },
            "skills": [
                {
                    "slug": "repo-helper",
                    "scope": "repo",
                    "name": "repo-helper",
                    "description": "帮助分析仓库与生成修复计划",
                    "body_markdown": "Read the repository, summarize the task, then run targeted commands.\n",
                    "agent_metadata": {"interface": {"default_prompt": "Inspect the repo first."}},
                },
                {
                    "slug": "research-notes",
                    "scope": "repo",
                    "name": "research-notes",
                    "description": "帮助整理研究材料与提纲",
                    "body_markdown": "Gather multiple sources, compare them, and produce a concise outline.\n",
                    "agent_metadata": {"interface": {"default_prompt": "Compare sources before concluding."}},
                },
            ],
            "manifest_tools": [
                common_manifest_exec,
                {
                    "type": "function",
                    "name": "core.web_fetch",
                    "description": "Fetch a URL and return text content.",
                    "parameters": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["url"],
                        "properties": {"url": {"type": "string"}},
                    },
                },
            ],
            "model_function_call": {
                "type": "function_call",
                "call_id": "call_exec_research",
                "name": "exec",
                "arguments": '{"cmd":"python build_outline.py","workdir":"/workspace/research"}',
            },
            "tool_output_item": {
                "type": "function_call_output",
                "call_id": "call_exec_research",
                "output": '{"exit_code":0,"stdout":"outline saved to /workspace/research/outline.md","stderr":""}',
            },
            "assistant_message": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "我已经整理出研究提纲，并保存到 /workspace/research/outline.md。"}],
            },
            "command_preview": "python build_outline.py",
            "command_workdir": "/workspace/research",
            "command_exit_code": 0,
            "command_stdout": "outline saved to /workspace/research/outline.md",
            "command_stderr": "",
            "command_duration_ms": 480,
        }
    if scenario == "toolset_retry":
        return {
            "scenario_label": "Toolset Refresh Retry",
            "request_body": {
                "model": model,
                "input": "请在工具版本变更后重试并完成写文件。",
                "stream": False,
                "metadata": {"session_key": session_key},
            },
            "tool_call_id": "call_exec_retry",
            "requested_tool_names": ["exec"],
            "sandbox_mode": "local-unsafe",
            "persistence_mode": "session_hot_cold",
            "mcp_servers": {},
            "skills": [
                {
                    "slug": "retry-aware",
                    "scope": "repo",
                    "name": "retry-aware",
                    "description": "帮助在 manifest 变化后做单次安全重试",
                    "body_markdown": "If tool metadata changes, refresh manifest once before retrying.\n",
                    "agent_metadata": {"interface": {"default_prompt": "Retry once after manifest refresh."}},
                }
            ],
            "manifest_tools": [common_manifest_exec],
            "model_function_call": {
                "type": "function_call",
                "call_id": "call_exec_retry",
                "name": "exec",
                "arguments": '{"cmd":"python write_retry_file.py","workdir":"/workspace/retry"}',
            },
            "tool_output_item": {
                "type": "function_call_output",
                "call_id": "call_exec_retry",
                "output": '{"exit_code":0,"stdout":"retried after manifest refresh and wrote /workspace/retry/output.txt","stderr":""}',
            },
            "assistant_message": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "我已经在刷新工具清单后重试成功，并写入 /workspace/retry/output.txt。"}],
            },
            "command_preview": "python write_retry_file.py",
            "command_workdir": "/workspace/retry",
            "command_exit_code": 0,
            "command_stdout": "retried after manifest refresh and wrote /workspace/retry/output.txt",
            "command_stderr": "",
            "command_duration_ms": 310,
        }
    return {
        "scenario_label": "Sandbox File Write",
        "request_body": {
            "model": model,
            "input": "请抓取网页摘要，并在沙箱里生成一份总结文件。",
            "stream": False,
            "metadata": {"session_key": session_key},
        },
        "tool_call_id": "call_exec_example",
        "requested_tool_names": ["exec", "core.web_fetch"],
        "sandbox_mode": "local-unsafe",
        "persistence_mode": "session_hot_cold",
        "mcp_servers": {"github": {"url": "https://mcp.example.test"}},
        "skills": [
            {
                "slug": "repo-helper",
                "scope": "repo",
                "name": "repo-helper",
                "description": "帮助分析仓库与生成修复计划",
                "body_markdown": "Read the repository, summarize the task, then run targeted commands.\n",
                "agent_metadata": {
                    "interface": {"default_prompt": "Inspect the repo first."},
                    "dependencies.tools": [{"transport": "builtin", "value": "exec"}],
                },
            }
        ],
        "manifest_tools": [
            common_manifest_exec,
            {
                "type": "function",
                "name": "core.web_fetch",
                "description": "Fetch a URL and return text content.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["url"],
                    "properties": {"url": {"type": "string"}},
                },
            },
        ],
        "model_function_call": {
            "type": "function_call",
            "call_id": "call_exec_example",
            "name": "exec",
            "arguments": '{"cmd":"python summarize.py","workdir":"/workspace/repo"}',
        },
        "tool_output_item": {
            "type": "function_call_output",
            "call_id": "call_exec_example",
            "output": '{"exit_code":0,"stdout":"summary saved to /workspace/repo/summary.txt","stderr":""}',
        },
        "assistant_message": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "我已经把总结写入 /workspace/repo/summary.txt。"}],
        },
        "command_preview": "python summarize.py",
        "command_workdir": "/workspace/repo",
        "command_exit_code": 0,
        "command_stdout": "summary saved to /workspace/repo/summary.txt",
        "command_stderr": "",
        "command_duration_ms": 240,
    }


def _build_example_run_bundle_explanation(
    *,
    scenario: PromptRunBundleScenario,
    scenario_label: str,
    manifest_tool_names: list[str],
    selected_skill_ids: list[str],
) -> PromptRunBundleExplanation:
    scenario_summary = {
        "sandbox_file_write": "展示一个典型的 coding agent 如何在沙箱里写文件，并把上下文、工具和最终回复串成完整链路。",
        "multi_skill_research": "展示多个 skill 和多个 MCP 引用如何共同影响 prompt bundle 与 tool loop。",
        "toolset_retry": "展示工具清单刷新后重试的 explain 视角，帮助说明 manifest/tool loop 的关系。",
    }[scenario]
    why = {
        "sandbox_file_write": "这个场景适合解释 sandbox guidance、workspace 持久化和 exec 命令派生事件。",
        "multi_skill_research": "这个场景适合解释为什么 PromptEnvelope 里会同时出现多个 skill 与 MCP catalog 片段。",
        "toolset_retry": "这个场景适合解释 manifest 和 tool loop 并不是静态不变的，重试也需要被解释出来。",
    }[scenario]
    steps = [
        PromptRunBundleExplanationStep(
            title="1. 先组装 prompt bundle",
            detail=f"示例先构造 {scenario_label} 场景下的 PromptEnvelope，把 AGENTS、skills、MCP、sandbox guidance 和 environment context 渲染成模型可见片段。",
            cites=["prompt_bundle.rendered_fragments", "prompt_bundle.prompt_context"],
        ),
        PromptRunBundleExplanationStep(
            title="2. 再展示 manifest 可见工具",
            detail=f"示例不会真的去请求 Tool Runtime，而是内部构造 manifest tools：{', '.join(manifest_tool_names)}。",
            cites=["prompt_bundle.manifest_tools", "prompt_bundle.manifest_tool_names"],
        ),
        PromptRunBundleExplanationStep(
            title="3. 最后拼出 tool loop 与模型回复",
            detail="示例继续构造 function_call、function_call_output、assistant message 和 stage events，形成一条完整但纯本地的运行轨迹。",
            cites=["tool_loop_items", "stage_events", "model_response"],
        ),
    ]
    return PromptRunBundleExplanation(
        summary=scenario_summary,
        why_this_shape=why,
        key_takeaways=[
            "这是一份纯本地示例，不依赖真实运行时。",
            f"当前示例选中的 skill 数量为 {len(selected_skill_ids)}。",
            "UI 或 onboarding 页面可以直接消费 explanation 和 stage_events 做演示。",
        ],
        steps=steps,
    )


def coerce_example_options(options: PromptRunBundleExampleOptions | dict[str, Any] | None) -> PromptRunBundleExampleOptions:
    if isinstance(options, dict):
        return _validate_request(PromptRunBundleExampleOptions, options)
    if isinstance(options, PromptRunBundleExampleOptions):
        return _validate_request(PromptRunBundleExampleOptions, options)
    return PromptRunBundleExampleOptions()


def _apply_example_options(
    *,
    scenario_spec: dict[str, Any],
    options: PromptRunBundleExampleOptions,
) -> None:
    # 这些覆写只作用于本地 explain 示例，不影响任何真实运行时状态。
    if options.user_input:
        scenario_spec["request_body"] = dict(scenario_spec["request_body"])
        scenario_spec["request_body"]["input"] = options.user_input

    if options.skill_count is not None:
        scenario_spec["skills"] = list(scenario_spec["skills"])[: int(options.skill_count)]

    if options.include_mcp is False:
        scenario_spec["mcp_servers"] = {}

    if options.sandbox_mode is not None:
        scenario_spec["sandbox_mode"] = options.sandbox_mode
        if options.sandbox_mode == "disabled":
            # 关闭 sandbox 时，示例也同步切换到非 exec 的工具形态，
            # 这样返回的数据和真实 PromptEnvelope 语义保持一致。
            requested = [name for name in list(scenario_spec["requested_tool_names"]) if name != "exec"]
            if "core.web_fetch" not in requested:
                requested.append("core.web_fetch")
            scenario_spec["requested_tool_names"] = requested
            scenario_spec["manifest_tools"] = [
                item for item in list(scenario_spec["manifest_tools"]) if item.get("name") != "exec"
            ]
            if not scenario_spec["manifest_tools"]:
                scenario_spec["manifest_tools"] = [
                    {
                        "type": "function",
                        "name": "core.web_fetch",
                        "description": "Fetch a URL and return text content.",
                        "parameters": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["url"],
                            "properties": {"url": {"type": "string"}},
                        },
                    }
                ]
            scenario_spec["model_function_call"] = {
                "type": "function_call",
                "call_id": "call_web_fetch_example",
                "name": "core.web_fetch",
                "arguments": '{"url":"https://example.com"}',
            }
            scenario_spec["tool_output_item"] = {
                "type": "function_call_output",
                "call_id": "call_web_fetch_example",
                "output": '{"status":200,"text":"example page summary","url":"https://example.com"}',
            }
            scenario_spec["assistant_message"] = {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "我已经基于抓取到的网页内容给出摘要。"}],
            }
            scenario_spec["tool_call_id"] = "call_web_fetch_example"
            scenario_spec["command_preview"] = "core.web_fetch https://example.com"
            scenario_spec["command_workdir"] = None
            scenario_spec["command_stdout"] = "example page summary"
            scenario_spec["command_stderr"] = ""
            scenario_spec["command_exit_code"] = 0
            scenario_spec["command_duration_ms"] = 120


EXAMPLE_SCENARIO_CATALOG: tuple[PromptRunBundleScenarioDescriptor, ...] = (
    PromptRunBundleScenarioDescriptor(
        scenario="sandbox_file_write",
        label="Sandbox File Write",
        summary="演示典型 coding agent 如何在沙箱中写文件，并串起 prompt bundle、tool loop 与最终回复。",
        default_options=PromptRunBundleExampleOptions(
            skill_count=1,
            include_mcp=True,
            sandbox_mode="local-unsafe",
        ),
    ),
    PromptRunBundleScenarioDescriptor(
        scenario="multi_skill_research",
        label="Multi Skill Research",
        summary="演示多个 skills 与多个 MCP catalog 如何一起影响 PromptEnvelope 和后续 tool loop。",
        default_options=PromptRunBundleExampleOptions(
            skill_count=2,
            include_mcp=True,
            sandbox_mode="local-unsafe",
        ),
    ),
    PromptRunBundleScenarioDescriptor(
        scenario="toolset_retry",
        label="Toolset Refresh Retry",
        summary="演示 manifest/toolset 发生变化后，如何从 explain 视角理解一次重试链路。",
        default_options=PromptRunBundleExampleOptions(
            skill_count=1,
            include_mcp=False,
            sandbox_mode="local-unsafe",
        ),
    ),
)
