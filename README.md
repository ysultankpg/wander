# Wander

A travel-planning agent that runs entirely on your own machine. No Google Cloud,
no Vertex AI, no API keys, no billing account, no project quota — nothing to
switch off and nothing to pay for.

## Why this exists

The previous version was a Vertex AI Agent Engine deployment. It stopped working
because the reasoning engine lived in a lab project the account no longer had IAM
access to, returning `403` on every request. A deployment you cannot reach and
cannot re-deploy is not a product. This rebuild has no such dependency: if your
laptop boots, the agent runs.

## The stack

| Concern | Old | Now | Cost |
|---|---|---|---|
| Model | Gemini via Vertex AI | Ollama `llama3.1:8b`, local | $0 |
| Memory | Vertex AI Memory Bank | SQLite (`wander.db`) | $0 |
| Catalog | Firestore | SQLite, 18 seeded destinations | $0 |
| Weather & time | invented by the model | Open-Meteo (keyless) | $0 |
| Exchange rates | invented | Frankfurter / ECB (keyless) | $0 |
| Places | invented | OpenStreetMap Overpass | $0 |
| Photos | a 44-byte fake MP4 | Wikimedia Commons | $0 |
| Serving | Cloud Run + Agent Engine | uvicorn on localhost | $0 |

## Run it

```bash
brew install ollama
brew services start ollama
ollama pull llama3.1:8b

cd wander
uv venv --python 3.11
uv pip install --python .venv/bin/python fastapi "uvicorn[standard]" httpx itsdangerous

.venv/bin/python -m uvicorn server.app:app --port 8000
```

Open <http://localhost:8000>. The chat interface is served at the root URL —
there is no separate landing page to click through.

Set `WANDER_SECRET` to a fixed value if you want identity cookies to survive a
restart. `WANDER_MODEL` swaps the model (`qwen2.5:7b` and `mistral-nemo` also
handle tool calls well).

## Design decisions that matter

**Nothing is invented.** The system prompt's grounding rules forbid guessing any
fact a tool can supply, and the tools are built so a failure is *visible*: a
throttled weather response returns `{"error": ...}` rather than an empty dict the
model could narrate as real conditions. `search_destinations` relaxes an
unmatched filter and says so instead of returning nothing — an empty result is an
invitation to hallucinate.

**`user_id` is never a model argument.** It is derived server-side from a signed
`HttpOnly` cookie and injected by the dispatcher, which strips any `user_id` the
model tries to supply. Bookmark deletion enforces ownership in the `WHERE`
clause, not after the fetch. Verified: an injected id returns the session user's
own empty memories, and a cross-user delete returns `No such bookmark for this
traveller.`

**No `innerHTML` on model output.** The renderer escapes first, then applies a
fixed rule set, and drops any image or link URL that is not `http(s)`.

**Bounded everything.** Four tool rounds per turn, twelve messages of history,
500 conversations LRU-capped, 4000-character messages, retry with backoff on the
free APIs.

## Layout

```
server/
  app.py            FastAPI: SSE chat, signed cookie identity, static mount
  agent.py          Ollama tool-calling loop
  prompts.py        persona, grounding rules, planning workflow, safety
  verify.py         live check of every tool against the real APIs
  tools/
    registry.py     14 tool schemas + the security-critical dispatcher
    geo.py          geocoding, weather, local time
    money.py        exchange rates, conversion
    places.py       OpenStreetMap POI search
    images.py       Wikimedia photographs
    store.py        SQLite catalog, bookmarks, memories
    seed.py         18 destinations
web/
  index.html  style.css  app.js  md.js
```

## Verify

```bash
.venv/bin/python -m server.verify
```

Hits every live API and asserts the security properties. Expect real output:
Kyoto's actual temperature, real OSM temple names, the current USD→JPY rate from
the ECB.
