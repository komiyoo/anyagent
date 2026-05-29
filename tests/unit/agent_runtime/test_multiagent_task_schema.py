from __future__ import annotations

from anyagent.agent_runtime import task_tool_schema
from anyagent.protocol.multi_agent import TaskArgs


def test_task_args_require_description_prompt_and_agent_id() -> None:
    args = TaskArgs.model_validate(
        {
            "description": "Summarize repository risks",
            "prompt": "Read the TODO list and return the highest-risk items.",
            "agent_id": "reviewer",
        }
    )

    assert args.description == "Summarize repository risks"
    assert args.prompt.startswith("Read the TODO")
    assert args.agent_id == "reviewer"


def test_task_tool_schema_is_strict_function_tool() -> None:
    dumped = task_tool_schema()

    assert dumped["name"] == "task"
    assert dumped["strict"] is True
    assert dumped["parameters"]["additionalProperties"] is False
    assert set(dumped["parameters"]["required"]) == {"description", "prompt", "agent_id"}
