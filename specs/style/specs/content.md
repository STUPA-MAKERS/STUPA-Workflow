---
id: S/specs/content
title: Spec content and language
kind: style
status: draft
scope:
  - specs/
owner: frederikbeimgraben
updated: 2026-11-05
---

# Spec content and language

## S/specs/content/000015 A spec contains only rules

Write rules. Do not write introductions, summaries, overviews, "key points" or filler text.

Reason: A reader must find the rule at once.

## S/specs/content/000016 One rule controls one thing

One rule section controls one behavior or one property. If a rule needs "and also", make two
rules.

Reason: A reference to a rule ID must point to one thing that is true or false.

## S/specs/content/000017 A rule can be examined

Write a rule so that a person or a test can decide if the code obeys it. Use numbers, names,
states, status codes and paths. Do not use words such as "fast", "nice" or "intuitive"
without a measurable value.

## S/specs/content/000018 The rule text uses must and must not

Use `must` for an obligation and `must not` for a prohibition. Use the present tense for a
fact that the rule depends on.

## S/specs/content/000019 A rule gives its reason

Add `Reason:` when the cause is known. Keep the cause, also when you make the rule shorter.

Reason: The cause is the part that prevents the next mistake.

## S/specs/content/000020 A rule names its test

Add `Test:` with the test file, lint rule or check that finds a violation. Leave it out if
only a review can find a violation.

## S/specs/content/000021 A spec states the current rule

Do not write history or stories. Give a date only if the rule depends on it. Do not refer to
tickets, pull requests, threads or decision codes. Write the rule itself.

Reason: A history explains the past. The reader needs the rule that is in force now.

## S/specs/content/000022 A spec is written in ASD-STE100

- Use at most 20 words in an instruction and at most 25 words in a description.
- Use the active voice.
- Write one instruction in one sentence.
- Use one word for one thing.
- Do not use "-ing" forms as nouns or adjectives where a different form is possible.

## S/specs/content/000023 Product terms stay as the UI shows them

Use the German UI term where the UI shows it, for example `Antrag`, `TOP` or `Kostenstelle`.
Write STUPA in capitals. AStA keeps its spelling.

Reason: The reader must find the term in the application.
