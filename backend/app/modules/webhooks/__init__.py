"""Webhook-Dispatch-Motor (T-19, security.md §5 / flows §8).

Baut auf den von T-24 angelegten Tabellen ``webhook``/``webhook_delivery`` auf und
liefert ausschließlich den **Versand**: Event → passende Webhooks → ``webhook_delivery``
(pending) + arq-Job. Der Worker (``worker.webhook``) signiert HMAC-SHA256, prüft den
SSRF-Guard zur **Sende-Zeit** (DNS-Rebinding) und schreibt Status/Versuche zurück.
"""
