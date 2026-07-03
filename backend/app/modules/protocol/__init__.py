"""Protocol module: meeting minutes.

Markdown backing for the editor, plus ``finalize`` → pytex → PDF → MinIO →
mail to the gremium mailing list. Reuses the render infrastructure from
:mod:`app.modules.pdf` instead of duplicating pytex/storage/mail code.
"""
