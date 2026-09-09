FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# WeasyPrint needs cairo/pango for invoice PDFs; psycopg needs libpq.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libpq-dev libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
      libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e .

COPY . .

RUN adduser --disabled-password --gecos "" appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD curl -fsS http://localhost:8000/health/live/ || exit 1

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "4", "--timeout", "60", "--access-logfile", "-"]
