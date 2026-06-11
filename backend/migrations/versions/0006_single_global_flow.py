"""Genau **ein** Flow, keine Versionen: alle Anträge auf den einen globalen Flow ziehen.

Erzwingt die Invariante (vom PO gefordert):
* Es bleibt **genau eine** ``flow_version`` (der aktive/letzte globale Flow); alle
  anderen (globale Alt-Versionen + Per-Typ-Flows) werden gelöscht.
* Jeder Antrag wird auf diesen Flow gepinnt; sein ``current_state`` wird per **KEY**
  gemappt — ein gelöschter State ⇒ **Initial-State**.
* Der verbleibende Flow hat **mindestens einen** Initial-State (sonst wird der erste
  State zum Initial gemacht).

Idempotent: nach dem Lauf bleibt nur ein Flow; ein erneuter Lauf ist ein No-op.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_single_global_flow"
down_revision: str | None = "0005_accounts_and_transfers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FORCE = """
DO $$
DECLARE
    gid uuid;
    init_id uuid;
    has_type_col boolean;
BEGIN
    -- Frische Installationen (Baseline = create_all aus den AKTUELLEN Models)
    -- kennen die Typ-Flow-Spalten seit 0019 nicht mehr — alles Spalten-abhängige
    -- nur ausführen, wenn die Spalte (Bestands-DB) noch existiert.
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'flow_version' AND column_name = 'application_type_id'
    ) INTO has_type_col;

    -- Den einen globalen Flow wählen (aktiv zuerst, sonst höchste Version).
    IF has_type_col THEN
        SELECT id INTO gid FROM flow_version
         WHERE application_type_id IS NULL
         ORDER BY active DESC, version DESC
         LIMIT 1;
    ELSE
        SELECT id INTO gid FROM flow_version
         ORDER BY active DESC, version DESC
         LIMIT 1;
    END IF;
    IF gid IS NULL THEN
        -- Kein globaler Flow: irgendeinen vorhandenen Flow zum globalen machen.
        SELECT id INTO gid FROM flow_version ORDER BY version DESC LIMIT 1;
    END IF;
    IF gid IS NULL THEN
        RETURN;  -- gar kein Flow vorhanden → nichts zu erzwingen.
    END IF;

    IF has_type_col THEN
        UPDATE flow_version SET application_type_id = NULL, active = true WHERE id = gid;
    ELSE
        UPDATE flow_version SET active = true WHERE id = gid;
    END IF;

    -- Mindestens ein Initial-State.
    SELECT id INTO init_id FROM state
     WHERE flow_version_id = gid AND is_initial LIMIT 1;
    IF init_id IS NULL THEN
        SELECT id INTO init_id FROM state
         WHERE flow_version_id = gid ORDER BY key LIMIT 1;
        IF init_id IS NOT NULL THEN
            UPDATE state SET is_initial = true WHERE id = init_id;
        END IF;
    END IF;

    -- Jeden Antrag auf den einen Flow ziehen; State per KEY mappen, sonst Initial.
    UPDATE application a
       SET current_state_id = COALESCE(
               (SELECT s2.id FROM state s2
                 WHERE s2.flow_version_id = gid
                   AND s2.key = (SELECT s1.key FROM state s1
                                  WHERE s1.id = a.current_state_id)),
               init_id),
           flow_version_id = gid;

    -- Per-Typ-Zeiger lösen, damit deren Versionen gelöscht werden können
    -- (Spalte existiert nur noch auf Bestands-DBs, fällt mit 0019).
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'application_type'
           AND column_name = 'active_flow_version_id'
    ) THEN
        UPDATE application_type SET active_flow_version_id = NULL;
    END IF;

    -- Alle anderen Flows löschen (state/transition hängen per CASCADE dran).
    DELETE FROM flow_version WHERE id <> gid;
END $$;
"""


def upgrade() -> None:
    op.execute(_FORCE)


def downgrade() -> None:
    # Nicht umkehrbar (gelöschte Alt-Versionen sind verloren). Bewusst No-op.
    pass
