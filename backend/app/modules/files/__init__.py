"""Files module: attachment upload, MIME sniff, ClamAV, MinIO and gated downloads.

``models`` defines the ``attachment`` table.
``mime`` sniffs with libmagic and holds the type allowlist.
``storage`` wraps the MinIO/S3 backend.
``scanner`` runs the ClamAV/clamd scan in the worker and returns a ``ScanVerdict``.
``queue`` enqueues the ``scan_attachment`` job in arq with an idempotent job id.
``service`` handles upload, quarantine, download and scan completion.
``body`` reads an upload body with a size cap.

The routes are in the module `attachments` (§S/backend/python/000651).
"""
