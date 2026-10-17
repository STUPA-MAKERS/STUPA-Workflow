"""Tickets: problem reports, questions and ideas from the help menu.

A person reports a ticket with ``POST /tickets``: with a session, or without one
behind ALTCHA, rate limit and body cap while ``tickets.publicEnabled`` is on. The
report is one-way. The reporter gets the ticket number and a confirmation mail and
never reads the ticket again. Holders of ``ticket.manage`` work on the tickets:
status, assignee, kind, internal notes and a timeline of events.
"""
