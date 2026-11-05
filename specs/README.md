# Specs

The binding rules of STUPA-Workflow. The format of every file is a spec itself:
[style/shared/specs.md](style/shared/specs.md). Copy [TEMPLATE.md](TEMPLATE.md) to start a
new file.

## Tree

```
specs/
  style/
    shared/          specs, writing, api, testing, git
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

## Index

| File | ID prefix | Status |
| --- | --- | --- |
| [style/shared/specs.md](style/shared/specs.md) | `S-shared-specs` | Draft |
| [requirements/functional/meetings/voting.md](requirements/functional/meetings/voting.md) | `F-meetings-voting` | Draft |
