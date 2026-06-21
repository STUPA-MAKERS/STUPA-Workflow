"""gremium_membership_overlap: DB-Backing der Overlap-Invariante (#42, AUD-029).

Pro ``(principal_id, gremium_id)`` darf sich kein Amtszeit-Intervall überschneiden.
Bisher nur Service-seitig geprüft (TOCTOU-Lücke bei zwei parallelen Inserts). Diese
Migration legt die ``EXCLUDE``-Constraint an, die die ORM-Definition in
``app/modules/admin/models.py`` spiegelt (halboffenes Intervall ``[from, until)``,
NULL = ±unendlich). Setzt die ``btree_gist``-Extension voraus.

Vor dem Anlegen werden eventuell bereits vorhandene Überschneidungen deterministisch
bereinigt (sonst schlägt ``ADD CONSTRAINT`` fehl): pro Überlappungspaar bleibt die
Mitgliedschaft mit dem späteren Start erhalten, ältere werden gelöscht (Tie-Break per
``id``). Die gelöschten Zeilen sind NICHT wiederherstellbar.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0038_gremium_membership_overlap"
down_revision: str | None = "0037_applicant_session"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Vorhandene Überschneidungen bereinigen, bevor die Constraint greift. Behalte je
    #    Paar die Mitgliedschaft mit dem späteren Start (Tie-Break: kleinere id verliert),
    #    damit der Lauf deterministisch konvergiert.
    op.execute(
        """
        DELETE FROM gremium_membership a
        USING gremium_membership b
        WHERE a.principal_id = b.principal_id
          AND a.gremium_id = b.gremium_id
          AND a.id <> b.id
          AND tstzrange(coalesce(a.valid_from, '-infinity'),
                        coalesce(a.valid_until, 'infinity'), '[)')
              && tstzrange(coalesce(b.valid_from, '-infinity'),
                           coalesce(b.valid_until, 'infinity'), '[)')
          AND (
               coalesce(a.valid_from, '-infinity') < coalesce(b.valid_from, '-infinity')
               OR (coalesce(a.valid_from, '-infinity') = coalesce(b.valid_from, '-infinity')
                   AND a.id < b.id)
              )
        """
    )

    # 2) btree_gist wird für eine GIST-EXCLUDE über Gleichheits-Spalten (=) benötigt.
    #    Falls der Deploy-Rollenrechte fehlen, muss ein DB-Admin die Extension vorab
    #    anlegen — dann ist dies ein No-op (vgl. 0027 / pg_trgm).
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # 3) EXCLUDE-Constraint — exakt wie die ExcludeConstraint im ORM.
    op.execute(
        """
        ALTER TABLE gremium_membership
        ADD CONSTRAINT ex_gremium_membership_no_overlap
        EXCLUDE USING gist (
            principal_id WITH =,
            gremium_id WITH =,
            tstzrange(coalesce(valid_from, '-infinity'),
                      coalesce(valid_until, 'infinity'), '[)') WITH &&
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE gremium_membership "
        "DROP CONSTRAINT IF EXISTS ex_gremium_membership_no_overlap"
    )
    # btree_gist bleibt absichtlich installiert (andere Objekte könnten sie nutzen;
    # spiegelt die Behandlung von pg_trgm in 0027). Gelöschte Überlappungen sind nicht
    # wiederherstellbar.
