# Specs

The binding rules of STUPA-Workflow. One file holds one rule. The rules for specs are in
[style/specs/](style/specs/). Copy [TEMPLATE.md](TEMPLATE.md) to start a new rule.

## Tree

```
specs/
  style/
    specs/        format, structure, content
    shared/       writing, api, testing, git
    backend/      python, database, functional
    frontend/     angular, functional
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

The second level is the area, the third level is the topic. A topic folder holds the rule
files, for example `requirements/functional/meetings/voting/000024_every-vote-is-secret.md`.

## Index

| ID | Title | Status |
| --- | --- | --- |
| [F/meetings/voting/000024](requirements/functional/meetings/voting/000024_every-vote-is-secret.md) | Every vote is secret | draft |
| [F/meetings/voting/000025](requirements/functional/meetings/voting/000025_ballot-does-not-change.md) | A cast ballot does not change | draft |
| [F/meetings/voting/000026](requirements/functional/meetings/voting/000026_tie-rejects-motion.md) | A tie rejects a motion | draft |
| [F/meetings/voting/000027](requirements/functional/meetings/voting/000027_election-tie-by-lot.md) | A tie in an election is decided by lot | draft |
| [F/meetings/voting/000028](requirements/functional/meetings/voting/000028_protokollant-opens-and-closes.md) | Only the protokollant opens and closes a meeting vote | draft |
| [F/meetings/voting/000029](requirements/functional/meetings/voting/000029_delete-only-draft-or-cancelled.md) | A vote can be deleted only as draft or cancelled | draft |
| [F/meetings/voting/000030](requirements/functional/meetings/voting/000030_vote-in-gremium-of-antrag.md) | A vote on an Antrag belongs to the Gremium of the Antrag | draft |
| [F/meetings/voting/000031](requirements/functional/meetings/voting/000031_poll-shows-only-counts.md) | A poll shows only counts | draft |
| [S/specs/content/000015](style/specs/content/000015_only-the-rule.md) | A spec contains only the rule | draft |
| [S/specs/content/000016](style/specs/content/000016_one-thing.md) | One rule controls one thing | draft |
| [S/specs/content/000017](style/specs/content/000017_examinable.md) | A rule can be examined | draft |
| [S/specs/content/000018](style/specs/content/000018_must-and-must-not.md) | The rule text uses must and must not | draft |
| [S/specs/content/000019](style/specs/content/000019_reason.md) | A rule gives its reason | draft |
| [S/specs/content/000020](style/specs/content/000020_test.md) | A rule names its test | draft |
| [S/specs/content/000021](style/specs/content/000021_current-rule.md) | A spec states the current rule | draft |
| [S/specs/content/000022](style/specs/content/000022_ste.md) | A spec is written in ASD-STE100 | draft |
| [S/specs/content/000023](style/specs/content/000023_product-terms.md) | Product terms stay as the UI shows them | draft |
| [S/specs/format/000001](style/specs/format/000001_copy-the-template.md) | A new spec starts as a copy of the template | draft |
| [S/specs/format/000002](style/specs/format/000002_yaml-preamble.md) | A spec starts with a YAML preamble | draft |
| [S/specs/format/000003](style/specs/format/000003_status.md) | The status shows the approval | draft |
| [S/specs/format/000004](style/specs/format/000004_one-rule-per-file.md) | One file holds one rule | draft |
| [S/specs/format/000005](style/specs/format/000005_rule-id.md) | The rule ID has kind, path and number | draft |
| [S/specs/format/000006](style/specs/format/000006_unique-number.md) | The number is the identity of a rule | draft |
| [S/specs/format/000007](style/specs/format/000007_moved-rule.md) | A moved rule keeps its number | draft |
| [S/specs/format/000008](style/specs/format/000008_labels.md) | Labels in a rule are fixed | draft |
| [S/specs/format/000032](style/specs/format/000032_section-sign-reference.md) | Code refers to a rule with the § sign | draft |
| [S/specs/format/000033](style/specs/format/000033_file-name.md) | The file name is number and name | draft |
| [S/specs/structure/000009](style/specs/structure/000009_precedence.md) | A spec wins over other guidance | draft |
| [S/specs/structure/000010](style/specs/structure/000010_tree.md) | The tree sorts by kind, then by area and topic | draft |
| [S/specs/structure/000011](style/specs/structure/000011_folder-names.md) | Folder names are lower case kebab case | draft |
| [S/specs/structure/000012](style/specs/structure/000012_one-place.md) | A rule is written in one place | draft |
| [S/specs/structure/000013](style/specs/structure/000013_index.md) | The index lists every rule | draft |
| [S/specs/structure/000014](style/specs/structure/000014_change-process.md) | A change goes through a pull request | draft |
