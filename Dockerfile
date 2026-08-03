FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py main.py version.py ./
COPY handlers ./handlers
COPY infrastructure ./infrastructure
COPY policies ./policies
COPY routers ./routers
COPY services ./services

USER 10001:10001

ENTRYPOINT ["python", "/app/main.py"]
CMD ["--config", "/config/JellyfinProxy.toml"]
