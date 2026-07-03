"""PDF module: application-Markdown generation, pytex client, MinIO storage.

Application PDFs render asynchronously: the API creates a ``render_job`` (202 +
``jobId``), the arq worker builds the Markdown, calls pytex ``POST /render`` and
stores the PDF in MinIO. ``GET /jobs/{id}`` returns the status plus, on success, a
short-lived signed result URL.
"""
