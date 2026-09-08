FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY src ./src

RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels .


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system fdre \
    && useradd --system --gid fdre --create-home --home-dir /home/fdre fdre

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels fdre \
    && rm -rf /wheels

COPY --chown=fdre:fdre alembic.ini ./
COPY --chown=fdre:fdre apps/api/alembic ./apps/api/alembic
COPY --chown=fdre:fdre scripts ./scripts
COPY --chown=fdre:fdre data/sample ./data/sample

USER fdre

EXPOSE 8000

CMD ["sh", "-c", "uvicorn apps.api.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
