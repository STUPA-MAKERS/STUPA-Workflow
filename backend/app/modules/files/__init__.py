"""Files module: attachment upload + MIME sniff + ClamAV + MinIO + signed URLs.

* :mod:`models`   — ``attachment`` table.
* :mod:`mime`     — libmagic sniffing + type allowlist.
* :mod:`storage`  — MinIO/S3 backend + short-lived signed URLs.
* :mod:`scanner`  — ClamAV/clamd scan (worker) + ``ScanVerdict``.
* :mod:`queue`    — arq enqueue of the ``scan_attachment`` job (idempotent).
* :mod:`service`  — upload/quarantine/download/scan completion.
* :mod:`router`   — ``POST /applications/{id}/attachments``, ``GET /attachments/{id}``.
"""
