# Deploying Wander (always-on, free)

Local development runs against **Ollama** — no key, no cost. This guide is for the
**hosted** build, which swaps the local model for **Groq's free API** so it can run
on a small free container with no GPU. Same code, same tools; only the model
backend changes, controlled by `WANDER_BACKEND`.

## What it costs

Nothing, if you stay on the paths below. The only ways a charge can appear are
all opt-in: a host that requires a card (Fly.io), a persistent volume / managed
database, a custom domain, or explicitly upgrading Groq's tier. None happen
automatically.

Accepted trade-offs for $0:
- **Cold start** — the free web service sleeps after ~15 min idle; the first
  request after a lull takes ~30–60s to wake.
- **Ephemeral memory** — the container's disk resets on redeploy. The
  destination catalog re-seeds automatically on startup, but saved bookmarks and
  remembered preferences do not survive a redeploy. Fine for a demo.

## Step 1 — get a free Groq key

1. Sign up at <https://console.groq.com> (no credit card).
2. Create an API key. Copy it — you set it as a secret in step 3, never in code.

The default hosted model is `llama-3.1-8b-instant` — the same 8B Llama family you
run locally, so behaviour is consistent.

## Step 2 — pick a host (both free, no card)

**Render** (recommended — `render.yaml` is already in the repo):

1. <https://dashboard.render.com> → **New → Web Service** → connect the
   `ysultankpg/wander` repo.
2. Render detects `render.yaml` and the `Dockerfile` automatically.
3. In the service's **Environment**, add one secret:
   `GROQ_API_KEY = <your key>`.
   `WANDER_SECRET` is generated for you; `WANDER_BACKEND=groq` is already set.
4. **Create Web Service**. First build takes a few minutes.

Your live URL will be `https://wander-<hash>.onrender.com`.

**Hugging Face Spaces** (alternative — also no card):

1. Create a new **Docker** Space.
2. Push this repo to it (or point it at GitHub).
3. In **Settings → Variables and secrets**, add `GROQ_API_KEY` (secret) and
   `WANDER_SECRET` (secret). Spaces sets `PORT` itself; the Dockerfile respects it.

## Step 3 — verify

Once deployed, hit `https://<your-url>/api/health`. Expect:

```json
{"ok": true, "detail": "groq ready", "backend": "groq", "model": "llama-3.1-8b-instant"}
```

If `ok` is false, `detail` tells you what's wrong — almost always a missing or
rejected `GROQ_API_KEY`.

## Local development is unchanged

```bash
./run.sh                      # WANDER_BACKEND defaults to ollama
```

To exercise the Groq path locally before deploying:

```bash
export WANDER_BACKEND=groq
export GROQ_API_KEY=<your key>
.venv/bin/python -m uvicorn server.app:app --port 8000
```

## Linking it from the showcase page

Once you have the live URL, tell me and I'll wire a "Try it live" button on the
GitHub Pages showcase (`docs/index.html`) pointing at it.
