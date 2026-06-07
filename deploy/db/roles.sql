-- deploy/db/roles.sql — Least-Privilege-DB-Rollen (security.md §4/§10, deployment.md §3).
--
-- EINMALIG als Superuser (postgres) bei der Provisionierung ausführen. Zweistufig:
--   1) Schritte 1–4 VOR `alembic upgrade head` (die Rollen müssen existieren, bevor
--      der Migrations-User die Tabellen anlegt).
--   2) Schritt 5 NACH `alembic upgrade head` (braucht die Tabelle `audit_entry`).
-- Beides ist idempotent (DO-Blöcke / IF EXISTS) → mehrfach gefahrlos ausführbar.
--
-- Passwörter NICHT hier einchecken: nach CREATE ROLE per
--   ALTER ROLE app      PASSWORD '…';
--   ALTER ROLE migrator PASSWORD '…';
-- setzen (Werte aus dem Secret-Store). Die App nutzt `app` (DATABASE_URL), die
-- Migrationen `migrator` (DB_MIGRATION_URL) — getrennte Service-User.

-- 1) Migrations-User (DDL) — getrennt vom Runtime-User.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'migrator') THEN
    CREATE ROLE migrator LOGIN;
  END IF;
END $$;

-- 2) Runtime-User (DML/CRUD) — die App. Kein DDL.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app') THEN
    CREATE ROLE app LOGIN;
  END IF;
END $$;

-- 3) Optionaler dedizierter Audit-Writer (INSERT/SELECT). Den eigentlichen Grant
--    auf `audit_entry` setzt Migration 0006 conditional, sobald diese Rolle existiert.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'audit_writer') THEN
    CREATE ROLE audit_writer NOLOGIN;
  END IF;
END $$;

-- 4) Runtime-User bekommt DML auf alle (vom Migrations-User erzeugten) Tabellen,
--    aber kein DDL. Default-Privileges greifen für künftige Migrationen automatisch.
GRANT CONNECT ON DATABASE antrag TO app, migrator;
GRANT USAGE ON SCHEMA public TO app;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO app;

-- 5) NACH den Migrationen: Audit-Least-Privilege. Der Runtime-User darf `audit_entry`
--    nur INSERT/SELECT — NIE UPDATE/DELETE/TRUNCATE (Hash-Kette unveränderlich,
--    security.md §4). Der DB-Trigger (Migration 0006) erzwingt Append-only zusätzlich
--    rollenunabhängig; dieser Entzug ist die Least-Privilege-Schicht darüber.
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_entry'
  ) THEN
    REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_entry FROM app;
    GRANT INSERT, SELECT ON TABLE audit_entry TO app;
  END IF;
END $$;
