---
id: "000884"
title: An Antrag on the agenda is an Anlage of the protocol
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
implementation:
  - backend/app/modules/protocol
  - backend/app/modules/livevote
scope:
  - backend/app/modules/protocol
  - backend/app/modules/livevote
  - backend/app/modules/applications
  - typst
---

# An Antrag on the agenda is an Anlage of the protocol

If a TOP of the Sitzung treats an Antrag, the protocol PDF must append the Antrag PDF
(000881) as an Anlage. The Anlage must follow the rules of an embedded PDF: the numbers
(000864), the watermark (000865), the limits (000868) and the public variant (000867). The
TOP must print `Anlage <N>: Antrag <Titel> (Seite <P>)` with a link below its heading
(000866). The Anlage must not show the decision, because the protocol holds the vote result.

Reason: The protocol must show what the Sitzung decided on, without a second document.

Test: Unit test of the render input: a Sitzung with one Antrag TOP gives one Anlage and the
reference line below the TOP heading.
