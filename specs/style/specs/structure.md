---
id: S/specs/structure
title: Spec tree and index
kind: style
status: draft
scope:
  - specs/
owner: frederikbeimgraben
updated: 2026-11-05
---

# Spec tree and index

## S/specs/structure/000009 A spec wins over other guidance

A rule in `specs/` wins over a skill, a memory file and a code comment. If code and a spec
disagree, tell the owner. Do not change the code or the spec silently.

Reason: Only one source can be binding. Otherwise two agents follow two different rules.

## S/specs/structure/000010 The tree sorts by kind, then by area

A spec file must be in one of these kind folders:

| Folder | Kind | Content |
| --- | --- | --- |
| `style/` | `style` | How code, tests, migrations, commits, specs and texts must look. |
| `requirements/functional/` | `functional` | What the application must do. |
| `requirements/non-functional/` | `non-functional` | How well the application must do it: security, privacy, performance, usability, accessibility, compatibility. |

Below the kind folder, one folder is one area, for example `meetings/`. One file covers one
topic of the area.

## S/specs/structure/000011 Names are lower case kebab case

Folder and file names use only `a` to `z`, `0` to `9` and `-`. A file name ends with `.md`.

Reason: The names become part of the rule IDs, where `/` is the separator.

## S/specs/structure/000012 A file belongs to one area and one topic

Put a rule in the file of the topic it controls. If a rule applies to two areas, put it in
the area that owns the code. Do not write the same rule in two files. Refer to the rule ID
instead.

Reason: Two copies of a rule drift apart.

## S/specs/structure/000013 The index lists every file

`specs/README.md` lists every spec file with its `id` and `status`. A pull request that adds,
moves or removes a file updates the index.

Test: Every `.md` file below `style/` and `requirements/` is in the index, and the index
lists no other file.

## S/specs/structure/000014 A change goes through a pull request

1. Find the file for the topic. If there is no file, copy the template.
2. Give a new rule the highest number in `specs/` plus one.
3. Set `status: draft` and set `updated` to the current date.
4. Update the index.
5. Open a pull request. The owner sets `approved`.
