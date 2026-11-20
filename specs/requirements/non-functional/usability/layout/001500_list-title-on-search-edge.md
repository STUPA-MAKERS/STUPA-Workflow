---
id: "001500"
title: A wide list column has no visible title and puts its buttons beside the search
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/vendor/ui-kit/src/styles/styles.spec.ts:WideListHead"
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
  - "frontend/src/app/pages/todos/todos.component.spec.ts:TodosComponent"
implementation:
  - frontend/vendor/ui-kit/src/styles/list-detail.scss
  - frontend/vendor/ui-kit/src/lib/page-header/page-header.component.ts
  - frontend/src/app/pages/budget/budget-dashboard.component.html
  - frontend/src/app/pages/budget/budget-dashboard.component.scss
  - frontend/src/app/pages/budget/plan/budget-plan.component.html
  - frontend/src/app/pages/todos/todos.component.html
  - frontend/src/app/pages/todos/todos.component.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A wide list column has no visible title and puts its buttons beside the search

On a wide screen, a list column must not show its title. The title stays in the page for a
screen reader. The buttons of the head of the column must stand at the end of the first line of
the filter bar, after a gap of 12px. That line is the search bar, or the filter chips where the
column has no search bar. The buttons must be as high as the control at the start of that line,
and that control must end before the buttons. In the very high contrast the buttons must be as
high as the yellow of the search bar. The buttons must stay beside the filter bar while the page
scrolls, level with the control at the start of the line, so they keep the same gap to the top
edge of the screen as that control. A head without buttons must take no room.

A list column without a filter bar (no search bar and no filter chips, such as Konto) must keep
its title line on a wide screen, because nothing else names the page there.

On a phone the title line stays as it is.

Haushalt shows no visible title on any screen wider than a phone, also when it shows only an
error or an empty state, and also on a narrow screen where the tree is in a sheet. Its heading
stays in the page for a screen reader. On that narrow screen its buttons stand at the end of the
line of its chips.

This applies to every list column with a pane header (Anträge, Meine Anträge, Sitzungen,
Abstimmungen, Rechnungen, Buchungen, Tickets, Aktivität, Gremien, Aufgaben, Verwaltung, the
tree column of Haushalt and of its plan view, and Boards). On Boards the buttons are as high as the
board picker at the start of the line. The
desktop calendar is no list column; it hides its title too and puts its buttons in its tools row
(001771).

Reason: The title stood 16px right of the search bar and the chips below it, and it repeated the
name of the active item of the navigation. Without it, the column starts with the search, and the
buttons, which act on the list, stand next to the search and the filters.

Test: A unit test of the kit reads `list-detail.scss` and expects the title to be visually
hidden only in a column with a filter bar, the buttons to be absolute at the end of the first filter line with the height of the
search bar, the search bar to end before them, the lower height in the very high contrast, and the
sticky top of the head 8px (`--space-2`, the gap of the sticky bar) below the sticky top of the
filter bar. A screenshot of Aktivität scrolled on a wide screen shows the button level with the chips.
