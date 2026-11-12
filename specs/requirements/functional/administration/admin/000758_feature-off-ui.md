---
id: "000758"
title: A feature that is off does not show in the UI
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - frontend/src/app
  - backend/app/modules/search
  - backend/app/modules/site_config
---

# A feature that is off does not show in the UI

While a feature is off, the UI must not show its navigation entry, its pages, its admin pages, its
entries in the command palette and its notification settings. A route of the feature must show the
page `Seite nicht gefunden`. The global search must not return hits of the feature.

Another page must leave out the parts that belong to the feature and must not show an empty
section or a dead link in their place. Examples: the Kalender omits the meetings while `Sitzungen`
is off and the due cards while `Boards` is off. The Antrag omits the Kostenstelle while `Budget` is
off. The start page omits the tiles of a feature that is off.

The public site configuration must name the state of each feature, so that the public pages follow
the switches without a session.

Reason: A person must not find a way into a part that the student body does not use.

Test: A frontend unit test switches each feature off in the site configuration and finds no
navigation entry of it. A route test opens a route of the feature and gets the not-found page. A
backend unit test of the search finds no hit of a feature that is off.
