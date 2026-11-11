---
id: "000645"
title: A model is in the module of its subject
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - backend/app/modules
---

# A model is in the module of its subject

A database model must be in the module that owns its subject. The models `Gremium`,
`GremiumRole`, `GremiumMembership`, `GremiumMembershipMapping` and `GremiumRoleMapping` must be
in `gremien`. The model `ApplicationType` must be in `application_types`. The models `Webhook`
and `WebhookDelivery` must be in `webhooks`. The module `admin` must hold only the models of the
site configuration and of the design variants.

Reason: A module that needs a committee then imports `gremien` and not the whole
administration, which imports almost every other module.

Test: A unit test reads the module of each of these models.
