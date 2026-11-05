# Specs

This folder holds the binding rules of STUPA-Workflow. A rule here wins over a skill, a memory
file and a code comment. If code and a spec disagree, the code has a bug or the spec is old.
Tell the owner. Do not change one of them silently.

## Folders

The tree sorts first by kind, then by area.

```
specs/
  style/
    shared/          writing, api, testing, git
    backend/         python, database, functional
    frontend/        angular, functional
  requirements/
    functional/
      meetings/        meetings, voting, delegations, protocols
      applications/    applications, forms
      finance/         budget, invoices
      collaboration/   todos, tickets, notifications
      administration/  accounts, admin, files
      public/          public-pages
      integrations/    mcp
    non-functional/
      security/  privacy/  performance/  usability/  accessibility/  compatibility/
```

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

The index lists every file with its ID prefix. It follows when the ID format is decided.
