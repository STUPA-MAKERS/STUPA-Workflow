# Alembic migrations

Async SQLAlchemy 2.0 setup. The target metadata is `app.db.Base.metadata`. The import
of `app.models` fills it. The environment configuration is in `env.py`. The template is
`script.py.mako`.

## Convention: hash revision IDs (from now on)

**A new migration uses `alembic revision` with the hash ID that Alembic assigns.**
Do not pass `--rev-id`. Do not use a running `000N` number.

```bash
cd backend
alembic revision -m "short_description"
# -> migrations/versions/<hash>_short_description.py  (for example aa50a10a8072_…)

alembic heads          # MUST show exactly one head
alembic upgrade head   # MUST run green
```

Alembic sets `down_revision` to the current head by itself, as long as exactly one head
exists. A **second** head after a merge is a real conflict. Resolve it: point your own
revision at the merged head through `down_revision`. Do **not** use `alembic merge`. Do
**not** renumber.

### Why a hash and not `000N`

Parallel development streams handed out the same next running number on their own.
`0016` collided twice, and every merge then forced a manual renumbering. Random hashes
almost never collide. One merge-conflict point is left: the head comparison (single
head). That conflict must stay visible.

### The existing chain stays

The existing chain `0001_core_extensions … 0017_role_assignment_deleg` keeps its names.
Only *new* revisions get hash IDs. `file_template` in `alembic.ini` is
`%%(rev)s_%%(slug)s`. A hash ID gives `<hash>_<slug>.py`. The existing files keep
`<nnnn>_<slug>.py`.

## Tables versus data

`Base.metadata.create_all` in `0002_core_tables` creates the tables from the models
(single-source pattern: the models and the schema stay identical). A new table
therefore needs no DDL migration of its own as a rule. It arrives with the metadata.
Data, seed, constraint and index changes each get their own revision.

## Verify locally

```bash
cd backend
alembic heads          # one head
alembic history | head # chain ok
# against a real Postgres (compose or throwaway container):
alembic upgrade head
```
