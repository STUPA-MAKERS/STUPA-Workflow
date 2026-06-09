"""Protokoll-Modul (T-22, api.md »protocol«, flows §7).

Sitzungsprotokoll (Markdown-Backing für den Editor) inkl. ``finalize`` → pytex →
PDF → MinIO → Versand an die Gremium-Mailingliste. Baut auf der
T-20-Render-Infrastruktur (:mod:`app.modules.pdf`) auf, ohne pytex/Storage/
Mail-Code zu duplizieren.
"""
