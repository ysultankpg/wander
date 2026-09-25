"""The agent loop: chat + iterative tool calling, streamed.

The LLM backend is pluggable (see llm.py): local Ollama for development, hosted
Groq for deployment. This module deals only in normalized tool calls and never
knows which provider answered.

Shape of a turn:
  1. send history + tool schemas to the model
  2. if it asks for tools, run them (concurrently), append results, loop
  3. once it answers in prose, stream those tokens to the client

MAX_ROUNDS bounds the tool loop so a confused model cannot spin forever.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx

from . import llm
from .prompts import system_prompt
from .tools import store
from .tools.registry import OLLAMA_TOOLS, call_tool

MODEL = llm.MODEL
BACKEND = llm.BACKEND
MAX_ROUNDS = 4


def _chunks(text: str, size: int = 24) -> list[str]:
    """Slice finished text into token-sized pieces so the UI still types it out."""
    return [text[i:i + size] for i in range(0, len(text), size)]


async def run_turn(user_id: str, history: list[dict], message: str) -> AsyncIterator[tuple[str, object]]:
    """Drive one user turn, yielding ("status"|"token"|"tool"|"error", payload)."""
    messages: list[dict] = [
        {"role": "system", "content": system_prompt(store.memory_context(user_id))}
    ]
    messages.extend(history[-12:])  # bounded context window
    messages.append({"role": "user", "content": message})

    async with httpx.AsyncClient() as client:
        try:
            for _round in range(MAX_ROUNDS):
                msg = await llm.complete(client, messages, OLLAMA_TOOLS)
                calls = llm.extract_calls(msg)

                if not calls:
                    # The model already wrote its answer. Hand that text over as
                    # tokens — asking it to speak again would leave it with
                    # nothing to add and return an empty stream.
                    content = (msg.get("content") or "").strip()
                    if content:
                        for piece in _chunks(content):
                            yield ("token", piece)
                        return
                    break

                messages.append(msg)  # assistant turn carrying the tool_calls

                names = [c["name"] for c in calls]
                yield ("status", f"Checking {', '.join(n.replace('_', ' ') for n in names)}…")
                jobs = [call_tool(c["name"], c["args"], user_id) for c in calls]
                results = await asyncio.gather(*jobs, return_exceptions=True)

                for call, result in zip(calls, results):
                    if isinstance(result, BaseException):
                        result = {"error": f"{call['name']} raised {type(result).__name__}"}
                    yield ("tool", {"name": call["name"], "result": result})
                    messages.append(llm.tool_result_message(call, result))
            else:
                yield ("status", "Wrapping up after several lookups…")

            # Final pass: stream prose with tools withheld so it must answer.
            yield ("status", "Writing…")
            got_any = False
            async for piece in llm.stream(client, messages):
                got_any = True
                yield ("token", piece)
            if not got_any:
                yield ("error", "The model returned an empty response. Try rephrasing.")

        except llm.LLMError as exc:
            yield ("error", str(exc))
        except httpx.ConnectError:
            yield ("error", llm.unreachable_hint())
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 429:
                yield ("error", "The model backend is rate-limited right now. Wait a few seconds and retry.")
            elif code in (401, 403):
                yield ("error", "The model backend rejected the request — check the API key/credentials.")
            else:
                yield ("error", f"Model backend returned HTTP {code}.")
        except Exception as exc:  # noqa: BLE001
            yield ("error", f"Unexpected failure: {type(exc).__name__}")
