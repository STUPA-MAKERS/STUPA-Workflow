"""pytex render service — Skelett (T-01).

FastAPI-Wrapper-Platzhalter. /health jetzt; reales /render (pytex_api.render_blob,
md->pdf, tectonic-Cache) in T-21.
"""

from fastapi import FastAPI, Response, status

app = FastAPI(title="pytex render service", version="0.0.1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/render")
def render() -> Response:
    """Stub — Implementierung in T-21."""
    return Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)
