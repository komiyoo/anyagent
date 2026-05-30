from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ._capabilities import ProviderCapabilities


class VendorRequest(BaseModel):
    url_path: str
    headers: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class VendorToolCall(BaseModel):
    call_id: str
    name: str
    arguments_json: str


class VendorTranslation(BaseModel):
    text: str = ""
    tool_calls: list[VendorToolCall] = Field(default_factory=list)
    raw_assistant_turn: dict[str, Any] = Field(default_factory=dict)


class ToolNameMapping(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_to_source: dict[str, str] = Field(default_factory=dict)
    source_to_model: dict[str, str] = Field(default_factory=dict)
    call_id_to_model_name: dict[str, str] = Field(default_factory=dict)

    def model_name_for_source(self, source_name: str) -> str:
        return self.source_to_model.get(source_name, source_name)

    def source_name_for_model(self, model_name: str) -> str:
        return self.model_to_source.get(model_name, model_name)


class VendorTranslator(Protocol):
    capabilities: ProviderCapabilities

    def build_request(
        self,
        *,
        body: dict[str, Any],
        turns: list[dict[str, Any]],
        names: ToolNameMapping,
        settings: object,
    ) -> VendorRequest:
        raise NotImplementedError

    def parse_response(self, *, data: dict[str, Any], names: ToolNameMapping) -> VendorTranslation:
        raise NotImplementedError

    def input_to_turns(self, *, input_: object, names: ToolNameMapping) -> list[dict[str, Any]]:
        raise NotImplementedError
