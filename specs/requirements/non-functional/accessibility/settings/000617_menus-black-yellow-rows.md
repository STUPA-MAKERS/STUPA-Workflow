---
id: "000617"
title: In very high contrast, every menu is black with yellow rows
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:menusBlackYellowRows"
  - "frontend/src/app/shared/very-high-contrast.styles.spec.ts:menuRows"
implementation:
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
  - frontend/src/app/shared/ui/_very-high-contrast.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# In very high contrast, every menu is black with yellow rows

While "Hoher Kontrast" is on, every menu must have a black fill and a 2 px white edge. This
applies to the 3-dot menu, the filter menu, the help menu, the accessibility menu, the account menu and the list of a
select. Each row that a person can press must have yellow text and a yellow icon. The chosen row
must have a yellow fill and black text. A heading in a menu must be white. A destructive row must
have light red text (`#ff8a8a`).

Reason: Two different menu pictures make a person learn each menu again. In a menu that is all
yellow, the chosen row does not stand out.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts` expects the black fill of the
menu, the yellow text of a row and the yellow fill of the chosen row.
