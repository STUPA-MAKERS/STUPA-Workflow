"""PDF module: application-Markdown generation, pytex client, MinIO storage.

Application PDFs render asynchronously. The API creates a ``render_job`` and answers
202 with the ``jobId``. The arq worker builds the Markdown, calls pytex
``POST /render`` and stores the PDF in MinIO. ``GET /jobs/{id}`` returns the status.
On success it also returns a short-lived signed result URL.
"""
