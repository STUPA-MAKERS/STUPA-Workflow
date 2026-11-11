---
id: "000650"
title: The meeting core is in the module meetings
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules
  - backend/pyproject.toml
---

# The meeting core is in the module meetings

The module `meetings` is in layer 3. It must hold the part of a meeting that the modules
`voting`, `flow` and `applications` read:

1. The models of the meeting, the agenda item, the attendance and the guest.
2. The models `Protocol` and `ProtocolVoteRef`, because the meeting rules read the status of
   the protocol and `voting` deletes the references of a vote. This is an exception to 000645.
3. The order and the title of the agenda items, and the add of an Antrag to an agenda.
4. The rules that say who can read a meeting and who can run its votes, the count of the
   eligible voters, and the mark of a person as present at a ballot.
5. The publisher that sends an event to the channel of a meeting.

The module `livevote` must keep the live part: the routes, the WebSocket connections, the
lifecycle of a meeting, the live vote, the guests, and the handover of the minute taker. It
imports `meetings`.

The module `delegations` is in layer 3, because the ballot of `voting` asks it who can vote
for whom. The model of the substitute pool and the reads of the pool are in `gremien`, because
the pool belongs to a Gremium and gives its read scope.

The modules `voting`, `flow` and `applications` must not import `livevote` or `protocol`. The
move must change no URL, no response and no database table.

Reason: A vote, a flow action and an Antrag need the meeting they belong to. When they read it
from `livevote`, the three modules import the module that imports them, and the live part
cannot change alone.

Test: A unit test reads the import contract in `backend/pyproject.toml` and finds no exception
that starts with `app.modules.voting`, `app.modules.flow` or `app.modules.applications`.
