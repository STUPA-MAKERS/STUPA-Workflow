---
id: "000606"
title: Very high contrast includes the other display settings
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - frontend/src/app/features/help
  - frontend/vendor/ui-kit
---

# Very high contrast includes the other display settings

While "Sehr hoher Kontrast" is on, the settings "Mehr Kontrast" (000595), "Weniger Bewegung"
(000219), "Weniger Transparenz" (000596) and "Eingabefelder hervorheben" (000598) must be in
effect, and "Dunkles Design" (000218) must be in effect too, because 000605 has a black
background. Their switches must show on and must be disabled. The choices that the person made
for these switches before must stay stored, and they must apply again when the person turns
"Sehr hoher Kontrast" off. "Sehr hoher Kontrast" has no system setting, so it is off until the
person turns it on. "Systemeinstellungen verwenden" (000594) turns it off too.

Reason: One switch must give a person every visual aid at once, and a switch that has no effect
must not look as if it had one.

Test: `frontend/vendor/ui-kit/src/lib/display/display-settings.service.spec.ts`.
