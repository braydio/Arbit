FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir \
    ccxt \
    websockets \
    pydantic \
    typer \
    prometheus-client \
    orjson

COPY arbit ./arbit

ENTRYPOINT ["python", "-m", "arbit.cli", "live"]
