"""Files module: attachment upload, MIME sniff, ClamAV, MinIO and signed URLs.

``models`` defines the ``attachment`` table.
``mime`` sniffs with libmagic and holds the type allowlist.
``storage`` wraps the MinIO/S3 backend and the short-lived signed URLs.
``scanner`` runs the ClamAV/clamd scan in the worker and returns a ``ScanVerdict``.
``queue`` enqueues the ``scan_attachment`` job in arq with an idempotent job id.
``service`` handles upload, quarantine, download and scan completion.
``router`` serves ``POST /applications/{id}/attachments`` and ``GET /attachments/{id}``.
"""
