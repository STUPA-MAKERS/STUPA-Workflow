# Alembic-Migrationen

Async-SQLAlchemy-2.0-Setup. Ziel-Metadata = `app.db.Base.metadata` (über
`app.models` befüllt). Env-Konfiguration: `env.py`; Template: `script.py.mako`.

## Konvention: Hash-Revision-IDs (ab sofort)

**Neue Migration = `alembic revision` mit der von Alembic vergebenen Hash-ID.**
Kein `--rev-id`, keine fortlaufende `000N`-Nummer mehr.

```bash
cd backend
alembic revision -m "kurzbeschreibung"
# -> migrations/versions/<hash>_kurzbeschreibung.py  (z.B. aa50a10a8072_…)

alembic heads          # MUSS genau einen head zeigen
alembic upgrade head   # MUSS grün durchlaufen
```

`down_revision` wird automatisch auf den aktuellen head gesetzt, solange genau ein
head existiert. Erscheint nach einem Merge ein **zweiter** head, ist das ein echter
Konflikt — auflösen, indem die eigene Revision auf den gemergten head umgehängt wird
(`down_revision` anpassen), **nicht** per `alembic merge` und **nicht** per
Umnummerierung.

### Warum Hash statt `000N`

Parallele Entwicklungs-Wellen vergaben unabhängig dieselbe nächste fortlaufende
Nummer (`0016` kollidierte zweimal), was bei jedem Merge manuelles Renumbering
erzwang. Zufalls-Hashes kollidieren praktisch nie; der einzig verbleibende
Mergekonflikt-Punkt ist der head-Vergleich (single-head) — und der soll sichtbar
sein.

### Bestand bleibt

Die existierende Kette `0001_core_extensions … 0017_role_assignment_deleg` wird
**nicht** umbenannt. Nur *neue* Revisions bekommen Hash-IDs. `file_template` in
`alembic.ini` ist `%%(rev)s_%%(slug)s` — bei Hash-IDs ergibt das
`<hash>_<slug>.py`, bei den Bestands-Dateien bleibt es `<nnnn>_<slug>.py`.

## Tabellen vs. Daten

Tabellen/Modelle entstehen über `Base.metadata.create_all` in `0002_core_tables`
(Single-Source-Pattern: Modelle und Schema bleiben deckungsgleich). Eine neue
Tabelle braucht daher i. d. R. **keine** eigene DDL-Migration — sie kommt über die
Metadata mit. Reine Daten-/Seed-/Constraint-/Index-Änderungen bekommen je eine
eigene Revision.

## Lokal verifizieren

```bash
cd backend
alembic heads          # ein head
alembic history | head # Kette ok
# gegen echtes Postgres (compose oder Wegwerf-Container):
alembic upgrade head
```
