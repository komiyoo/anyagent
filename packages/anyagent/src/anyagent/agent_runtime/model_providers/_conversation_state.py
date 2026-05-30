from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from openai.types.responses.response import Response


@dataclass(slots=True)
class ConversationState:
    turns: list[dict[str, Any]] = field(default_factory=list)


class ConversationStateStore:
    def __init__(self, *, max_entries: int) -> None:
        self._max_entries = max(1, int(max_entries))
        self._states: OrderedDict[str, ConversationState] = OrderedDict()
        self._idem: dict[str, Response] = {}

    def get(self, response_id: str) -> ConversationState | None:
        state = self._states.get(response_id)
        if state is not None:
            self._states.move_to_end(response_id)
        return state

    def remember(self, response_id: str, turns: list[dict[str, Any]], *, assistant_turn: dict[str, Any]) -> None:
        next_turns = list(turns)
        if assistant_turn:
            next_turns.append(assistant_turn)
        self._states[response_id] = ConversationState(turns=next_turns)
        self._states.move_to_end(response_id)
        while len(self._states) > self._max_entries:
            self._states.popitem(last=False)

    def get_idempotent(self, key: str | None) -> Response | None:
        if key:
            return self._idem.get(key)
        return None

    def remember_idempotent(self, key: str | None, response: Response) -> None:
        if key:
            self._idem[key] = response
