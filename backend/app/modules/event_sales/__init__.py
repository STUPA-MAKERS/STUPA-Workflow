"""The sales of the Events from pretix and Mollie: the reads, the bookings and the routes.

The module reads the sales of the linked pretix events and the money data of Mollie, books
them on the cost centres of the Events and of the Mollie connection, and serves the admin
pages, the link of an Event, the section `Verkauf` and the action `Daten abrufen`. It sits
on the top layer, because it reads the Events and writes bookings and links.
"""
