# Specs

This folder holds the binding rules of STUPA-Workflow. A rule here wins over a skill, a memory
file and a code comment. If code and a spec disagree, the code has a bug or the spec is old.
Tell the owner. Do not change one of them silently.

## Folders

| Folder | Content |
| --- | --- |
| `style/` | How code, tests, migrations, commits and texts must look. |
| `requirements/functional/` | What the application must do: features, states, permissions, results. |
| `requirements/non-functional/` | How well the application must do it: security, privacy, performance, usability, accessibility, compatibility. |

## File format

Every spec file uses the same format. Copy `TEMPLATE.md` to start a new file.

- Write in ASD-STE100 Simplified Technical English.
- One file covers one area. The file name is the area in kebab case.
- The header lists `Kind` (`Style` or `Requirement`), `Status`, `Scope` and `Updated`.
- One rule is one `##` section. The heading is the rule ID and a short title.
- A rule ID is the file prefix and a two-digit number, for example `VOTE-03`. An ID never
  changes and is never used again. A removed rule keeps its heading with the text `Removed.`
- The rule text comes first. Use `must` for an obligation and `must not` for a prohibition.
- `Reason:` gives the cause of the rule. Keep it. The reason is the part that prevents a
  second mistake.
- `Test:` tells how a person or a tool finds a violation. Leave it out if only a review can
  find it.

## Status values

| Status | Meaning |
| --- | --- |
| `Draft` | Written, not yet approved by the owner. Follow it, but ask when it blocks you. |
| `Approved` | The owner approved it. Follow it. |
| `Replaced` | A different file replaces it. The header names that file. |

## Writing rules

- Use short sentences: at most 20 words in an instruction, at most 25 words in a description.
- Use the active voice and the present tense.
- Write one instruction in one sentence.
- Use one word for one thing. Use the UI term in German where the UI shows it, for example
  `Antrag` or `TOP`.
- Write STUPA in capitals. AStA keeps its spelling.
- Do not refer to tickets, pull requests, threads or decision codes. Write the rule itself.
- Do not write history. Write the current rule. Give a date only if the rule depends on it.
- Do not write introductions, summaries, "key points" or filler text.

## How an agent adds or changes a spec

1. Find the file for the area. If there is no file, copy `TEMPLATE.md`.
2. Give a new rule the next free ID of the file.
3. Set `Status: Draft` and `Updated` to the current date.
4. Open a pull request. The owner sets `Approved`.

## Index

### Style

| File | Prefix | Area |
| --- | --- | --- |
| [style/writing.md](style/writing.md) | `WRT` | Texts in the repository: docstrings, docs, commits |
| [style/backend.md](style/backend.md) | `BE` | Python backend code |
| [style/api.md](style/api.md) | `API` | Contract between frontend and backend |
| [style/database.md](style/database.md) | `DB` | Schema, Alembic migrations, time values |
| [style/frontend.md](style/frontend.md) | `FE` | Angular frontend code |
| [style/testing.md](style/testing.md) | `TST` | Tests and coverage gates |
| [style/git.md](style/git.md) | `GIT` | Branches, pull requests, merges, releases |
| [style/functional.md](style/functional.md) | `FUN` | Functional style in backend and frontend |

### Functional requirements

| File | Prefix | Area |
| --- | --- | --- |
| [requirements/functional/accounts.md](requirements/functional/accounts.md) | `ACC` | Login, roles, account merge |
| [requirements/functional/admin.md](requirements/functional/admin.md) | `ADM` | Verwaltung, CRUD, audit revert, texts |
| [requirements/functional/applications.md](requirements/functional/applications.md) | `APP` | Anträge, Aufgaben, forms |
| [requirements/functional/meetings.md](requirements/functional/meetings.md) | `MTG` | Sitzungen, TOPs, attendance, QR guests |
| [requirements/functional/voting.md](requirements/functional/voting.md) | `VOTE` | Votes, elections, polls |
| [requirements/functional/delegations.md](requirements/functional/delegations.md) | `DEL` | Delegations and substitute pools |
| [requirements/functional/protocols.md](requirements/functional/protocols.md) | `PROT` | Protocols and the protocol PDF |
| [requirements/functional/public.md](requirements/functional/public.md) | `PUB` | Public pages |
| [requirements/functional/budget.md](requirements/functional/budget.md) | `BUD` | Kostenstellen, Haushaltsjahre, Buchungen |
| [requirements/functional/files.md](requirements/functional/files.md) | `FILE` | Attachments, file names |
| [requirements/functional/notifications.md](requirements/functional/notifications.md) | `NOT` | Mails and notification settings |
| [requirements/functional/todos-tickets.md](requirements/functional/todos-tickets.md) | `TODO` | Boards, cards, help tickets |
| [requirements/functional/integrations.md](requirements/functional/integrations.md) | `INT` | MCP server and external systems |

### Non-functional requirements

| File | Prefix | Area |
| --- | --- | --- |
| [requirements/non-functional/security.md](requirements/non-functional/security.md) | `SEC` | Access control, downloads, public endpoints |
| [requirements/non-functional/privacy.md](requirements/non-functional/privacy.md) | `PRIV` | Personal data, pseudonymization, erasure |
| [requirements/non-functional/performance.md](requirements/non-functional/performance.md) | `PERF` | Load times, batch reads, loading indicators |
| [requirements/non-functional/layout.md](requirements/non-functional/layout.md) | `LAY` | Page geometry, panes, phone frame |
| [requirements/non-functional/controls.md](requirements/non-functional/controls.md) | `CTL` | Buttons, menus, search, lists, empty states |
| [requirements/non-functional/accessibility.md](requirements/non-functional/accessibility.md) | `A11Y` | Accessibility, languages, themes |
| [requirements/non-functional/compatibility.md](requirements/non-functional/compatibility.md) | `COMP` | Browsers, installed app (PWA), devices |
