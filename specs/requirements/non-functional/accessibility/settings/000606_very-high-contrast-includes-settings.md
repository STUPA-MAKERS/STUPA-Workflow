---
id: "000606"
title: Very high contrast includes the other display settings
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/lib/display/display-settings.service.spec.ts:DisplaySettingsService"
  - "frontend/vendor/ui-kit/src/lib/theme/theme.service.spec.ts:ThemeService"
  - "frontend/src/app/features/help/help-menu/help-menu.component.spec.ts:HelpMenuComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/display/display-settings.service.ts
  - frontend/vendor/ui-kit/src/lib/theme/theme.service.ts
  - frontend/src/app/features/help/help-menu
scope:
  - frontend/src/app/features/help
  - frontend/vendor/ui-kit
---

# Very high contrast includes the other display settings

While "Hoher Kontrast" is on, the settings "Mehr Kontrast" (000595), "Weniger Bewegung"
(000219) and "Weniger Transparenz" (000596) and the highlighted fields (000598) must be in
effect, and "Dunkles Design" (000218) must be in effect too, because 000605 has a black
background. The switches of these settings must show on and must be disabled. The choices that the person made
for these switches before must stay stored, and they must apply again when the person turns
"Hoher Kontrast" off. "Hoher Kontrast" has no system setting, so it is off until the
person turns it on. "Systemeinstellungen verwenden" (000594) turns it off too.

Reason: One switch must give a person every visual aid at once, and a switch that has no effect
must not look as if it had one.

Test: `frontend/vendor/ui-kit/src/lib/display/display-settings.service.spec.ts`.
