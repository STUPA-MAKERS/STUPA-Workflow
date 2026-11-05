---
id: "000002"
title: A spec starts with a YAML front matter
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - specs/
---

# A spec starts with a YAML front matter

The file must start with a standard YAML front matter block. The block is the first thing in
the file and stands between two `---` lines. The block has
these keys, in this order:

| Key | Type | Value |
| --- | --- | --- |
| `id` | string | The six-digit number of the rule in double quotes, for example `"000024"`. |
| `title` | string | The title of the rule. It is the same text as the `#` title. |
| `kind` | enum | `functional`, `non-functional` or `style`. |
| `status` | enum | `draft`, `approved`, `replaced` or `removed`. |
| `owner` | string | The GitHub login of the person who approves the rule. |
| `updated` | date | The date of the last change, as `YYYY-MM-DD`. |
| `replaced_by` | string | Only with `status: replaced`: the ID of the new rule. |
| `tests` | list of strings | Optional: the unit tests that check the rule, as `"<path>:<function>"`. |
| `scope` | list of strings | The paths in the repository that the rule applies to. |

Do not add other keys. Do not put metadata in the Markdown body. `scope` is the last key.

A `tests` entry has the path from the repository root, a colon and the test function, for
example `"backend/tests/unit/test_voting.py:test_secret_is_forced"`. For a method of a test
class, write `Class.method` after the colon.

Reason: Every Markdown tool reads standard front matter, so a tool reads the metadata without a
custom parser. One fixed set of keys keeps
every spec readable by the same tool. The quotes keep the leading zeros, because YAML reads
an unquoted `000024` as a number.

Test: The front matter parses as YAML, has exactly these keys, and `id` is the number in the
file name.
