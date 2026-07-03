"""Webhook dispatch engine.

Builds on the ``webhook``/``webhook_delivery`` tables and handles only sending:
event -> matching webhooks -> ``webhook_delivery`` (pending) + arq job. The worker
(``worker.webhook``) signs HMAC-SHA256, checks the SSRF guard at send time
(DNS rebinding) and writes status/attempts back.
"""
