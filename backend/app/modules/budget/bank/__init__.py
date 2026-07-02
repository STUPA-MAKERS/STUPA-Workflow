"""Bank reconciliation — FinTS fetch, statement parsers, staging, reconcile.

Layout:

* :mod:`.statement`   — source-agnostic data types + format detection (file-import
  entry point: :func:`~.statement.parse_statement_full`).
* :mod:`.mt940_parse` — MT940 (``.sta``) to :class:`~.statement.StatementLine`.
* :mod:`.camt_parse`  — CAMT.052/053 (XML) to StatementLine, incl. splitting batch
  bookings (one ``Ntry``, n ``TxDtls``) into single transactions.
* :mod:`.normalize`   — pure text/IBAN/counterparty normalization.
* :mod:`.dedup`       — idempotency keys + raw-based dedup base.
* :mod:`.client`      — FinTS network client (PIN/TAN SCA, CAMT-preferred fetch).
* :mod:`.match`       — scoring of transaction vs. existing booking.
* :mod:`.service`     — :class:`~.service.BankService` (HTTP facade, DB orchestration),
  composed of ``credentials``/``sync``/``staging``/``reconcile``/``listing``.
* :mod:`.maintenance` — idempotent cleanup routines for migrations.
"""
