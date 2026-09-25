"""LLM backend adapter: one interface, two providers.

Local development runs against Ollama — no key, no cost, no account. A hosted
deployment runs against Groq's OpenAI-compatible API — free tier, no credit card.
The provider is chosen by WANDER_BACKEND so the agent loop never has to know
which one is answering; it deals only in normalized tool calls.

Both providers accept the same OpenAI-style tool schema (registry.OLLAMA_TOOLS)
and both return tool calls under message["tool_calls"]. The two real differences
this module hides:
  * endpoint + auth (Ollama /api/chat, no auth; Groq /chat/completions, Bearer)
  * tool-call arguments arrive as a dict from Ollama, a JSON string from Groq,
    and Groq's tool results must carry the originating tool_call_id.
"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx

BACKEND = os.environ.get("WANDER_BACKEND", "ollama").lower()

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
GROQ_BASE = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")

if BACKEND == "groq":
    MODEL = os.environ.get("WANDER_MODEL", "openai/gpt-oss-20b")
else:
    MODEL = os.environ.get("WANDER_MODEL", "llama3.1:8b")

NUM_CTX = 8192
TIMEOUT = 180.0


class LLMError(RuntimeError):
    """Backend failure carrying a message safe to show the user."""


def _groq_headers() -> dict:
    return {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}


# --------------------------------------------------------------- public surface

async def complete(client: httpx.AsyncClient, messages: list[dict], tools: list) -> dict:
    """One non-streaming round. Returns a clean assistant message
    ({"role","content"[, "tool_calls"]}) that is safe to append back to history."""
    if BACKEND == "groq":
        return await _groq_complete(client, messages, tools)
    return await _ollama_complete(client, messages, tools)


async def stream(client: httpx.AsyncClient, messages: list[dict]) -> AsyncIterator[str]:
    """Final answer, streamed token by token, tools withheld."""
    if BACKEND == "groq":
        async for p in _groq_stream(client, messages):
            yield p
    else:
        async for p in _ollama_stream(client, messages):
            yield p


def extract_calls(message: dict) -> list[dict]:
    """Normalize provider tool calls to [{"id","name","args": dict}]."""
    out = []
    for c in message.get("tool_calls") or []:
        fn = c.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        out.append({"id": c.get("id"), "name": fn.get("name") or "", "args": args or {}})
    return out


def tool_result_message(call: dict, result: dict) -> dict:
    """Shape a tool result for whichever provider is active.

    Groq (OpenAI) requires tool_call_id linking the result to the call; Ollama
    ignores it. Sending it whenever we have one satisfies both."""
    msg = {"role": "tool", "content": json.dumps(result, default=str)[:4000]}
    if call.get("id"):
        msg["tool_call_id"] = call["id"]
    if call.get("name"):
        msg["name"] = call["name"]
    return msg


def unreachable_hint() -> str:
    if BACKEND == "groq":
        return "Cannot reach Groq. Check GROQ_API_KEY and network connectivity."
    return "Cannot reach Ollama. Start it with: brew services start ollama"


async def health(client: httpx.AsyncClient) -> tuple[bool, str]:
    if BACKEND == "groq":
        if not GROQ_KEY:
            return False, "GROQ_API_KEY is not set."
        try:
            r = await client.get(f"{GROQ_BASE}/models", headers=_groq_headers(), timeout=10.0)
            r.raise_for_status()
            return True, "groq ready"
        except Exception:
            return False, "Groq API unreachable or key rejected."
    try:
        r = await client.get(f"{OLLAMA_URL}/api/tags", timeout=10.0)
        names = [m.get("name", "") for m in (r.json().get("models") or [])]
        if not any(n.startswith(MODEL.split(":")[0]) for n in names):
            return False, f"model {MODEL} not pulled — run: ollama pull {MODEL}"
        return True, "ready"
    except Exception:
        return False, "ollama unreachable — run: brew services start ollama"


# --------------------------------------------------------------------- ollama

async def _ollama_complete(client, messages, tools):
    payload = {"model": MODEL, "messages": messages, "stream": False,
               "options": {"temperature": 0.3, "num_ctx": NUM_CTX}}
    if tools:
        payload["tools"] = tools
    resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    return _clean(resp.json().get("message") or {})


async def _ollama_stream(client, messages):
    payload = {"model": MODEL, "messages": messages, "stream": True,
               "options": {"temperature": 0.4, "num_ctx": NUM_CTX}}
    async with client.stream("POST", f"{OLLAMA_URL}/api/chat",
                             json=payload, timeout=TIMEOUT) as resp:
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


# ----------------------------------------------------------------------- groq

async def _groq_complete(client, messages, tools):
    if not GROQ_KEY:
        raise LLMError("GROQ_API_KEY is not set.")
    payload = {"model": MODEL, "messages": messages, "stream": False, "temperature": 0.3}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    resp = await client.post(f"{GROQ_BASE}/chat/completions", json=payload,
                             headers=_groq_headers(), timeout=TIMEOUT)
    resp.raise_for_status()
    choice = (resp.json().get("choices") or [{}])[0]
    return _clean(choice.get("message") or {})


async def _groq_stream(client, messages):
    if not GROQ_KEY:
        raise LLMError("GROQ_API_KEY is not set.")
    payload = {"model": MODEL, "messages": messages, "stream": True, "temperature": 0.4}
    async with client.stream("POST", f"{GROQ_BASE}/chat/completions", json=payload,
                             headers=_groq_headers(), timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            delta = ((chunk.get("choices") or [{}])[0]).get("delta") or {}
            piece = delta.get("content") or ""
            if piece:
                yield piece


def _clean(message: dict) -> dict:
    """Rebuild a minimal assistant message safe to re-submit to either API."""
    out = {"role": "assistant", "content": message.get("content") or ""}
    if message.get("tool_calls"):
        out["tool_calls"] = message["tool_calls"]
    return out
