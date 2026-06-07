"""Delegation/Vertretung (T-45, R1.5).

Ein Mitglied delegiert eines seiner **eigenen** Rechte (Rolle, optional Stimmrecht)
zeitlich begrenzt an ein anderes Mitglied. Eine Delegation ist ein zeit-validiertes
``role_assignment`` mit gesetztem ``delegated_by`` (Anker), das der RBAC-Resolver
(T-10) im Gültigkeitsfenster automatisch mitzählt; Widerruf wirkt sofort. Jede
Delegation/jeder Widerruf wird auditiert (T-23). Stimmrecht-Delegation steht unter
satzungsrechtlichem Vorbehalt (Q5) und ist per Settings schaltbar.
"""
