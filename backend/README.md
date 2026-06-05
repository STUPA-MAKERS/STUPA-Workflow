# backend

Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async) + Alembic, arq (Worker),
uvicorn (`--proxy-headers`).

**Status:** Skelett (T-01) — `app/main.py` (`/health`), `worker/main.py` (arq
WorkerSettings + No-op-Task). App-Factory/Settings/db/deps/Error-Contract: **T-02**.
Module (`app/modules/*`), Migrationen, Config-Schemas: T-02/T-05/T-06+.

## Lokal

```bash
pip install -e '.[dev]'
ruff check .
basedpyright
pytest
```
