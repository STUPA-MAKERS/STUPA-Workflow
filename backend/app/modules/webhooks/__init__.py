"""Webhook dispatch engine.

This module builds on the `webhook` and `webhook_delivery` tables. It covers only the
send path. An event selects the matching webhooks. Each match gets one
`webhook_delivery` row in state `pending` plus one arq job. The worker
(`worker.webhook`) signs the body with HMAC-SHA256. It runs the SSRF guard at send time
to block DNS rebinding. It then writes the status and the attempt count back.
"""
