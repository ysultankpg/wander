"""FastAPI app: serves the chat UI at / and streams agent turns over SSE.

Carries forward the fixes from the previous review:
  * per-browser signed identity cookie (not one shared "web-user" for everyone)
  * bounded conversation store instead of an unbounded dict that leaks memory
  * errors return a real status code with a generic message, never HTTP 200 with
    a raw exception string
  * no wildcard CORS with credentials
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import uuid
from collections import OrderedDict
from pathlib import Path

from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeSerializer

from .agent import MODEL, OLLAMA_URL, run_turn
from .tools import http as tool_http
from .tools import store
from .tools.seed import seed

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("wander")

SECRET = os.environ.get("WANDER_SECRET") or secrets.token_urlsafe(32)
signer = URLSafeSerializer(SECRET, salt="wander-identity")
COOKIE = "wander_uid"
MAX_MESSAGE = 4000
MAX_CONVERSATIONS = 500

app = FastAPI(title="Wander", description="Local-first travel agent")


class LRU(OrderedDict):
    """Bounded history store — the old proxy grew without limit."""

    def __init__(self, cap: int) -> None:
        super().__init__()
        self.cap = cap

    def touch(self, key: str, value: list) -> None:
        self[key] = value
        self.move_to_end(key)
        while len(self) > self.cap:
            self.popitem(last=False)


conversations: LRU = LRU(MAX_CONVERSATIONS)


def identity(raw: str | None) -> tuple[str, bool]:
    """Return (user_id, is_new). Signed so it cannot be forged client-side."""
    if raw:
        try:
            return str(signer.loads(raw)), False
        except BadSignature:
            logger.warning("Discarding a cookie with a bad signature.")
    return f"u-{uuid.uuid4().hex[:12]}", True


@app.on_event("startup")
async def _startup() -> None:
    count = seed()
    logger.info("Catalog ready with %d destinations; model=%s", count, MODEL)


@app.on_event("shutdown")
async def _shutdown() -> None:
    await tool_http.aclose()
    conversations.clear()


@app.exception_handler(Exception)
async def _errors(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": "Something broke server-side."})


@app.get("/api/health")
async def health():
    ok, detail = True, "ready"
    try:
        r = await tool_http.client().get(f"{OLLAMA_URL}/api/tags")
        names = [m.get("name", "") for m in (r.json().get("models") or [])]
        if not any(n.startswith(MODEL.split(":")[0]) for n in names):
            ok, detail = False, f"model {MODEL} not pulled — run: ollama pull {MODEL}"
    except Exception:
        ok, detail = False, "ollama unreachable — run: brew services start ollama"
    return {"ok": ok, "detail": detail, "model": MODEL,
            "destinations": store.search_destinations(limit=20)["count"]}


@app.post("/api/chat")
async def chat(request: Request, response: Response, wander_uid: str | None = Cookie(default=None)):
    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "Message cannot be empty.")
    if len(message) > MAX_MESSAGE:
        raise HTTPException(400, f"Message exceeds {MAX_MESSAGE} characters.")

    user_id, is_new = identity(wander_uid)
    history = list(conversations.get(user_id, []))

    async def events():
        if is_new:
            yield f"data: {json.dumps({'type': 'identity', 'new': True})}\n\n"
        answer: list[str] = []
        try:
            async for kind, payload in run_turn(user_id, history, message):
                if kind == "token":
                    answer.append(str(payload))
                yield f"data: {json.dumps({'type': kind, 'data': payload}, default=str)}\n\n"
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            logger.info("Client disconnected mid-turn.")
            raise
        finally:
            if answer:
                history.append({"role": "user", "content": message})
                history.append({"role": "assistant", "content": "".join(answer)})
                conversations.touch(user_id, history[-12:])
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    resp = StreamingResponse(events(), media_type="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    if is_new:
        resp.set_cookie(COOKIE, signer.dumps(user_id), httponly=True,
                        samesite="lax", max_age=60 * 60 * 24 * 365,
                        secure=os.environ.get("COOKIE_SECURE", "0") == "1")
    return resp


@app.post("/api/reset")
async def reset(wander_uid: str | None = Cookie(default=None)):
    user_id, _ = identity(wander_uid)
    conversations.pop(user_id, None)
    return {"reset": True}


@app.get("/api/memories")
async def memories(wander_uid: str | None = Cookie(default=None)):
    user_id, _ = identity(wander_uid)
    return {**store.recall(user_id), **store.list_bookmarks(user_id)}


# Mounted last so /api/* wins.
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", 8000)))
