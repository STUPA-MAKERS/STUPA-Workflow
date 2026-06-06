"""files-Modul (T-13): Anhang-Upload + MIME-Sniff + ClamAV + MinIO + signierte URLs.

* :mod:`models`   — ``attachment``-Tabelle (data-model §1).
* :mod:`mime`     — libmagic-Sniffing + Typ-Allowlist (security.md §6).
* :mod:`storage`  — MinIO/S3-Backend + kurzlebige signierte URLs.
* :mod:`scanner`  — ClamAV/clamd-Scan (Worker) + ``ScanVerdict``.
* :mod:`queue`    — arq-Enqueue des ``scan_attachment``-Jobs (idempotent).
* :mod:`service`  — Upload/Quarantäne/Download/Scan-Abschluss.
* :mod:`router`   — ``POST /applications/{id}/attachments``, ``GET /attachments/{id}``.
"""
