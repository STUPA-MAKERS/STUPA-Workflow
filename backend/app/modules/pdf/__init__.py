"""PDF module: the HTTP client of the typst render service.

The protocol module is the one caller. It renders a meeting protocol through
``TypstClient.render_pdf`` and stores the PDF in MinIO itself.
"""
