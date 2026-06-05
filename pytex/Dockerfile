# pytex-Service — Skelett (T-01). Reales pytex v1.0.0 + tectonic: T-21.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN pip install "fastapi>=0.115" "uvicorn[standard]>=0.34"

COPY app.py ./

EXPOSE 8099

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8099"]
