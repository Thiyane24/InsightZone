# ── STAGE 1: COMPILAÇÃO E DEPENDÊNCIAS (BUILDER) ─────────────────────────────
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── STAGE 2: EXECUÇÃO EM PRODUÇÃO (FINAL) ────────────────────────────────────
FROM python:3.11-slim AS final

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*


COPY --from=builder /install /usr/local

 
RUN useradd -u 5678 -r -s /bin/bash appuser \
    && mkdir -p data/uploads data/gold

COPY --chown=appuser:appuser . .


RUN chown -R appuser:appuser /app/data

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]