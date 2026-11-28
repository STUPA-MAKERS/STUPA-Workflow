"""Pretix integration: the connection, the client and the link of an Event to a pretix event.

The module holds the single connection to one organizer of a pretix instance with its two
switches (`pretix_settings`), the read-only HTTP client (§F/integrations/pretix/003089),
the link of an Event to one pretix event with its stored sales (`pretix_event_link`) and
one row per booked order or refund (`pretix_booking`). The module `event_sales` reads the
sales and makes the bookings; this module sits below it.
"""
