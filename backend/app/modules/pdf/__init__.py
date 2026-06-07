"""PDF-Modul (T-20): Markdown-Gen + pytex-Client + MinIO + Nextcloud-WebDAV.

Antrags-PDFs entstehen **asynchron**: die API legt einen ``render_job`` an (202 +
``jobId``), der arq-Worker baut das Markdown, ruft den pytex-Container ``POST /render``,
legt das PDF in MinIO und exportiert es optional per Nextcloud-WebDAV. ``GET /jobs/{id}``
liefert den Status + (bei Erfolg) eine kurzlebige, signierte Ergebnis-URL.
"""
