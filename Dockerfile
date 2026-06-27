# Multi-stage build: a uv-bearing stage resolves the locked deps into a venv,
# then a slim runtime carries only that venv and the app. Serves the FastAPI
# app (UI at /, JSON API at /api) on port 18990.

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Install dependencies first (cached layer) using only the lock + manifest, then
# the project itself, so dependency resolution is not invalidated by source edits.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra web

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra web


FROM python:3.14-slim AS runtime

# Run as a non-root user; the service needs no privileges.
RUN useradd --create-home --uid 10001 app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    COMMON_FILE_GEN_HOST=0.0.0.0 \
    COMMON_FILE_GEN_PORT=18990

COPY --from=build /opt/venv /opt/venv
COPY --from=build /app/src /app/src

WORKDIR /app
USER app

EXPOSE 18990

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('COMMON_FILE_GEN_PORT','18990')}/health\").status==200 else 1)"]

# Host and port come from COMMON_FILE_GEN_HOST / COMMON_FILE_GEN_PORT (set above);
# override at run time with -e COMMON_FILE_GEN_PORT=... and the matching -p mapping.
CMD ["gen-ui"]
