# Snacky: one process, MCP on 8000 and the web UI on 8080.
# Same base as the homelab MCP image so both share layers on the node.
FROM python:3.14-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS base

FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.20@sha256:100047e74f30778ab704942321a09750d6158739573ff58bf3924085cc6cd2d8 /uv /usr/local/bin/uv
# UV_PYTHON_DOWNLOADS=never makes uv use the base image's interpreter, so the
# venv's python symlink still resolves in the runtime stage.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# The project itself is not installed: the runtime stage puts src/ on PYTHONPATH.
RUN uv sync --frozen --no-dev --no-install-project

# BLS stage, not active yet. It turns on once scripts/build_bls.py is on main:
# it converts the BLS download into the SQLite index that snacky.sources.bls reads.
#
# FROM builder AS bls
# COPY scripts/ ./scripts/
# RUN uv run --group bls-build python scripts/build_bls.py /out/bls.sqlite

FROM base AS runtime
LABEL org.opencontainers.image.source="https://github.com/pxldi/snacky" \
      org.opencontainers.image.licenses="GPL-3.0-only" \
      org.opencontainers.image.description="Protein and calorie log fed by a chat assistant over MCP"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/src

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src/ ./src/
# When the BLS stage is active, also add:
# COPY --from=bls /out/bls.sqlite /app/data/bls.sqlite

# The commit this image was built from, reported by /health as "build". The
# homelab's wait-for-mcp compares it to know a rollout finished.
ARG GIT_SHA=dev
ENV IMAGE_SHA=$GIT_SHA

# /data holds the SQLite file and is the only path written at runtime, so the
# deployment can mount it and make the root filesystem read-only.
RUN mkdir /data && chown 1000:1000 /data

USER 1000:1000
EXPOSE 8000 8080
CMD ["python", "-m", "snacky"]
