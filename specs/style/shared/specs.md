# Spec format

Kind: Style
Status: Draft
Scope: specs/
Updated: 2026-11-05

## S-shared-specs-0001 A spec wins over other guidance

A rule in `specs/` wins over a skill, a memory file and a code comment. If code and a spec
disagree, tell the owner. Do not change the code or the spec silently.

Reason: Only one source can be binding. Otherwise two agents follow two different rules.

## S-shared-specs-0002 The tree sorts by kind, then by area

A spec file must be in one of these kind folders:

| Folder | Kind | Content |
| --- | --- | --- |
| `style/` | `Style` | How code, tests, migrations, commits and texts must look. |
| `requirements/functional/` | `Functional` | What the application must do. |
| `requirements/non-functional/` | `Non-functional` | How well the application must do it: security, privacy, performance, usability, accessibility, compatibility. |

Below the kind folder, one folder is one area, for example `meetings/`. One file covers one
topic of the area. Folder and file names are lower case in kebab case.

## S-shared-specs-0003 A new file starts as a copy of the template

Copy `specs/TEMPLATE.md` to start a new spec file.

## S-shared-specs-0004 The header has four fields

The file starts with a `#` title and these four lines:

- `Kind`: `Functional`, `Non-functional` or `Style`.
- `Status`: see S-shared-specs-0005.
- `Scope`: the paths in the repository that the rules apply to.
- `Updated`: the date of the last change, as `YYYY-MM-DD`.

## S-shared-specs-0005 The status shows the approval

| Status | Meaning |
| --- | --- |
| `Draft` | Not yet approved by the owner. Follow it, but ask when it blocks you. |
| `Approved` | The owner approved it. Follow it. |
| `Replaced` | A different file replaces it. The header names that file. |

Only the owner sets `Approved`.

## S-shared-specs-0006 One rule is one section with an ID

One rule is one `##` section. The heading is the rule ID and a short title. Do not use other
heading levels for rules.

## S-shared-specs-0007 The rule ID contains kind, path and number

The rule ID has the form `(F|NF|S)-<path>-NNNN`:

- `F` is a functional requirement, `NF` a non-functional requirement, `S` a style rule.
- `<path>` is the path of the file below its kind folder, without `.md`, with `-` between the
  parts. `requirements/functional/meetings/voting.md` gives `meetings-voting`.
- `NNNN` is a four-digit number. It counts up in the file and starts at `0001`.

Examples: `F-meetings-voting-0003`, `NF-security-downloads-0001`, `S-backend-python-0012`.

Test: Every heading matches
`^## (F|NF|S)-[a-z0-9]+(-[a-z0-9]+)*-[0-9]{4} ` and its path part matches the file path.

## S-shared-specs-0008 A rule number is never used again

A removed rule keeps its heading. Its text is `Removed.` A new rule gets the next free number.

Reason: An old reference must not point to a different rule.

## S-shared-specs-0009 A moved file changes its IDs everywhere

The ID contains the path. If a file moves, all its IDs change. Update every reference in the
same pull request.

## S-shared-specs-0010 A rule has a text, a reason and a test

- The rule text comes first. Use `must` for an obligation and `must not` for a prohibition.
- `Reason:` gives the cause of the rule. Keep it. The reason is the part that prevents a
  second mistake.
- `Test:` tells how a person or a tool finds a violation. Leave it out if only a review can
  find it.

## S-shared-specs-0011 Specs are written in ASD-STE100

- Use short sentences: at most 20 words in an instruction, at most 25 words in a description.
- Use the active voice and the present tense.
- Write one instruction in one sentence.
- Use one word for one thing. Use the German UI term where the UI shows it, for example
  `Antrag` or `TOP`.
- Write STUPA in capitals. AStA keeps its spelling.

## S-shared-specs-0012 A spec contains only rules

Do not write introductions, summaries, "key points" or filler text. Do not write history.
Write the current rule. Give a date only if the rule depends on it. Do not refer to tickets,
pull requests, threads or decision codes. Write the rule itself.

Reason: A reader must find the rule, not the story of the rule.

## S-shared-specs-0013 A change goes through a pull request

1. Find the file for the topic. If there is no file, copy the template.
2. Give a new rule the next free number of the file.
3. Set `Status: Draft` and set `Updated` to the current date.
4. Add a new file to the index in `specs/README.md`.
5. Open a pull request. The owner sets `Approved`.
