"""Mollie integration: the connection, the read-only client and the stored money data.

The module holds the single connection to one Mollie organization (`mollie_settings`),
the read-only HTTP client (§F/integrations/mollie/003099), the payments, refunds,
chargebacks and settlements as the worker read them (only the money values,
§F/integrations/mollie/003098) and one row per booked payment, refund, chargeback and
settlement (`mollie_booking`). The module `event_sales` reads and books; this module sits
below it.
"""
