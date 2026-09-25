# Wander — hosted deployment image.
# Runs the Groq-backed build (no local model needed, so a small free container
# is enough). Local development does NOT use this — it runs Ollama directly.
FROM python:3.11-slim

WORKDIR /app

# Deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code. .dockerignore keeps the venv, DB and docs out of the image.
COPY server/ ./server/
COPY web/ ./web/

# Hosted build talks to Groq, not a local model.
ENV WANDER_BACKEND=groq \
    WANDER_MODEL=openai/gpt-oss-20b \
    HOST=0.0.0.0 \
    PORT=8000 \
    COOKIE_SECURE=1

# GROQ_API_KEY and WANDER_SECRET are injected by the host as secrets — never baked in.
EXPOSE 8000

# Respect the platform's $PORT (Render/Spaces set it); default to 8000 locally.
CMD ["sh", "-c", "uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
