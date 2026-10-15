"""The tab "Gremien": a read-only view of the gremien of a principal.

The module reads; it never writes. A member sees the own gremien, a holder of the
global permission ``gremium.view_all`` (and the admin role) sees every gremium. Each
gremium has its members, meetings, attendance per member and month, and decisions.
The gate lives in ``access.py``; an unknown or hidden gremium gives 404.
"""
