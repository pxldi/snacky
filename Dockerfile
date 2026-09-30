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

# Converts the pinned BLS download into the SQLite index that snacky.sources.bls
# reads. Only the two modules the script imports are copied, so an edit
# elsewhere in src/ does not download the archive again.
FROM base AS bls
WORKDIR /app
COPY scripts/ ./scripts/
COPY src/snacky/__init__.py src/snacky/model.py ./src/snacky/
COPY src/snacky/sources/__init__.py src/snacky/sources/bls.py ./src/snacky/sources/
RUN PYTHONPATH=/app/src python scripts/build_bls.py /out/bls.sqlite

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
COPY --from=bls /out/bls.sqlite /app/data/bls.sqlite
# The BLS licence (CC BY 4.0) asks for credit wherever the data is passed on;
# the published image is where that happens, so the notice travels with it.
COPY LICENSE NOTICE /app/

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
