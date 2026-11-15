---
id: "000969"
title: The editor blacks out a known name after it is typed
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation: null
scope:
  - frontend/src/app/features/meetings
  - frontend/vendor/ui-kit/markdown-editor
---

# The editor blacks out a known name after it is typed

The protocol editor must put the blackout marker (000685) around a known name (000970) right
after a keeper types it. A known name is a first name and a last name with whitespace between
them, in any case. The editor must set the marker when the keeper types the first character
after the last name that is no letter, digit or hyphen: a space, a punctuation mark or a line
break. This must work in the formatted view and in the Markdown view. The editor must not set
the marker on a name that already has a marker, that is in a blackout block (000965) or that is
in code. One undo (Ctrl+Z, Cmd+Z on macOS) right after it must remove the marker and keep the
name. A paste must not set a marker.

Reason: A keeper writes names while the meeting runs and forgets the marker. The public
protocol names nobody (000172).

Test: Frontend tests type a known name followed by a space and check the marker, the undo and a
name in a block.
