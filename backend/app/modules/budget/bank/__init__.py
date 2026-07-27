"""Bank reconciliation: FinTS fetch, statement parsers, staging, reconcile.

Modules of this package:

`statement` defines the source-agnostic data types and detects the format. Files enter
through `statement.parse_statement_full`.
`mt940_parse` maps MT940 (`.sta`) to `statement.StatementLine`.
`camt_parse` maps CAMT.052/053 (XML) to StatementLine. It also splits a batch booking
(one `Ntry` with n `TxDtls`) into single transactions.
`normalize` holds the pure text, IBAN and counterparty normalization.
`dedup` builds the idempotency keys and the raw dedup base.
`client` is the FinTS network client (PIN/TAN SCA, CAMT-preferred fetch).
`match` scores a transaction against an existing booking.
`service` holds `service.BankService`, the HTTP facade and the DB orchestration. It is
composed of `credentials`, `sync`, `staging`, `reconcile` and `listing`.
`maintenance` holds the idempotent cleanup routines for migrations.
"""
