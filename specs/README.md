# Specs

The binding rules of STUPA-Workflow. One file holds one rule. The rules for specs are in
[style/specs/](style/specs/). Copy [TEMPLATE.md](TEMPLATE.md) to start a new rule.

## Tree

```
specs/
  style/
    backend/         database, functional, python
    frontend/        angular, functional
    shared/          agents, api, functional, git, testing, writing
    specs/           content, format, structure
  requirements/
    functional/
      administration/  accounts, admin, audit, backups, files, translations
      applications/    applications, flow, forms
      collaboration/   notifications, search, tickets, todos
      finance/         budget, invoices
      integrations/    external, mcp, webhooks
      meetings/        calendar, delegations, meetings, protocols, voting
      public/          public-pages
    non-functional/
      accessibility/   interaction, language
      compatibility/   deploy, pwa
      performance/     loading
      privacy/         personal-data
      security/        access, files, integrity, network
      usability/       controls, layout
```

The second level is the area, the third level is the topic. A topic folder holds the rule
files, for example `requirements/functional/meetings/voting/000024_every-vote-is-secret.md`.

## Index

| ID | Title | Status |
| --- | --- | --- |
| [F/administration/accounts/000154](requirements/functional/administration/accounts/000154_roles-from-oidc.md) | Memberships and roles come from OIDC groups | draft |
| [F/administration/accounts/000155](requirements/functional/administration/accounts/000155_admin-role.md) | The admin role has every permission | draft |
| [F/administration/accounts/000156](requirements/functional/administration/accounts/000156_login-lifetime.md) | Login lifetime is an admin setting | draft |
| [F/administration/accounts/000157](requirements/functional/administration/accounts/000157_account-merge.md) | An admin merges two accounts | draft |
| [F/administration/accounts/000158](requirements/functional/administration/accounts/000158_revoke-without-login.md) | Role assignments can be revoked without a login | draft |
| [F/administration/accounts/000159](requirements/functional/administration/accounts/000159_ohne-namen.md) | An account without a name shows Ohne Namen | draft |
| [F/administration/accounts/000160](requirements/functional/administration/accounts/000160_membership-sync.md) | Membership sync deletes without history | draft |
| [F/administration/accounts/000265](requirements/functional/administration/accounts/000265_refused-logins.md) | A deactivated or merged account cannot log in | draft |
| [F/administration/accounts/000266](requirements/functional/administration/accounts/000266_member-role.md) | Every user holds the member role | draft |
| [F/administration/accounts/000267](requirements/functional/administration/accounts/000267_gremium-rights.md) | Gremium rights come only from the membership | draft |
| [F/administration/accounts/000268](requirements/functional/administration/accounts/000268_magic-link-lifetime.md) | A magic link is valid until an event ends it | draft |
| [F/administration/accounts/000269](requirements/functional/administration/accounts/000269_applicant-edit.md) | An applicant session can edit | draft |
| [F/administration/accounts/000270](requirements/functional/administration/accounts/000270_return-to.md) | The login returns to the page | draft |
| [F/administration/accounts/000271](requirements/functional/administration/accounts/000271_sso-logout.md) | The logout ends the SSO session | draft |
| [F/administration/accounts/000334](requirements/functional/administration/accounts/000334_avatar-proxy.md) | Avatars come through the platform | draft |
| [F/administration/accounts/000422](requirements/functional/administration/accounts/000422_erase-account-action.md) | An account can be erased from the user list | draft |
| [F/administration/admin/000161](requirements/functional/administration/admin/000161_crud-complete.md) | Every entity has create, read, update and delete | draft |
| [F/administration/admin/000162](requirements/functional/administration/admin/000162_cd-variant-delete.md) | A CD variant in use is not deleted | draft |
| [F/administration/admin/000163](requirements/functional/administration/admin/000163_audit-revert.md) | The audit revert reverses effects, never entries | draft |
| [F/administration/admin/000164](requirements/functional/administration/admin/000164_translations.md) | Admins edit UI texts and add languages | draft |
| [F/administration/admin/000165](requirements/functional/administration/admin/000165_admin-start.md) | Verwaltung starts with an empty state | draft |
| [F/administration/admin/000166](requirements/functional/administration/admin/000166_dsgvo-delete.md) | A privacy erasure starts from Benutzer | draft |
| [F/administration/admin/000368](requirements/functional/administration/admin/000368_role-keys.md) | Role keys are fixed lower case | draft |
| [F/administration/admin/000369](requirements/functional/administration/admin/000369_page-permissions.md) | Each admin page has its own permission | draft |
| [F/administration/admin/000370](requirements/functional/administration/admin/000370_self-lockout.md) | An admin cannot deactivate the own account | draft |
| [F/administration/admin/000371](requirements/functional/administration/admin/000371_repin-by-key.md) | A flow save moves Anträge by state key | draft |
| [F/administration/admin/000372](requirements/functional/administration/admin/000372_branding-checks.md) | Branding logos are checked by their bytes | draft |
| [F/administration/admin/000373](requirements/functional/administration/admin/000373_cd-logo-download.md) | A CD logo is served only as a download | draft |
| [F/administration/admin/000383](requirements/functional/administration/admin/000383_revert-forward.md) | A config revert goes forward | draft |
| [F/administration/admin/000384](requirements/functional/administration/admin/000384_snapshot-no-pii.md) | A config snapshot holds no personal data | draft |
| [F/administration/admin/000405](requirements/functional/administration/admin/000405_revert-permissions.md) | A revert needs the right of the original change | draft |
| [F/administration/admin/000421](requirements/functional/administration/admin/000421_dashboard.md) | The start page is a work list with a side bar | draft |
| [F/administration/audit/000290](requirements/functional/administration/audit/000290_no-pii-in-audit.md) | An audit entry holds no personal data | draft |
| [F/administration/audit/000291](requirements/functional/administration/audit/000291_record-in-tx.md) | An audit entry is written in the same transaction | draft |
| [F/administration/audit/000292](requirements/functional/administration/audit/000292_chain-check.md) | The audit chain is checked every night | draft |
| [F/administration/audit/000293](requirements/functional/administration/audit/000293_three-permissions.md) | Read, check and revert are separate permissions | draft |
| [F/administration/audit/000294](requirements/functional/administration/audit/000294_resolved-names.md) | The audit log shows names | draft |
| [F/administration/audit/000295](requirements/functional/administration/audit/000295_canonical-hash.md) | The hash input is canonical | draft |
| [F/administration/backups/000300](requirements/functional/administration/backups/000300_web-ui.md) | Backups run from the web UI | draft |
| [F/administration/backups/000301](requirements/functional/administration/backups/000301_archive-content.md) | A backup holds the database and the attachments, encrypted | draft |
| [F/administration/backups/000302](requirements/functional/administration/backups/000302_pre-restore.md) | A restore first saves the current state | draft |
| [F/administration/backups/000303](requirements/functional/administration/backups/000303_confirm-restore.md) | A restore needs the word RESTORE | draft |
| [F/administration/backups/000304](requirements/functional/administration/backups/000304_no-token-backup.md) | No agent token reaches a backup | draft |
| [F/administration/files/000167](requirements/functional/administration/files/000167_ascii-names.md) | Storage names replace non-ASCII characters | draft |
| [F/administration/files/000168](requirements/functional/administration/files/000168_confirm-delete.md) | Every attachment delete is confirmed | draft |
| [F/administration/files/000169](requirements/functional/administration/files/000169_drop-files.md) | Attachments can be dropped | draft |
| [F/administration/files/000339](requirements/functional/administration/files/000339_size-limit.md) | An attachment is at most 10 MiB | draft |
| [F/administration/files/000340](requirements/functional/administration/files/000340_quarantine.md) | An unscanned file is not served | draft |
| [F/administration/files/000341](requirements/functional/administration/files/000341_file-access.md) | File access follows the access to the Antrag | draft |
| [F/administration/files/000342](requirements/functional/administration/files/000342_drafts.md) | Wizard uploads are drafts | draft |
| [F/administration/files/000343](requirements/functional/administration/files/000343_display-name.md) | A file name is cleaned | draft |
| [F/administration/files/000344](requirements/functional/administration/files/000344_image-reencode.md) | Markdown images are re-encoded | draft |
| [F/administration/translations/000336](requirements/functional/administration/translations/000336_catalog-source.md) | The frontend catalog is the source of UI texts | draft |
| [F/administration/translations/000337](requirements/functional/administration/translations/000337_language-lifecycle.md) | A new language starts inactive | draft |
| [F/administration/translations/000338](requirements/functional/administration/translations/000338_extra-language-scope.md) | Extra languages cover only UI texts | draft |
| [F/applications/applications/000121](requirements/functional/applications/applications/000121_apply-buttons.md) | The apply button is Antrag anlegen | draft |
| [F/applications/applications/000122](requirements/functional/applications/applications/000122_on-behalf-capture.md) | An Antrag can be captured on behalf of a person | draft |
| [F/applications/applications/000123](requirements/functional/applications/applications/000123_received-on.md) | The received date is at most 365 days back | draft |
| [F/applications/applications/000124](requirements/functional/applications/applications/000124_match-by-email.md) | A guest e-mail of an active account becomes that account | draft |
| [F/applications/applications/000125](requirements/functional/applications/applications/000125_unconfirmed-guest.md) | An unconfirmed guest Antrag rests | draft |
| [F/applications/applications/000126](requirements/functional/applications/applications/000126_transition-notes.md) | Transition notes are visible to the applicant | draft |
| [F/applications/applications/000127](requirements/functional/applications/applications/000127_applicant-view.md) | The applicant sees the Gremium as actor | draft |
| [F/applications/applications/000128](requirements/functional/applications/applications/000128_timeline-vote-link.md) | The timeline links the deciding vote | draft |
| [F/applications/applications/000129](requirements/functional/applications/applications/000129_keep-open-after-transition.md) | An Antrag stays open after a transition in Aufgaben | draft |
| [F/applications/applications/000130](requirements/functional/applications/applications/000130_pii-fields.md) | PII fields need application.read | draft |
| [F/applications/applications/000131](requirements/functional/applications/applications/000131_comments-button.md) | Comments open from a header button | draft |
| [F/applications/applications/000132](requirements/functional/applications/applications/000132_approval-with-deviation.md) | An approval can deviate | draft |
| [F/applications/applications/000374](requirements/functional/applications/applications/000374_pinned-validation.md) | Antrag data is checked against its pinned form | draft |
| [F/applications/applications/000375](requirements/functional/applications/applications/000375_versioned-edit.md) | An edit is versioned and audited without values | draft |
| [F/applications/applications/000376](requirements/functional/applications/applications/000376_anonymize-all.md) | An anonymization removes every copy of personal data | draft |
| [F/applications/applications/000377](requirements/functional/applications/applications/000377_state-since.md) | The time in a state is shown | draft |
| [F/applications/flow/000227](requirements/functional/applications/flow/000227_one-active-flow.md) | There is one active flow | draft |
| [F/applications/flow/000228](requirements/functional/applications/flow/000228_state-kinds.md) | A state is normal or a vote state | draft |
| [F/applications/flow/000229](requirements/functional/applications/flow/000229_guard-whitelist.md) | Guards and actions come from a whitelist | draft |
| [F/applications/flow/000230](requirements/functional/applications/flow/000230_actor-gates-manual.md) | Actor gates apply only to manual transitions | draft |
| [F/applications/flow/000231](requirements/functional/applications/flow/000231_compare-fails-closed.md) | A guard on a field fails closed | draft |
| [F/applications/flow/000232](requirements/functional/applications/flow/000232_optimistic-lock.md) | A transition fires only from the current state | draft |
| [F/applications/flow/000233](requirements/functional/applications/flow/000233_branch-by-vote-only.md) | Only the vote result fires a vote branch | draft |
| [F/applications/flow/000234](requirements/functional/applications/flow/000234_no-auto-exit-from-vote.md) | No automatic exit from a vote state | draft |
| [F/applications/flow/000235](requirements/functional/applications/flow/000235_leave-cancels-votes.md) | Leaving a vote state cancels its votes | draft |
| [F/applications/flow/000236](requirements/functional/applications/flow/000236_status-event.md) | A status change is recorded | draft |
| [F/applications/flow/000237](requirements/functional/applications/flow/000237_actions-after-commit.md) | Actions run after the commit and never undo it | draft |
| [F/applications/flow/000238](requirements/functional/applications/flow/000238_one-dispatcher.md) | Every fire path runs the full action chain | draft |
| [F/applications/flow/000239](requirements/functional/applications/flow/000239_add-to-meeting.md) | A transition into a vote state can add the Antrag to a meeting | draft |
| [F/applications/flow/000240](requirements/functional/applications/flow/000240_implicit-mails.md) | Every state change sends the implicit mails | draft |
| [F/applications/flow/000241](requirements/functional/applications/flow/000241_minute-cron.md) | The minute cron advances and cleans up | draft |
| [F/applications/flow/000242](requirements/functional/applications/flow/000242_revert-status.md) | A status revert works only from the reverted state | draft |
| [F/applications/flow/000243](requirements/functional/applications/flow/000243_vote-gremium-snapshot.md) | The vote Gremium is a snapshot | draft |
| [F/applications/flow/000244](requirements/functional/applications/flow/000244_budget-locked-by-vote.md) | The cost centre is locked during a budget vote | draft |
| [F/applications/flow/000245](requirements/functional/applications/flow/000245_applicant-transitions.md) | Applicant transitions need actorIsApplicant | draft |
| [F/applications/forms/000133](requirements/functional/applications/forms/000133_positions-shape.md) | A positions answer has label and offers | draft |
| [F/applications/forms/000134](requirements/functional/applications/forms/000134_offer-limits.md) | Offer counts have limits | draft |
| [F/applications/forms/000135](requirements/functional/applications/forms/000135_funding-field.md) | The requested funding is separate from the costs | draft |
| [F/applications/forms/000136](requirements/functional/applications/forms/000136_all-languages-editable.md) | Every i18n text is editable in English too | draft |
| [F/applications/forms/000137](requirements/functional/applications/forms/000137_flow-auto-layout.md) | The flow editor lays out automatically | draft |
| [F/applications/forms/000280](requirements/functional/applications/forms/000280_pin-not-mutate.md) | A form version is never changed | draft |
| [F/applications/forms/000281](requirements/functional/applications/forms/000281_inactive-type.md) | A type without an active form is closed | draft |
| [F/applications/forms/000282](requirements/functional/applications/forms/000282_system-title.md) | Every form has a title field | draft |
| [F/applications/forms/000283](requirements/functional/applications/forms/000283_sections.md) | Section fields make wizard steps | draft |
| [F/applications/forms/000284](requirements/functional/applications/forms/000284_definition-check.md) | A form definition is checked at save time | draft |
| [F/applications/forms/000285](requirements/functional/applications/forms/000285_jsonlogic-whitelist.md) | JsonLogic uses a whitelist | draft |
| [F/applications/forms/000286](requirements/functional/applications/forms/000286_all-errors.md) | Answer validation reports all errors | draft |
| [F/applications/forms/000287](requirements/functional/applications/forms/000287_pattern-limits.md) | A pattern check cannot hang | draft |
| [F/applications/forms/000288](requirements/functional/applications/forms/000288_finite-numbers.md) | Numbers are finite decimals | draft |
| [F/applications/forms/000289](requirements/functional/applications/forms/000289_form-revision.md) | A form change is versioned and audited | draft |
| [F/collaboration/notifications/000151](requirements/functional/collaboration/notifications/000151_task-mail-recipients.md) | Task mails go only to who can act | draft |
| [F/collaboration/notifications/000152](requirements/functional/collaboration/notifications/000152_team-mails-opt-in.md) | Team mails about Anträge are off by default | draft |
| [F/collaboration/notifications/000153](requirements/functional/collaboration/notifications/000153_sandboxed-templates.md) | Mail templates are sandboxed | draft |
| [F/collaboration/notifications/000306](requirements/functional/collaboration/notifications/000306_mail-queue.md) | Mails go through the queue | draft |
| [F/collaboration/notifications/000307](requirements/functional/collaboration/notifications/000307_mail-once.md) | A mail is sent once | draft |
| [F/collaboration/notifications/000308](requirements/functional/collaboration/notifications/000308_mail-link.md) | Every mail links its element | draft |
| [F/collaboration/notifications/000309](requirements/functional/collaboration/notifications/000309_mail-preferences.md) | A person controls their mail kinds | draft |
| [F/collaboration/notifications/000310](requirements/functional/collaboration/notifications/000310_mail-languages.md) | Mail texts are in German and English | draft |
| [F/collaboration/notifications/000311](requirements/functional/collaboration/notifications/000311_mail-logs.md) | Mail logs hold no personal data | draft |
| [F/collaboration/notifications/000312](requirements/functional/collaboration/notifications/000312_task-reminders.md) | Task reminders follow the admin setting | draft |
| [F/collaboration/search/000328](requirements/functional/collaboration/search/000328_reuse-gates.md) | Search reuses the gate of each module | draft |
| [F/collaboration/search/000329](requirements/functional/collaboration/search/000329_query-length.md) | Search needs two characters | draft |
| [F/collaboration/search/000330](requirements/functional/collaboration/search/000330_per-kind-cap.md) | Search shows a fixed number per kind | draft |
| [F/collaboration/tickets/000150](requirements/functional/collaboration/tickets/000150_public-report.md) | Anyone can report a help ticket | draft |
| [F/collaboration/tickets/000313](requirements/functional/collaboration/tickets/000313_reporter-view.md) | A reporter account follows its tickets | draft |
| [F/collaboration/tickets/000314](requirements/functional/collaboration/tickets/000314_team-work.md) | The team works on tickets | draft |
| [F/collaboration/tickets/000315](requirements/functional/collaboration/tickets/000315_sender-block.md) | A sender can be blocked | draft |
| [F/collaboration/tickets/000316](requirements/functional/collaboration/tickets/000316_ticket-retention.md) | Closed tickets are anonymized after the retention time | draft |
| [F/collaboration/tickets/000317](requirements/functional/collaboration/tickets/000317_context-url.md) | A ticket context keeps only platform pages | draft |
| [F/collaboration/todos/000147](requirements/functional/collaboration/todos/000147_board-kinds.md) | Boards per Gremium, per person and per team | draft |
| [F/collaboration/todos/000148](requirements/functional/collaboration/todos/000148_move-sheet.md) | One move sheet | draft |
| [F/collaboration/todos/000149](requirements/functional/collaboration/todos/000149_no-status-sync.md) | No status sync between ticket and card | draft |
| [F/collaboration/todos/000318](requirements/functional/collaboration/todos/000318_board-rights.md) | Board rights depend on the board kind | draft |
| [F/collaboration/todos/000319](requirements/functional/collaboration/todos/000319_unreadable-404.md) | An unreadable board is not found | draft |
| [F/collaboration/todos/000320](requirements/functional/collaboration/todos/000320_members-only.md) | Only members are assigned or mentioned | draft |
| [F/collaboration/todos/000321](requirements/functional/collaboration/todos/000321_no-transfer-to-personal.md) | A shared card does not move to a personal board | draft |
| [F/collaboration/todos/000322](requirements/functional/collaboration/todos/000322_transfer-rules.md) | A transfer keeps what the target supports | draft |
| [F/collaboration/todos/000323](requirements/functional/collaboration/todos/000323_done-column.md) | The done column sets the completion time | draft |
| [F/collaboration/todos/000324](requirements/functional/collaboration/todos/000324_live-pings.md) | Boards update live | draft |
| [F/collaboration/todos/000325](requirements/functional/collaboration/todos/000325_todo-mails.md) | To-do mails go to assignees | draft |
| [F/collaboration/todos/000326](requirements/functional/collaboration/todos/000326_card-on-agenda.md) | A card can go on the agenda | draft |
| [F/collaboration/todos/000327](requirements/functional/collaboration/todos/000327_link-access.md) | A link shows nothing without access | draft |
| [F/finance/budget/000138](requirements/functional/finance/budget/000138_cost-centre-picker.md) | The cost centre pickers are fixed | draft |
| [F/finance/budget/000139](requirements/functional/finance/budget/000139_close-fiscal-year.md) | A fiscal year closes and reopens | draft |
| [F/finance/budget/000140](requirements/functional/finance/budget/000140_default-fiscal-year.md) | The default fiscal year holds today | draft |
| [F/finance/budget/000141](requirements/functional/finance/budget/000141_fiscal-year-delete.md) | A fiscal year in use is not deleted | draft |
| [F/finance/budget/000142](requirements/functional/finance/budget/000142_duplicate-booking.md) | A booking can be duplicated | draft |
| [F/finance/budget/000143](requirements/functional/finance/budget/000143_transfer-kind.md) | A transfer is a kind in the Art filter | draft |
| [F/finance/budget/000144](requirements/functional/finance/budget/000144_cost-centre-items.md) | The cost centre card lists Anträge and bookings | draft |
| [F/finance/budget/000145](requirements/functional/finance/budget/000145_revert-keeps-invoice.md) | A reverted booking keeps the invoice status | draft |
| [F/finance/budget/000146](requirements/functional/finance/budget/000146_legend.md) | The budget legend matches the drawing | draft |
| [F/finance/budget/000246](requirements/functional/finance/budget/000246_path-key.md) | A cost centre has a stable path key | draft |
| [F/finance/budget/000247](requirements/functional/finance/budget/000247_roll-up.md) | Allocation flows down, consumption flows up | draft |
| [F/finance/budget/000248](requirements/functional/finance/budget/000248_available-formula.md) | The available amount can be negative | draft |
| [F/finance/budget/000249](requirements/functional/finance/budget/000249_state-classes.md) | Flow states classify the amount of an Antrag | draft |
| [F/finance/budget/000250](requirements/functional/finance/budget/000250_decision-gremium.md) | The deciding Gremium is inherited | draft |
| [F/finance/budget/000251](requirements/functional/finance/budget/000251_fiscal-year-bounds.md) | A fiscal year starts on a day from 1 to 28 | draft |
| [F/finance/budget/000252](requirements/functional/finance/budget/000252_closed-year-refuses.md) | A closed fiscal year refuses money changes | draft |
| [F/finance/budget/000253](requirements/functional/finance/budget/000253_euro-only.md) | Amounts are euro only | draft |
| [F/finance/budget/000254](requirements/functional/finance/budget/000254_delete-in-use.md) | A cost centre in use is not deleted | draft |
| [F/finance/budget/000255](requirements/functional/finance/budget/000255_money-audit.md) | Every money change is audited and revertable | draft |
| [F/finance/budget/000256](requirements/functional/finance/budget/000256_transfer-pair.md) | A transfer is a pair of bookings | draft |
| [F/finance/budget/000257](requirements/functional/finance/budget/000257_income-no-application.md) | An income never belongs to an Antrag | draft |
| [F/finance/budget/000258](requirements/functional/finance/budget/000258_sub-bookings.md) | A booking can have sub-bookings | draft |
| [F/finance/budget/000259](requirements/functional/finance/budget/000259_gremium-view.md) | Gremium members see their cost centres | draft |
| [F/finance/invoices/000260](requirements/functional/finance/invoices/000260_invoice-bookings.md) | An invoice is a document with many bookings | draft |
| [F/finance/invoices/000261](requirements/functional/finance/invoices/000261_paid-by-user.md) | Only a user sets an invoice to paid | draft |
| [F/finance/invoices/000262](requirements/functional/finance/invoices/000262_invoice-segments.md) | The invoice list has three segments | draft |
| [F/finance/invoices/000263](requirements/functional/finance/invoices/000263_zugferd-import.md) | A ZUGFeRD invoice fills the form | draft |
| [F/integrations/external/000176](requirements/functional/integrations/external/000176_optional.md) | Integrations are optional | draft |
| [F/integrations/external/000177](requirements/functional/integrations/external/000177_preview-access.md) | A link preview uses the access of the viewer | draft |
| [F/integrations/mcp/000174](requirements/functional/integrations/mcp/000174_acts-as-user.md) | The MCP server acts as the logged-in user | draft |
| [F/integrations/mcp/000175](requirements/functional/integrations/mcp/000175_prod-data.md) | Production data changes only on request | draft |
| [F/integrations/mcp/000272](requirements/functional/integrations/mcp/000272_token-scope.md) | An agent token has a scope and a lifetime | draft |
| [F/integrations/mcp/000273](requirements/functional/integrations/mcp/000273_forbidden-permissions.md) | An agent never casts a ballot or merges accounts | draft |
| [F/integrations/mcp/000274](requirements/functional/integrations/mcp/000274_revoke-grants.md) | Tokens can be revoked | draft |
| [F/integrations/mcp/000385](requirements/functional/integrations/mcp/000385_version-bump.md) | The MCP version moves with its tools | draft |
| [F/integrations/mcp/000386](requirements/functional/integrations/mcp/000386_no-ballot-tool.md) | The MCP has no ballot tool | draft |
| [F/integrations/mcp/000387](requirements/functional/integrations/mcp/000387_idp-roles-read-only.md) | Memberships and roles are read-only in the MCP | draft |
| [F/integrations/mcp/000388](requirements/functional/integrations/mcp/000388_token-file.md) | The MCP token file is private | draft |
| [F/integrations/webhooks/000296](requirements/functional/integrations/webhooks/000296_secret-hidden.md) | A webhook secret is never shown | draft |
| [F/integrations/webhooks/000297](requirements/functional/integrations/webhooks/000297_signature.md) | A webhook request is signed with a timestamp | draft |
| [F/integrations/webhooks/000298](requirements/functional/integrations/webhooks/000298_retry.md) | A failed delivery is retried with backoff | draft |
| [F/integrations/webhooks/000299](requirements/functional/integrations/webhooks/000299_idempotent-delivery.md) | A delivery runs once per key | draft |
| [F/integrations/webhooks/000402](requirements/functional/integrations/webhooks/000402_flow-action-only.md) | A webhook fires only through a flow action | draft |
| [F/integrations/webhooks/000403](requirements/functional/integrations/webhooks/000403_delete-webhook.md) | A webhook can be deleted | draft |
| [F/meetings/calendar/000331](requirements/functional/meetings/calendar/000331_feed.md) | Each person has a calendar feed | draft |
| [F/meetings/calendar/000332](requirements/functional/meetings/calendar/000332_feed-404.md) | A wrong feed token is not found | draft |
| [F/meetings/calendar/000333](requirements/functional/meetings/calendar/000333_event-defaults.md) | A calendar event has a reminder | draft |
| [F/meetings/delegations/000110](requirements/functional/meetings/delegations/000110_per-gremium.md) | Vote delegation is a Gremium setting | draft |
| [F/meetings/delegations/000111](requirements/functional/meetings/delegations/000111_delegation-blocks-presence.md) | A member with an active delegation is not present | draft |
| [F/meetings/delegations/000112](requirements/functional/meetings/delegations/000112_one-pool.md) | The substitute pool is the only substitute rule | draft |
| [F/meetings/delegations/000113](requirements/functional/meetings/delegations/000113_pool-seats.md) | A pool substitute takes a free seat | draft |
| [F/meetings/delegations/000114](requirements/functional/meetings/delegations/000114_pool-read-scope.md) | Pool substitutes read like members | draft |
| [F/meetings/delegations/000362](requirements/functional/meetings/delegations/000362_meeting-bound.md) | A delegation belongs to one meeting | draft |
| [F/meetings/delegations/000363](requirements/functional/meetings/delegations/000363_moves-vote.md) | A delegation moves the vote | draft |
| [F/meetings/delegations/000364](requirements/functional/meetings/delegations/000364_eligible-delegator.md) | Only an eligible member delegates | draft |
| [F/meetings/delegations/000365](requirements/functional/meetings/delegations/000365_no-chains.md) | Delegations do not chain | draft |
| [F/meetings/delegations/000366](requirements/functional/meetings/delegations/000366_deadline.md) | A delegation has a deadline | draft |
| [F/meetings/delegations/000367](requirements/functional/meetings/delegations/000367_roster-privacy.md) | Roster names are visible only to the Gremium | draft |
| [F/meetings/delegations/000420](requirements/functional/meetings/delegations/000420_lead-enters-substitute.md) | The lead can enter a pool substitute | draft |
| [F/meetings/meetings/000092](requirements/functional/meetings/meetings/000092_open-window.md) | A meeting opens in a configured window | draft |
| [F/meetings/meetings/000093](requirements/functional/meetings/meetings/000093_state-order.md) | Meeting states move only forward | draft |
| [F/meetings/meetings/000094](requirements/functional/meetings/meetings/000094_close-with-open-vote.md) | A meeting with an open vote does not close | draft |
| [F/meetings/meetings/000095](requirements/functional/meetings/meetings/000095_prepare-before-open.md) | The protocol and votes can be prepared before the open | draft |
| [F/meetings/meetings/000096](requirements/functional/meetings/meetings/000096_no-prep-page.md) | There is no preparation page | draft |
| [F/meetings/meetings/000097](requirements/functional/meetings/meetings/000097_delete-removes-votes.md) | A meeting delete removes its votes | draft |
| [F/meetings/meetings/000098](requirements/functional/meetings/meetings/000098_agenda-changes.md) | Agenda changes only while planned or live | draft |
| [F/meetings/meetings/000099](requirements/functional/meetings/meetings/000099_top-text-editable.md) | A TOP text is editable until the protocol is final | draft |
| [F/meetings/meetings/000100](requirements/functional/meetings/meetings/000100_agenda-subtitle.md) | An agenda row has a subtitle only for an Antrag | draft |
| [F/meetings/meetings/000101](requirements/functional/meetings/meetings/000101_application-top-row.md) | A TOP with an Antrag shows the Antrag as its first row | draft |
| [F/meetings/meetings/000102](requirements/functional/meetings/meetings/000102_top-attachments-internal.md) | TOP attachments are internal | draft |
| [F/meetings/meetings/000103](requirements/functional/meetings/meetings/000103_attendance.md) | Lead-set attendance wins | draft |
| [F/meetings/meetings/000104](requirements/functional/meetings/meetings/000104_qr-only-without-quorum.md) | Public participation only without quorum | draft |
| [F/meetings/meetings/000105](requirements/functional/meetings/meetings/000105_admit-guests.md) | The meeting lead admits each guest | draft |
| [F/meetings/meetings/000106](requirements/functional/meetings/meetings/000106_guest-modes.md) | Guests vote or only watch | draft |
| [F/meetings/meetings/000107](requirements/functional/meetings/meetings/000107_guest-view.md) | Guests see public TOPs only | draft |
| [F/meetings/meetings/000108](requirements/functional/meetings/meetings/000108_guest-pseudonyms.md) | Guest names become pseudonyms | draft |
| [F/meetings/meetings/000109](requirements/functional/meetings/meetings/000109_list-and-calendar.md) | The meeting list has a list and a calendar | draft |
| [F/meetings/meetings/000345](requirements/functional/meetings/meetings/000345_gremium-rights.md) | Meeting rights are per Gremium | draft |
| [F/meetings/meetings/000346](requirements/functional/meetings/meetings/000346_open-needs-keeper.md) | A meeting opens only with a protokollant | draft |
| [F/meetings/meetings/000347](requirements/functional/meetings/meetings/000347_keeper-periods.md) | A keeper period follows the current TOP | draft |
| [F/meetings/meetings/000348](requirements/functional/meetings/meetings/000348_vote-needs-state.md) | A vote on an Antrag needs the matching vote state | draft |
| [F/meetings/meetings/000349](requirements/functional/meetings/meetings/000349_aggregates-only.md) | Live data shows only aggregates | draft |
| [F/meetings/meetings/000351](requirements/functional/meetings/meetings/000351_join-code.md) | A join code is short and unambiguous | draft |
| [F/meetings/meetings/000352](requirements/functional/meetings/meetings/000352_guest-device.md) | A guest joins with one device | draft |
| [F/meetings/meetings/000353](requirements/functional/meetings/meetings/000353_guest-vote.md) | A vote with guests has no quorum | draft |
| [F/meetings/meetings/000418](requirements/functional/meetings/meetings/000418_calendar-popover.md) | The calendar subscription is on Sitzungen | draft |
| [F/meetings/meetings/000419](requirements/functional/meetings/meetings/000419_gremium-delete.md) | A Gremium delete deletes its meetings | draft |
| [F/meetings/protocols/000115](requirements/functional/meetings/protocols/000115_keeper-permission.md) | The keeper holds protocol.write | draft |
| [F/meetings/protocols/000116](requirements/functional/meetings/protocols/000116_finalize.md) | Finalize needs a closed meeting and protocol.finalize | draft |
| [F/meetings/protocols/000117](requirements/functional/meetings/protocols/000117_delete-draft-only.md) | Only a draft protocol is deleted | draft |
| [F/meetings/protocols/000118](requirements/functional/meetings/protocols/000118_pdf-name.md) | The PDF is named after the meeting | draft |
| [F/meetings/protocols/000119](requirements/functional/meetings/protocols/000119_signatures-one-page.md) | The signature block stays on one page | draft |
| [F/meetings/protocols/000120](requirements/functional/meetings/protocols/000120_election-ranking.md) | An election shows a ranking | draft |
| [F/meetings/protocols/000354](requirements/functional/meetings/protocols/000354_built-from-tops.md) | The protocol is built from the TOP texts | draft |
| [F/meetings/protocols/000355](requirements/functional/meetings/protocols/000355_public-variant.md) | A non-public TOP gives a second PDF | draft |
| [F/meetings/protocols/000356](requirements/functional/meetings/protocols/000356_render-before-commit.md) | A failed render keeps the draft | draft |
| [F/meetings/protocols/000357](requirements/functional/meetings/protocols/000357_roster-quorum.md) | The quorum uses the roster of the meeting | draft |
| [F/meetings/protocols/000358](requirements/functional/meetings/protocols/000358_protocol-mail.md) | The protocol mail carries the PDF | draft |
| [F/meetings/protocols/000359](requirements/functional/meetings/protocols/000359_cd-variant.md) | The CD variant selects the layout | draft |
| [F/meetings/protocols/000360](requirements/functional/meetings/protocols/000360_text-is-data.md) | Protocol text is data, never code | draft |
| [F/meetings/protocols/000361](requirements/functional/meetings/protocols/000361_image-budget.md) | A protocol shows at most 48 images | draft |
| [F/meetings/voting/000024](requirements/functional/meetings/voting/000024_every-vote-is-secret.md) | Every vote is secret | draft |
| [F/meetings/voting/000025](requirements/functional/meetings/voting/000025_ballot-does-not-change.md) | A cast ballot does not change | draft |
| [F/meetings/voting/000026](requirements/functional/meetings/voting/000026_tie-rejects-motion.md) | A tie rejects a motion | draft |
| [F/meetings/voting/000027](requirements/functional/meetings/voting/000027_election-tie-by-lot.md) | A tie in an election is decided by lot | draft |
| [F/meetings/voting/000028](requirements/functional/meetings/voting/000028_protokollant-opens-and-closes.md) | Only the protokollant opens and closes a meeting vote | draft |
| [F/meetings/voting/000029](requirements/functional/meetings/voting/000029_delete-only-draft-or-cancelled.md) | A vote can be deleted only as draft or cancelled | draft |
| [F/meetings/voting/000030](requirements/functional/meetings/voting/000030_vote-in-gremium-of-antrag.md) | A vote on an Antrag belongs to the Gremium of the Antrag | draft |
| [F/meetings/voting/000031](requirements/functional/meetings/voting/000031_poll-shows-only-counts.md) | A poll shows only counts | draft |
| [F/meetings/voting/000378](requirements/functional/meetings/voting/000378_db-serializes-cast.md) | The database serializes ballots | draft |
| [F/meetings/voting/000379](requirements/functional/meetings/voting/000379_close-with-branch.md) | The close and its branch commit together | draft |
| [F/meetings/voting/000380](requirements/functional/meetings/voting/000380_quorum-close.md) | An unmet quorum blocks the manual close | draft |
| [F/meetings/voting/000381](requirements/functional/meetings/voting/000381_eligible-count.md) | The eligible count comes from the roster | draft |
| [F/meetings/voting/000382](requirements/functional/meetings/voting/000382_delegation-ballot.md) | A delegation ballot is a second ballot | draft |
| [F/public/public-pages/000170](requirements/functional/public/public-pages/000170_no-public-meetings.md) | Meetings are never public | draft |
| [F/public/public-pages/000171](requirements/functional/public/public-pages/000171_public-protocols.md) | Only final protocols of public Gremien are public | draft |
| [F/public/public-pages/000172](requirements/functional/public/public-pages/000172_public-protocol-content.md) | A public protocol has no names and no internal TOPs | draft |
| [F/public/public-pages/000173](requirements/functional/public/public-pages/000173_noindex.md) | Public pages are not indexed | draft |
| [NF/accessibility/interaction/000217](requirements/non-functional/accessibility/interaction/000217_keyboard-and-labels.md) | Controls are reachable by keyboard and named | draft |
| [NF/accessibility/interaction/000218](requirements/non-functional/accessibility/interaction/000218_themes.md) | Light and dark themes are both supported | draft |
| [NF/accessibility/interaction/000219](requirements/non-functional/accessibility/interaction/000219_reduced-motion.md) | Motion follows the reduced motion setting | draft |
| [NF/accessibility/language/000216](requirements/non-functional/accessibility/language/000216_i18n-parity.md) | German and English texts are complete | replaced |
| [NF/compatibility/deploy/000390](requirements/non-functional/compatibility/deploy/000390_typst-pin.md) | The typst version is pinned in two places | draft |
| [NF/compatibility/deploy/000394](requirements/non-functional/compatibility/deploy/000394_migrate-first.md) | A deploy runs the migration first | draft |
| [NF/compatibility/deploy/000434](requirements/non-functional/compatibility/deploy/000434_environments.md) | Dev follows development, production follows tags | draft |
| [NF/compatibility/deploy/000435](requirements/non-functional/compatibility/deploy/000435_caddy-edge.md) | Caddy is the edge proxy | draft |
| [NF/compatibility/pwa/000220](requirements/non-functional/compatibility/pwa/000220_zoom.md) | Zoom is blocked only in the installed app | draft |
| [NF/compatibility/pwa/000221](requirements/non-functional/compatibility/pwa/000221_android-nav-bar.md) | The Android navigation bar has the manifest colour | draft |
| [NF/compatibility/pwa/000222](requirements/non-functional/compatibility/pwa/000222_update-offline.md) | The app shows update and offline bars | draft |
| [NF/compatibility/pwa/000411](requirements/non-functional/compatibility/pwa/000411_status-bar-theme.md) | The status bar follows the theme | draft |
| [NF/performance/loading/000189](requirements/non-functional/performance/loading/000189_load-bar.md) | The load bar shows only for slow foreground reads | draft |
| [NF/performance/loading/000190](requirements/non-functional/performance/loading/000190_batch-reads.md) | A list reads its rows in one request | draft |
| [NF/performance/loading/000191](requirements/non-functional/performance/loading/000191_search-as-you-type.md) | Search runs as you type | draft |
| [NF/privacy/personal-data/000185](requirements/non-functional/privacy/personal-data/000185_no-raw-ids.md) | The UI shows no raw IDs | draft |
| [NF/privacy/personal-data/000186](requirements/non-functional/privacy/personal-data/000186_no-plain-ip.md) | The login audit has no plain IP address | draft |
| [NF/privacy/personal-data/000187](requirements/non-functional/privacy/personal-data/000187_guest-pseudonyms.md) | Guests get pseudonyms | replaced |
| [NF/privacy/personal-data/000188](requirements/non-functional/privacy/personal-data/000188_anonymize.md) | Personal data can be anonymized | draft |
| [NF/privacy/personal-data/000404](requirements/non-functional/privacy/personal-data/000404_markdown-images.md) | Markdown images are outside erasure and export | draft |
| [NF/security/access/000179](requirements/non-functional/security/access/000179_public-allowlist.md) | A public route is on the allowlist | draft |
| [NF/security/access/000180](requirements/non-functional/security/access/000180_public-abuse-guard.md) | Public input is protected against abuse | draft |
| [NF/security/access/000275](requirements/non-functional/security/access/000275_oauth-pkce.md) | The OAuth flow needs PKCE and a loopback redirect | draft |
| [NF/security/access/000276](requirements/non-functional/security/access/000276_no-tokens-in-js.md) | Tokens never reach JavaScript | draft |
| [NF/security/access/000277](requirements/non-functional/security/access/000277_hashed-tokens.md) | Tokens are stored only as hashes | draft |
| [NF/security/access/000278](requirements/non-functional/security/access/000278_anti-enumeration.md) | A magic-link request does not reveal accounts | draft |
| [NF/security/access/000279](requirements/non-functional/security/access/000279_oidc-discovery.md) | OIDC endpoints come from discovery | draft |
| [NF/security/access/000350](requirements/non-functional/security/access/000350_socket-origin.md) | A meeting socket checks the origin | draft |
| [NF/security/files/000178](requirements/non-functional/security/files/000178_stream-downloads.md) | Downloads stream through the API | draft |
| [NF/security/files/000181](requirements/non-functional/security/files/000181_scan-uploads.md) | Uploaded files are scanned | draft |
| [NF/security/files/000264](requirements/non-functional/security/files/000264_invoice-download.md) | An invoice file is served as a download | draft |
| [NF/security/files/000305](requirements/non-functional/security/files/000305_restore-paths.md) | A restore writes only inside the bucket | draft |
| [NF/security/integrity/000183](requirements/non-functional/security/integrity/000183_audit-chain.md) | The audit log is append-only | draft |
| [NF/security/integrity/000184](requirements/non-functional/security/integrity/000184_sandboxed-mail.md) | Mail templates run sandboxed | draft |
| [NF/security/integrity/000393](requirements/non-functional/security/integrity/000393_db-roles.md) | Database roles are separated | draft |
| [NF/security/network/000182](requirements/non-functional/security/network/000182_webhook-ssrf.md) | The webhook SSRF guard runs at send time | draft |
| [NF/security/network/000335](requirements/non-functional/security/network/000335_avatar-fetch.md) | The avatar fetch is fixed and limited | draft |
| [NF/security/network/000389](requirements/non-functional/security/network/000389_typst-isolated.md) | The render service has no network egress | draft |
| [NF/security/network/000391](requirements/non-functional/security/network/000391_host-ports.md) | Only two ports are bound on the host | draft |
| [NF/security/network/000392](requirements/non-functional/security/network/000392_forwarded-ips.md) | Forwarded headers come only from the proxy | draft |
| [NF/usability/controls/000203](requirements/non-functional/usability/controls/000203_app-popover.md) | Every dropdown uses the app popover | draft |
| [NF/usability/controls/000204](requirements/non-functional/usability/controls/000204_whole-control.md) | The whole control is clickable | draft |
| [NF/usability/controls/000205](requirements/non-functional/usability/controls/000205_empty-state.md) | Empty states use one component | draft |
| [NF/usability/controls/000206](requirements/non-functional/usability/controls/000206_no-helper-texts.md) | The UI has no helper texts | draft |
| [NF/usability/controls/000207](requirements/non-functional/usability/controls/000207_no-title-counters.md) | Titles show no counters | draft |
| [NF/usability/controls/000208](requirements/non-functional/usability/controls/000208_separators.md) | A separator stands only between two items | draft |
| [NF/usability/controls/000209](requirements/non-functional/usability/controls/000209_no-cut-urls.md) | URLs, IBANs and e-mail addresses are never cut | draft |
| [NF/usability/controls/000210](requirements/non-functional/usability/controls/000210_press-feedback.md) | A press gives feedback | draft |
| [NF/usability/controls/000211](requirements/non-functional/usability/controls/000211_swipe-and-select.md) | A swipe never deletes | draft |
| [NF/usability/controls/000212](requirements/non-functional/usability/controls/000212_tooltips.md) | A tooltip shows only for cut text | draft |
| [NF/usability/controls/000213](requirements/non-functional/usability/controls/000213_segments.md) | Segments have equal width | draft |
| [NF/usability/controls/000214](requirements/non-functional/usability/controls/000214_pill-icon.md) | A leading icon is centred on the end cap | draft |
| [NF/usability/controls/000399](requirements/non-functional/usability/controls/000399_design-basics.md) | The design has one accent and plain status text | draft |
| [NF/usability/controls/000400](requirements/non-functional/usability/controls/000400_danger-button.md) | A destructive action is an outlined red button | draft |
| [NF/usability/controls/000401](requirements/non-functional/usability/controls/000401_error-toast.md) | Errors show as a toast | draft |
| [NF/usability/controls/000410](requirements/non-functional/usability/controls/000410_tap-tint.md) | A tap tints the whole tile | draft |
| [NF/usability/controls/000412](requirements/non-functional/usability/controls/000412_ghost-rows-for-lists.md) | Ghost rows are only for lists | draft |
| [NF/usability/controls/000416](requirements/non-functional/usability/controls/000416_empty-chart.md) | An empty chart is a grey skeleton | draft |
| [NF/usability/layout/000192](requirements/non-functional/usability/layout/000192_one-geometry.md) | All list and detail pages share one geometry | draft |
| [NF/usability/layout/000193](requirements/non-functional/usability/layout/000193_scroll-edges.md) | A scroll edge fades, or cuts at a line | draft |
| [NF/usability/layout/000194](requirements/non-functional/usability/layout/000194_phone-breakpoint.md) | The phone layout starts below 768 px | draft |
| [NF/usability/layout/000195](requirements/non-functional/usability/layout/000195_bottom-bar.md) | The phone bottom bar is fixed | draft |
| [NF/usability/layout/000196](requirements/non-functional/usability/layout/000196_phone-sheets.md) | The phone opens pickers as bottom sheets | draft |
| [NF/usability/layout/000197](requirements/non-functional/usability/layout/000197_header-actions.md) | A header has a title, at most one action and a menu | draft |
| [NF/usability/layout/000198](requirements/non-functional/usability/layout/000198_floating-actions.md) | Neu and Speichern float at the bottom | draft |
| [NF/usability/layout/000199](requirements/non-functional/usability/layout/000199_footer.md) | The footer shows only on start and public pages | draft |
| [NF/usability/layout/000200](requirements/non-functional/usability/layout/000200_surfaces.md) | Surfaces step up | draft |
| [NF/usability/layout/000201](requirements/non-functional/usability/layout/000201_fill-or-centre.md) | Content fills its width or is centred | draft |
| [NF/usability/layout/000202](requirements/non-functional/usability/layout/000202_top-layer.md) | Dialogs and toasts are on the top layer | draft |
| [NF/usability/layout/000215](requirements/non-functional/usability/layout/000215_comments-beside.md) | Comments sit beside the fields | draft |
| [NF/usability/layout/000406](requirements/non-functional/usability/layout/000406_desktop-unchanged.md) | The phone layout does not change the desktop | draft |
| [NF/usability/layout/000407](requirements/non-functional/usability/layout/000407_mehr-and-search.md) | Mehr and Suche are always in reach | draft |
| [NF/usability/layout/000408](requirements/non-functional/usability/layout/000408_bottom-inset.md) | Fixed bottom elements sit above the bottom bar | draft |
| [NF/usability/layout/000409](requirements/non-functional/usability/layout/000409_phone-panes.md) | The phone shows one pane and card tables | draft |
| [NF/usability/layout/000413](requirements/non-functional/usability/layout/000413_card-mode.md) | A table in card mode keeps its controls in the card head | draft |
| [NF/usability/layout/000414](requirements/non-functional/usability/layout/000414_admin-heading.md) | Admin pages share one heading | draft |
| [NF/usability/layout/000415](requirements/non-functional/usability/layout/000415_balanced-bars.md) | Bars and headers are vertically balanced | draft |
| [NF/usability/layout/000417](requirements/non-functional/usability/layout/000417_antraege-pattern.md) | Work lists follow the Anträge pattern | draft |
| [S/backend/database/000068](style/backend/database/000068_hash-revision.md) | A migration has a hash ID | draft |
| [S/backend/database/000069](style/backend/database/000069_one-head.md) | Alembic has one head | draft |
| [S/backend/database/000070](style/backend/database/000070_idempotent-tables.md) | A migration that adds a table is idempotent | draft |
| [S/backend/database/000071](style/backend/database/000071_data-revision.md) | A data change has its own revision | draft |
| [S/backend/database/000072](style/backend/database/000072_immutable-records.md) | Five record types are immutable | draft |
| [S/backend/functional/000090](style/backend/functional/000090_no-gather-on-session.md) | One AsyncSession is never used concurrently | draft |
| [S/backend/python/000058](style/backend/python/000058_aware-datetimes.md) | Datetimes are timezone-aware | draft |
| [S/backend/python/000059](style/backend/python/000059_server-side-rbac.md) | Permissions are checked on the server | draft |
| [S/backend/python/000060](style/backend/python/000060_permission-not-role.md) | A gate names a permission, not a role | draft |
| [S/backend/python/000061](style/backend/python/000061_strict-types.md) | Inputs are strictly typed | draft |
| [S/backend/python/000062](style/backend/python/000062_docstrings.md) | Docstrings instead of comments | draft |
| [S/backend/python/000063](style/backend/python/000063_no-eval.md) | No eval | draft |
| [S/backend/python/000064](style/backend/python/000064_resolve-names.md) | Names are resolved on the server | draft |
| [S/backend/python/000065](style/backend/python/000065_merge-columns.md) | A principal column is known to the account merge | draft |
| [S/backend/python/000066](style/backend/python/000066_public-routes.md) | Public endpoints are a fixed list | draft |
| [S/backend/python/000067](style/backend/python/000067_nix-dev-shell.md) | Commands run in the Nix dev shell | draft |
| [S/frontend/angular/000073](style/frontend/angular/000073_i18n-parity.md) | Every UI text is in both catalogs | draft |
| [S/frontend/angular/000074](style/frontend/angular/000074_production-build.md) | Run the production build after style changes | draft |
| [S/frontend/angular/000075](style/frontend/angular/000075_narrow-with-as.md) | A template narrows a signal with as | draft |
| [S/frontend/angular/000076](style/frontend/angular/000076_tailwind-borders.md) | A Tailwind border has a style | draft |
| [S/frontend/angular/000077](style/frontend/angular/000077_load-bar.md) | Only foreground reads show the load bar | replaced |
| [S/frontend/angular/000078](style/frontend/angular/000078_after-next-render.md) | Wait for a render with afterNextRender | draft |
| [S/frontend/angular/000079](style/frontend/angular/000079_ui-kit-parts.md) | Shared UI parts live in the ui-kit | draft |
| [S/frontend/angular/000080](style/frontend/angular/000080_standalone-components.md) | Components are standalone with own files | draft |
| [S/frontend/angular/000395](style/frontend/angular/000395_semantic-tokens.md) | Components use semantic colour tokens | draft |
| [S/frontend/angular/000396](style/frontend/angular/000396_route-guards.md) | A route guard is only for the UX | draft |
| [S/frontend/angular/000397](style/frontend/angular/000397_gremium-checks.md) | Gremium rights come from the Gremium API | draft |
| [S/frontend/angular/000398](style/frontend/angular/000398_mock-dev-only.md) | The mock API runs only in dev builds | draft |
| [S/frontend/functional/000091](style/frontend/functional/000091_signal-update.md) | A signal update returns a new value | draft |
| [S/shared/agents/000426](style/shared/agents/000426_ask-with-options.md) | Ask with options | draft |
| [S/shared/agents/000427](style/shared/agents/000427_report-bugs.md) | Report a possible bug | draft |
| [S/shared/agents/000428](style/shared/agents/000428_no-unasked-features.md) | Do not build what exists | draft |
| [S/shared/agents/000429](style/shared/agents/000429_mockup-remark.md) | A mockup remark does not change the ui-kit | draft |
| [S/shared/agents/000430](style/shared/agents/000430_attach-mockups.md) | Mockup images go into the thread | draft |
| [S/shared/agents/000431](style/shared/agents/000431_plan-in-main.md) | Plan in the main session | draft |
| [S/shared/agents/000432](style/shared/agents/000432_no-main-checkout.md) | Do not touch the main checkout | draft |
| [S/shared/agents/000433](style/shared/agents/000433_no-imitation.md) | No page imitates an organization | draft |
| [S/shared/api/000039](style/shared/api/000039_same-names.md) | Field names are the same in frontend and backend | draft |
| [S/shared/api/000040](style/shared/api/000040_camelcase-base-model.md) | Schemas use the shared camelCase base model | draft |
| [S/shared/api/000041](style/shared/api/000041_one-source.md) | Shared data has one source | draft |
| [S/shared/api/000042](style/shared/api/000042_problem-json.md) | Every error is problem+json | draft |
| [S/shared/api/000043](style/shared/api/000043_mcp-version.md) | The MCP version rises with the tool set | draft |
| [S/shared/functional/000081](style/shared/functional/000081_body-shape.md) | A function body has one shape | draft |
| [S/shared/functional/000082](style/shared/functional/000082_readability-limit.md) | Readability limits the single expression | draft |
| [S/shared/functional/000083](style/shared/functional/000083_bind-once.md) | A local is bound once | draft |
| [S/shared/functional/000084](style/shared/functional/000084_no-mutation.md) | A value is not mutated | draft |
| [S/shared/functional/000085](style/shared/functional/000085_comprehensions.md) | Comprehensions instead of loops | draft |
| [S/shared/functional/000086](style/shared/functional/000086_exhaustive-match.md) | A branch on one value is an exhaustive match | draft |
| [S/shared/functional/000087](style/shared/functional/000087_frozen-data.md) | Data types are frozen by default | draft |
| [S/shared/functional/000088](style/shared/functional/000088_effects-at-edge.md) | Effects stay at the edge | draft |
| [S/shared/functional/000089](style/shared/functional/000089_exceptions.md) | The exceptions are named | draft |
| [S/shared/git/000051](style/shared/git/000051_commits.md) | Commits are unsigned and have no trailers | draft |
| [S/shared/git/000052](style/shared/git/000052_no-auto-merge.md) | A pull request is never set to auto-merge | draft |
| [S/shared/git/000053](style/shared/git/000053_release-tags.md) | Only the owner tags a release | draft |
| [S/shared/git/000054](style/shared/git/000054_merge-go.md) | A merge needs the go of the owner | draft |
| [S/shared/git/000055](style/shared/git/000055_ui-screenshots.md) | A UI change is approved on screenshots | draft |
| [S/shared/git/000056](style/shared/git/000056_ui-kit-flow.md) | ui-kit changes go to ui-kit development first | draft |
| [S/shared/git/000057](style/shared/git/000057_release-notes.md) | Release notes list migrations and steps | draft |
| [S/shared/git/000224](style/shared/git/000224_target-development.md) | An app pull request targets development | draft |
| [S/shared/git/000225](style/shared/git/000225_found-bugs.md) | A found bug is fixed, a behaviour change is asked | draft |
| [S/shared/git/000423](style/shared/git/000423_one-pr-per-package.md) | One branch and one pull request per package | draft |
| [S/shared/git/000424](style/shared/git/000424_sync-main.md) | Sync main into development first | draft |
| [S/shared/git/000425](style/shared/git/000425_shared-in-kit.md) | Shared list parts live in the ui-kit | draft |
| [S/shared/git/000436](style/shared/git/000436_release-flow.md) | A release goes from development to main by pull request | draft |
| [S/shared/testing/000044](style/shared/testing/000044_test-first.md) | Tests come first | draft |
| [S/shared/testing/000045](style/shared/testing/000045_coverage-gates.md) | Coverage gates hold | draft |
| [S/shared/testing/000046](style/shared/testing/000046_critical-modules.md) | Critical modules have full branch coverage | draft |
| [S/shared/testing/000047](style/shared/testing/000047_own-test-keys.md) | An integration test uses its own keys | draft |
| [S/shared/testing/000048](style/shared/testing/000048_run-integration.md) | CI runs the full suites | draft |
| [S/shared/testing/000049](style/shared/testing/000049_check-pixels.md) | A visual bug is checked on pixels | draft |
| [S/shared/testing/000050](style/shared/testing/000050_mockups-from-real-app.md) | UI mockups come from the real app | draft |
| [S/shared/testing/000223](style/shared/testing/000223_test-refers-to-rule.md) | A test refers back to its rule | draft |
| [S/shared/writing/000034](style/shared/writing/000034_ste-english.md) | Repository texts are written in STE English | draft |
| [S/shared/writing/000035](style/shared/writing/000035_stupa-in-capitals.md) | STUPA is written in capitals | draft |
| [S/shared/writing/000036](style/shared/writing/000036_no-task-references.md) | Texts do not refer to old tasks | draft |
| [S/shared/writing/000037](style/shared/writing/000037_current-fact.md) | Texts state the current fact | draft |
| [S/shared/writing/000038](style/shared/writing/000038_true-docstrings.md) | A docstring is true | draft |
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
| [S/specs/format/000002](style/specs/format/000002_front-matter.md) | A spec starts with a YAML front matter | draft |
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
| [S/specs/structure/000226](style/specs/structure/000226_spec-first.md) | A change request starts as a spec | draft |
