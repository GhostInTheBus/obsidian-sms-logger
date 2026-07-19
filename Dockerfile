# SMS Logger — pure-python logging server (no torch, no LLM)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

RUN mkdir -p data/logs profiles && chmod -R 755 /app

EXPOSE 5066

# --workers 1 is load-bearing: the Obsidian export loop starts at import time
# and is not multi-worker safe (state-file races).
CMD ["gunicorn", "--bind", "0.0.0.0:5066", "--timeout", "120", "--workers", "1", "server:app"]
