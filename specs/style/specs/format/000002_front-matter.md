---
id: "000002"
title: A spec starts with a YAML front matter
kind: style
status: draft
scope:
  - specs/
owner: frederikbeimgraben
updated: 2026-11-05
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
| `scope` | list of strings | The paths in the repository that the rule applies to. |
| `owner` | string | The GitHub login of the person who approves the rule. |
| `updated` | date | The date of the last change, as `YYYY-MM-DD`. |
| `replaced_by` | string | Only with `status: replaced`: the ID of the new rule. |

Do not add other keys. Do not put metadata in the Markdown body.

Reason: Every Markdown tool reads standard front matter, so a tool reads the metadata without a
custom parser. One fixed set of keys keeps
every spec readable by the same tool. The quotes keep the leading zeros, because YAML reads
an unquoted `000024` as a number.

Test: The front matter parses as YAML, has exactly these keys, and `id` is the number in the
file name.
