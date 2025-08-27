FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir \
    ccxt==4.1.79 \
    websockets==11.0.3 \
    pydantic==1.10.9 \
    typer==0.9.0 \
    prometheus-client==0.17.1 \
    orjson==3.9.5

COPY arbit ./arbit

ENTRYPOINT ["python", "-m", "arbit.cli", "live"]
