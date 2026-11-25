"""Teams: named groups of persons. Every Gremium has one inherent team.

The module holds the tables and the membership reads. Boards (``todos``) and Termine
(``calendar``) read the members of a team through ``members``. The routes live in
``team_pages``, because a new team also gets a board.
"""
