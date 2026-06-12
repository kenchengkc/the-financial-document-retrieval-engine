FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY apps ./apps
COPY packages ./packages
COPY scripts ./scripts
COPY data ./data

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn apps.api.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
