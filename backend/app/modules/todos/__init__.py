"""To-dos: kanban boards of a gremium, of one person and of a team.

A gremium board belongs to the members whose gremium role holds ``todo.write``;
``todo.configure`` edits its columns, labels and name. A personal board belongs to
its owner only. A team board belongs to the holders of its global permission (the
board "Plattform" to ``ticket.manage``). A card links to applications, meetings,
agenda items, tickets and other cards; a target that the viewer cannot read shows
without its title. There is no audit entry for to-dos: ``todo_event`` is the
timeline of a card.
"""
