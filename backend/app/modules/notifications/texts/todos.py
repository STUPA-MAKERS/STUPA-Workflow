"""Builtin texts of the to-do mails.

The mail catalogue reads them for the template editor. The sender is in
`todos.mails` and uses the same objects as its fallback.
"""

from __future__ import annotations

TODO_ASSIGNED_KEY = "todo_assigned"
TODO_MENTIONED_KEY = "todo_mentioned"
TODO_DUE_KEY = "todo_due"

TODO_ASSIGNED_SUBJECT: dict[str, str] = {
    "de": "Neues To-Do für Sie: {{ cardTitle }}",
    "en": "New to-do for you: {{ cardTitle }}",
}
TODO_ASSIGNED_BODY: dict[str, str] = {
    "de": "Hallo,\n\n{{ actor }} hat Ihnen das To-Do „{{ cardTitle }}“ im Board "
    "„{{ boardName }}“ zugewiesen.\n",
    "en": 'Hello,\n\n{{ actor }} assigned the to-do "{{ cardTitle }}" on the board '
    '"{{ boardName }}" to you.\n',
}
TODO_ASSIGNED_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum To-Do (ohne den Platzhalter hängt die Mail ihn an)",
    "cardTitle": "Titel des To-Dos",
    "boardName": "Name des Boards",
    "actor": "Name der Person, die zugewiesen hat",
}

TODO_MENTIONED_SUBJECT: dict[str, str] = {
    "de": "Sie wurden erwähnt: {{ cardTitle }}",
    "en": "You were mentioned: {{ cardTitle }}",
}
TODO_MENTIONED_BODY: dict[str, str] = {
    "de": "Hallo,\n\n{{ actor }} hat Sie im To-Do „{{ cardTitle }}“ (Board "
    "„{{ boardName }}“) erwähnt:\n\n{{ excerpt }}\n",
    "en": 'Hello,\n\n{{ actor }} mentioned you on the to-do "{{ cardTitle }}" (board '
    '"{{ boardName }}"):\n\n{{ excerpt }}\n',
}
TODO_MENTIONED_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum To-Do (ohne den Platzhalter hängt die Mail ihn an)",
    "cardTitle": "Titel des To-Dos",
    "boardName": "Name des Boards",
    "actor": "Name der Person, die erwähnt hat",
    "excerpt": "Anfang des Kommentars",
}

TODO_DUE_SUBJECT: dict[str, str] = {
    "de": "Morgen fällig: {{ cardTitle }}",
    "en": "Due tomorrow: {{ cardTitle }}",
}
TODO_DUE_BODY: dict[str, str] = {
    "de": "Hallo,\n\ndas To-Do „{{ cardTitle }}“ im Board „{{ boardName }}“ ist am "
    "{{ dueDate }} fällig.\n",
    "en": 'Hello,\n\nthe to-do "{{ cardTitle }}" on the board "{{ boardName }}" is due on '
    "{{ dueDate }}.\n",
}
TODO_DUE_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum To-Do (ohne den Platzhalter hängt die Mail ihn an)",
    "cardTitle": "Titel des To-Dos",
    "boardName": "Name des Boards",
    "dueDate": "Fälligkeitsdatum (JJJJ-MM-TT)",
}
