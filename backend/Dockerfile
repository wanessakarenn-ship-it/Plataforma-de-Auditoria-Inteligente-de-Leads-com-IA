FROM ghcr.io/astral-sh/uv:0.11.26 AS uv

FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/

ENV APP_ENV=production \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    VERTEX_AI_ENABLED=false \
    VERTEX_AI_APPROVED=false

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/__init__.py ./backend/__init__.py
COPY backend/app ./backend/app
COPY backend/migrations ./backend/migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

RUN useradd --system --uid 10001 --create-home app
USER app

EXPOSE 8080
CMD ["sh", "-c", "exec .venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
