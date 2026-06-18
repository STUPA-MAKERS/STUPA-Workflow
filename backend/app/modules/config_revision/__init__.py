"""Config-Revision-Modul (#config-versioning).

Universelle, **append-only** Snapshot-Historie der versionierten Configs (Forms,
Flow, Branding). Jede Config-Mutation der in-scope-Module hängt einen unveränderlichen
``config_revision``-Snapshot an die Kette (pro ``entity_type``/``entity_id``) und
verlinkt ihn vom Audit-Eintrag (``data.revisionId`` — nur id-Referenz, keine PII).

Trägt drei FE-Fähigkeiten:

* **Versions-Sidebar** — frühere Stände eines Configs auflisten und wiederherstellen
  (``restore``; nie löschbar).
* **Diff** — Feld-Diff zweier aufeinanderfolgender Snapshots (wie Antrags-Detail).
* **Revert** — aus dem Audit-Log einen Config-Change zurücknehmen (``audit.revert``,
  Konflikt-geschützt) — der Revert ist selbst geloggt und revertierbar.
"""
