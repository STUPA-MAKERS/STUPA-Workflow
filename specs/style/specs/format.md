---
id: S-specs-format
title: Spec file format
kind: style
status: draft
scope:
  - specs/
owner: frederikbeimgraben
updated: 2026-11-05
---

# Spec file format

## S-specs-format-0001 A new file starts as a copy of the template

Copy `specs/TEMPLATE.md` to start a new spec file.

## S-specs-format-0002 The file starts with a YAML preamble

The file must start with a YAML front matter block between two `---` lines. The block has
these keys, in this order:

| Key | Type | Value |
| --- | --- | --- |
| `id` | string | The ID prefix of the file, for example `F-meetings-voting`. |
| `title` | string | The title of the file. It is the same text as the `#` title. |
| `kind` | enum | `functional`, `non-functional` or `style`. |
| `status` | enum | `draft`, `approved` or `replaced`. |
| `scope` | list of strings | The paths in the repository that the rules apply to. |
| `owner` | string | The GitHub login of the person who approves the file. |
| `updated` | date | The date of the last change, as `YYYY-MM-DD`. |
| `replaced_by` | string | Only with `status: replaced`: the `id` of the new file. |

Do not add other keys. Do not put metadata in the Markdown body.

Reason: A tool reads the preamble without a Markdown parser. One fixed set of keys keeps
every file readable by the same tool.

Test: The preamble parses as YAML, has exactly these keys, and `id` matches the file path.

## S-specs-format-0003 The status shows the approval

| Status | Meaning |
| --- | --- |
| `draft` | Not yet approved by the owner. Follow it, but ask when it blocks you. |
| `approved` | The owner approved it. Follow it. |
| `replaced` | A different file replaces it. `replaced_by` names that file. |

Only the owner sets `approved`.

## S-specs-format-0004 The body has one title and one section per rule

After the preamble comes one `#` title. Then each rule is one `##` section. Do not use other
headings for rules. Do not put text between the title and the first rule.

## S-specs-format-0005 The rule ID contains kind, path and number

The heading of a rule is its ID, one space and a short title. The ID has the form
`(F|NF|S)-<path>-NNNN`:

- `F` is a functional requirement, `NF` a non-functional requirement, `S` a style rule.
- `<path>` is the path of the file below its kind folder, without `.md`, with `-` between the
  parts. `requirements/functional/meetings/voting.md` gives `meetings-voting`.
- `NNNN` is a four-digit number. It counts up in the file and starts at `0001`.

Examples: `F-meetings-voting-0003`, `NF-security-downloads-0001`, `S-backend-python-0012`.

Test: Every rule heading matches `^## (F|NF|S)-[a-z0-9]+(-[a-z0-9]+)*-[0-9]{4} ` and starts
with the `id` of the preamble.

## S-specs-format-0006 A rule number is never used again

A removed rule keeps its heading. Its text is `Removed.` A new rule gets the next free number.

Reason: An old reference must not point to a different rule.

## S-specs-format-0007 A moved file changes its IDs everywhere

The ID contains the path. If a file moves, its `id` and all its rule IDs change. Update every
reference in the same pull request.

## S-specs-format-0008 Labels in a rule are fixed

A rule section uses only these labels, each at the start of its own paragraph:

- `Reason:` the cause of the rule.
- `Test:` how a person or a tool finds a violation.

Other text in a rule section is the rule text. It comes before the labels.
