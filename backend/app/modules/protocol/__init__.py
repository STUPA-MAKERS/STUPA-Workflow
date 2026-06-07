"""Protokoll-Modul (T-22, api.md »protocol«, flows §7).

Sitzungsprotokoll (Markdown-Backing für den Editor) inkl. ``finalize`` → pytex →
PDF → MinIO/Nextcloud → Versand an die Gremium-Mailingliste. Baut auf der
T-20-Render-Infrastruktur (:mod:`app.modules.pdf`) auf, ohne pytex/Storage/
Nextcloud-/Mail-Code zu duplizieren.
"""
