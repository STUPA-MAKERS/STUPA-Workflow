---
id: "000463"
title: A scope caps every gremium right of a token
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/auth
  - backend/app/modules/livevote/service/permissions.py
---

# A scope caps every gremium right of a token

A gremium permission check must pass `Principal.scope_allows(perm)`. A module must not decide a
right from `principal.roles`.
