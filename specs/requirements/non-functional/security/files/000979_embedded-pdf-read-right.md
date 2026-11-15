---
id: "000979"
title: An embedded PDF needs the read right of its Sitzung
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - backend/app/modules/media/router.py
  - backend/app/modules/media/service.py
  - backend/app/modules/protocol/documents_router.py
scope:
  - backend/app/modules/media
  - backend/app/modules/protocol
---

# An embedded PDF needs the read right of its Sitzung

The server must store the Sitzung of each embedded PDF at the upload. `GET
/api/media/documents/{id}` and its info route must answer only a person who can read that
Sitzung, and 404 for each other session. The public route of a public protocol stays as it is
(F/meetings/protocols/000867). The images of the Markdown texts stay readable for each session
(NF/security/files/000344).

Reason: A PDF of a protocol can hold the papers of a non-public item. The id alone is not a
protection, because a text, a mail or a browser history can show it to a person without the
read right, also to an applicant.

Test: A backend unit test reads a PDF with a session that cannot read the Sitzung and with an
applicant session, and finds 404 for both.
