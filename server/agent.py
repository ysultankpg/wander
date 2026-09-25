"""The agent loop: Ollama chat + iterative tool calling, streamed.

Runs entirely against a local Ollama server. No cloud, no key, no billing.

Shape of a turn:
  1. send history + tool schemas to the model
  2. if it asks for tools, run them (concurrently), append results, loop
  3. once it answers in prose, stream those tokens to the client

MAX_ROUNDS bounds the tool loop so a confused model cannot spin forever.
"""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator

import httpx

from .prompts import system_prompt
from .tools import store
from .tools.registry import OLLAMA_TOOLS, call_tool

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("WANDER_MODEL", "llama3.1:8b")
MAX_ROUNDS = 4
NUM_CTX = 8192


async def _chat(client: httpx.AsyncClient, messages: list[dict], use_tools: bool) -> dict:
    """One non-streaming round, used while the model may still want tools."""
    payload: dict = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.3, "num_ctx": NUM_CTX},
    }
    if use_tools:
        payload["tools"] = OLLAMA_TOOLS
    resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=180.0)
    resp.raise_for_status()
    return resp.json()


def _chunks(text: str, size: int = 24) -> list[str]:
    """Slice finished text into token-sized pieces so the UI still types it out."""
    return [text[i:i + size] for i in range(0, len(text), size)]


async def _stream(client: httpx.AsyncClient, messages: list[dict]) -> AsyncIterator[str]:
    """Final answer, streamed token by token."""
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": True,
        "options": {"temperature": 0.4, "num_ctx": NUM_CTX},
    }
    async with client.stream("POST", f"{OLLAMA_URL}/api/chat",
                             json=payload, timeout=180.0) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            piece = (chunk.get("message") or {}).get("content") or ""
            if piece:
                yield piece
            if chunk.get("done"):
                return


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
                data = await _chat(client, messages, use_tools=True)
                msg = data.get("message") or {}
                calls = msg.get("tool_calls") or []

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

                messages.append({
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": calls,
                })

                names = []
                jobs = []
                for c in calls:
                    fn = c.get("function") or {}
                    name = fn.get("name") or ""
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    names.append(name)
                    jobs.append(call_tool(name, args, user_id))

                yield ("status", f"Checking {', '.join(n.replace('_', ' ') for n in names)}…")
                results = await asyncio.gather(*jobs, return_exceptions=True)

                for name, result in zip(names, results):
                    if isinstance(result, BaseException):
                        result = {"error": f"{name} raised {type(result).__name__}"}
                    yield ("tool", {"name": name, "result": result})
                    messages.append({
                        "role": "tool",
                        "content": json.dumps(result, default=str)[:4000],
                    })
            else:
                yield ("status", "Wrapping up after several lookups…")

            # Final pass: stream prose with tools withheld so it must answer.
            yield ("status", "Writing…")
            got_any = False
            async for piece in _stream(client, messages):
                got_any = True
                yield ("token", piece)
            if not got_any:
                yield ("error", "The model returned an empty response. Try rephrasing.")

        except httpx.ConnectError:
            yield ("error", "Cannot reach Ollama. Start it with: brew services start ollama")
        except httpx.HTTPStatusError as exc:
            yield ("error", f"Ollama returned HTTP {exc.response.status_code}. Is the model pulled?")
        except Exception as exc:  # noqa: BLE001
            yield ("error", f"Unexpected failure: {type(exc).__name__}")
