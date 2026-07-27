"""Protocol module: meeting minutes.

The module stores a Markdown body for the editor. The `finalize` step renders
that body with pytex, puts the PDF into MinIO and mails it to the gremium
mailing list. It reuses the render infrastructure of `app.modules.pdf` instead
of a second copy of the pytex, storage and mail code.
"""
