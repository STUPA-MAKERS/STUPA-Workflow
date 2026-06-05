"""FastAPI app factory — Skelett (T-01).

Nur /health. Router-Mount, Middleware, Error-Contract, Settings: T-02.
"""

from fastapi import FastAPI

app = FastAPI(title="Antragsplattform API", version="0.0.1")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness-Endpunkt für Container-Healthcheck."""
    return {"status": "ok"}
