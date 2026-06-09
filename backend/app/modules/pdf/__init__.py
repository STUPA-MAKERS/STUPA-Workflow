"""PDF-Modul (T-20): Markdown-Gen + pytex-Client + MinIO.

Antrags-PDFs entstehen **asynchron**: die API legt einen ``render_job`` an (202 +
``jobId``), der arq-Worker baut das Markdown, ruft den pytex-Container ``POST /render``
und legt das PDF in MinIO ab. ``GET /jobs/{id}`` liefert den Status + (bei Erfolg) eine
kurzlebige, signierte Ergebnis-URL.
"""
