# Decision API image. Build from the repo root (context = root, so uv.lock is available):
#   az acr build -r <registry> -t lending-api:<git sha> -f api/Dockerfile .
# Dependencies come from uv.lock (api group only), so the image runs the versions that were tested.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
# --frozen: fail if uv.lock is out of date instead of resolving new versions at build time.
# --only-group api: the API's libraries only (no model, notebook or dev tooling).
RUN uv sync --frozen --no-install-project --no-default-groups --only-group api \
    && useradd --system --uid 10001 app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

COPY api/ ./api/

# Non-root: a compromised process can't modify the image's files. Port 8000 (no root needed to bind it).
USER app
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
