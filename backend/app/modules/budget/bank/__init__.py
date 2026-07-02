"""Bankabgleich (#fints) — FinTS-Abruf, Auszug-Parser, Staging, Reconcile.

Aufbau:

* :mod:`.statement`   — quellen-agnostische Datentypen + Format-Erkennung (Einstieg
  für Datei-Importe: :func:`~.statement.parse_statement_full`).
* :mod:`.mt940_parse` — MT940 (``.sta``) → :class:`~.statement.StatementLine`.
* :mod:`.camt_parse`  — CAMT.052/053 (XML) → StatementLine, inkl. Aufteilung von
  Sammelbuchungen (ein ``Ntry``, n ``TxDtls``) in Einzelumsätze.
* :mod:`.normalize`   — reine Text-/IBAN-/Gegenkonto-Normalisierung.
* :mod:`.dedup`       — Idempotenz-Schlüssel + roh-basierte Dedup-Grundlage.
* :mod:`.client`      — FinTS-Netz-Client (PIN/TAN-SCA, CAMT-bevorzugter Abruf).
* :mod:`.match`       — Bewertung Umsatz ↔ bestehende Buchung.
* :mod:`.service`     — :class:`~.service.BankService` (HTTP-Fassade, DB-Orchestrierung),
  zusammengesetzt aus ``credentials``/``sync``/``staging``/``reconcile``/``listing``.
* :mod:`.maintenance` — idempotente Aufräum-Routinen für Migrationen.
"""
