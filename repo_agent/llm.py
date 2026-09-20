"""Model access. LiteLLM keeps providers interchangeable; ScriptedLLM keeps tests offline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Protocol, Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


@dataclass(slots=True)
class Usage:
    tokens: int = 0
    cost_usd: float = 0.0


class ChatClient(Protocol):
    def complete(
        self, messages: Sequence[BaseMessage], tools: list[dict[str, Any]] | None = None
    ) -> tuple[AIMessage, Usage]: ...


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return "" if content is None else str(content)


def to_openai_messages(messages: Sequence[BaseMessage]) -> list[dict[str, Any]]:
    """LangChain messages -> the wire format every provider understands."""
    payload: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, ToolMessage):
            payload.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": _text(message.content),
                }
            )
            continue
        if isinstance(message, AIMessage):
            entry: dict[str, Any] = {"role": "assistant", "content": _text(message.content)}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["args"], ensure_ascii=False),
                        },
                    }
                    for call in message.tool_calls
                ]
            payload.append(entry)
            continue
        role = {"system": "system", "human": "user", "ai": "assistant"}.get(message.type, "user")
        payload.append({"role": role, "content": _text(message.content)})
    return payload


def _cost(response: Any) -> float:
    try:
        import litellm

        return float(litellm.completion_cost(completion_response=response) or 0.0)
    except Exception:
        return 0.0


class LiteLLMClient:
    """One thin wrapper over LiteLLM so swapping models is a string change."""

    def __init__(
        self,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4_096,
        timeout: float = 300.0,
        api_base: str | None = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.api_base = api_base

    def complete(
        self, messages: Sequence[BaseMessage], tools: list[dict[str, Any]] | None = None
    ) -> tuple[AIMessage, Usage]:
        import litellm  # lazy import: offline runs never pay for it

        response = litellm.completion(
            model=self.model,
            messages=to_openai_messages(messages),
            tools=tools or None,
            tool_choice="auto" if tools else None,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            api_base=self.api_base,
            drop_params=True,
        )
        choice = response.choices[0].message
        calls: list[dict[str, Any]] = []
        for index, call in enumerate(getattr(choice, "tool_calls", None) or []):
            raw = call.function.arguments or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = {"_raw": raw}
            calls.append(
                {"name": call.function.name, "args": args, "id": call.id or f"call_{index}"}
            )
        message = AIMessage(content=choice.content or "", tool_calls=calls)
        usage = Usage(
            tokens=int(getattr(response.usage, "total_tokens", 0) or 0), cost_usd=_cost(response)
        )
        return message, usage


class ScriptedLLM:
    """Deterministic replay of a fixed trajectory, for tests and offline smoke runs."""

    def __init__(
        self, script: Sequence[AIMessage | Callable[[Sequence[BaseMessage]], AIMessage]]
    ) -> None:
        self.script = list(script)
        self.calls = 0

    def complete(
        self, messages: Sequence[BaseMessage], tools: list[dict[str, Any]] | None = None
    ) -> tuple[AIMessage, Usage]:
        if self.calls >= len(self.script):
            return AIMessage(content="script exhausted"), Usage()
        step = self.script[self.calls]
        self.calls += 1
        message = step(messages) if callable(step) else step
        chars = sum(len(_text(m.content)) for m in messages)
        return message, Usage(tokens=chars // 4)
