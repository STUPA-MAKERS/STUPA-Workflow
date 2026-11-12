# Specs

The binding rules of STUPA-Workflow. One file holds one rule. The rules for specs are in
[style/specs/](style/specs/). Copy [TEMPLATE.md](TEMPLATE.md) to start a new rule.

## Tree

```
specs/
  style/
    backend/   database, functional, python
    frontend/  angular, functional
    shared/    agents, api, functional, git, testing, tooling, writing
    specs/     content, format, structure, uml
  requirements/
    functional/
      administration/  accounts, admin, audit, backups, files, privacy, translations
      applications/    applications, dashboard, flow, forms
      collaboration/   notifications, search, tickets, todos
      finance/         budget, invoices
      integrations/    external, mcp, webhooks
      meetings/        calendar, delegations, meetings, protocols, voting
      public/          public-pages
    non-functional/
      accessibility/  conformance, documents, interaction, language, perception, settings, statement
      compatibility/  deploy, links, pwa
      performance/    loading
      privacy/        personal-data
      security/       access, files, integrity, network
      usability/      controls, layout
```

The second level is the area, the third level is the topic. A topic folder holds the rule
files, for example `requirements/functional/meetings/voting/000024_every-vote-is-secret.md`.

## Index

| ID | Title | Status |
| --- | --- | --- |
| [F/administration/accounts/000154](requirements/functional/administration/accounts/000154_roles-from-oidc.md) | Memberships and roles come from OIDC groups | approved |
| [F/administration/accounts/000155](requirements/functional/administration/accounts/000155_admin-role.md) | The admin role has every permission | approved |
| [F/administration/accounts/000156](requirements/functional/administration/accounts/000156_login-lifetime.md) | Login lifetime is an admin setting | approved |
| [F/administration/accounts/000157](requirements/functional/administration/accounts/000157_account-merge.md) | An admin merges two accounts | approved |
| [F/administration/accounts/000158](requirements/functional/administration/accounts/000158_revoke-without-login.md) | Role assignments can be revoked without a login | approved |
| [F/administration/accounts/000159](requirements/functional/administration/accounts/000159_ohne-namen.md) | An account without a name shows Ohne Namen | approved |
| [F/administration/accounts/000160](requirements/functional/administration/accounts/000160_membership-sync.md) | Membership sync deletes rows without history | approved |
| [F/administration/accounts/000265](requirements/functional/administration/accounts/000265_refused-logins.md) | A deactivated or merged account cannot log in | approved |
| [F/administration/accounts/000266](requirements/functional/administration/accounts/000266_member-role.md) | Every user holds the member role | approved |
| [F/administration/accounts/000267](requirements/functional/administration/accounts/000267_gremium-rights.md) | Gremium rights come only from the membership | approved |
| [F/administration/accounts/000268](requirements/functional/administration/accounts/000268_magic-link-lifetime.md) | A magic link is valid until an event ends it | approved |
| [F/administration/accounts/000269](requirements/functional/administration/accounts/000269_applicant-edit.md) | An applicant session can edit | approved |
| [F/administration/accounts/000270](requirements/functional/administration/accounts/000270_return-to.md) | The login returns to the page | approved |
| [F/administration/accounts/000271](requirements/functional/administration/accounts/000271_sso-logout.md) | The logout ends the SSO session | approved |
| [F/administration/accounts/000334](requirements/functional/administration/accounts/000334_avatar-proxy.md) | Avatars come through the platform | approved |
| [F/administration/accounts/000422](requirements/functional/administration/accounts/000422_erase-account-action.md) | An account can be erased from the user list | replaced |
| [F/administration/accounts/000439](requirements/functional/administration/accounts/000439_merge-conflicts.md) | A merge combines duplicates and stops at a conflict | approved |
| [F/administration/accounts/000440](requirements/functional/administration/accounts/000440_merged-account-row.md) | A merged account stays as a locked row | approved |
| [F/administration/accounts/000455](requirements/functional/administration/accounts/000455_session-idp-check.md) | A long session is checked at the IdP again | approved |
| [F/administration/accounts/000583](requirements/functional/administration/accounts/000583_email-login.md) | An applicant logs in with an e-mail link | approved |
| [F/administration/accounts/000584](requirements/functional/administration/accounts/000584_email-login-account-address.md) | An account address gets the applicant view only | approved |
| [F/administration/accounts/000585](requirements/functional/administration/accounts/000585_email-login-link-lifetime.md) | A login link works once and ends after a fixed time | approved |
| [F/administration/accounts/000586](requirements/functional/administration/accounts/000586_email-login-confirms.md) | The e-mail login confirms the open guest Anträge of the address | approved |
| [F/administration/accounts/000587](requirements/functional/administration/accounts/000587_email-login-account-owner.md) | A confirmed guest Antrag of an account address belongs to the account | approved |
| [F/administration/accounts/000630](requirements/functional/administration/accounts/000630_link-terms.md) | A magic link opens one Antrag, a login link opens an address | approved |
| [F/administration/admin/000161](requirements/functional/administration/admin/000161_crud-complete.md) | Every entity has create, read, update and delete | approved |
| [F/administration/admin/000162](requirements/functional/administration/admin/000162_cd-variant-delete.md) | A CD variant in use is not deleted | approved |
| [F/administration/admin/000163](requirements/functional/administration/admin/000163_audit-revert.md) | The audit revert reverses effects, never entries | approved |
| [F/administration/admin/000164](requirements/functional/administration/admin/000164_translations.md) | Admins edit UI texts and add languages | replaced |
| [F/administration/admin/000165](requirements/functional/administration/admin/000165_admin-start.md) | Verwaltung keeps its frame widths | approved |
| [F/administration/admin/000166](requirements/functional/administration/admin/000166_dsgvo-delete.md) | A privacy erasure starts from Benutzer | approved |
| [F/administration/admin/000368](requirements/functional/administration/admin/000368_role-keys.md) | Role keys are fixed lower case | approved |
| [F/administration/admin/000369](requirements/functional/administration/admin/000369_page-permissions.md) | Each admin page has its own permission | approved |
| [F/administration/admin/000370](requirements/functional/administration/admin/000370_self-lockout.md) | An admin cannot deactivate the own account | approved |
| [F/administration/admin/000371](requirements/functional/administration/admin/000371_repin-by-key.md) | A flow save moves Anträge by state key | approved |
| [F/administration/admin/000383](requirements/functional/administration/admin/000383_revert-forward.md) | A config revert goes forward | approved |
| [F/administration/admin/000405](requirements/functional/administration/admin/000405_revert-permissions.md) | A revert needs the right of the original change | approved |
| [F/administration/admin/000638](requirements/functional/administration/admin/000638_admin-menu-icons.md) | Each entry of the admin menu has its own icon | approved |
| [F/administration/audit/000291](requirements/functional/administration/audit/000291_record-in-tx.md) | An audit entry is written in the same transaction | approved |
| [F/administration/audit/000292](requirements/functional/administration/audit/000292_chain-check.md) | The audit chain is checked every night | approved |
| [F/administration/audit/000293](requirements/functional/administration/audit/000293_three-permissions.md) | Read, check and revert are separate permissions | approved |
| [F/administration/audit/000294](requirements/functional/administration/audit/000294_resolved-names.md) | The audit log shows names | approved |
| [F/administration/backups/000300](requirements/functional/administration/backups/000300_web-ui.md) | Backups run from the web UI | approved |
| [F/administration/backups/000301](requirements/functional/administration/backups/000301_archive-content.md) | A backup holds the database and the attachments, encrypted | approved |
| [F/administration/backups/000302](requirements/functional/administration/backups/000302_pre-restore.md) | A restore first saves the current state | approved |
| [F/administration/backups/000303](requirements/functional/administration/backups/000303_confirm-restore.md) | A restore needs the word RESTORE | approved |
| [F/administration/backups/000465](requirements/functional/administration/backups/000465_backup-retention.md) | Backups keep a fixed count and cap uploads | approved |
| [F/administration/files/000167](requirements/functional/administration/files/000167_ascii-names.md) | Storage names replace non-ASCII characters | approved |
| [F/administration/files/000168](requirements/functional/administration/files/000168_confirm-delete.md) | Every attachment delete is confirmed | approved |
| [F/administration/files/000169](requirements/functional/administration/files/000169_drop-files.md) | Attachments can be dropped | approved |
| [F/administration/files/000339](requirements/functional/administration/files/000339_size-limit.md) | An attachment is at most 10 MiB | approved |
| [F/administration/files/000340](requirements/functional/administration/files/000340_quarantine.md) | An unscanned file is not served | approved |
| [F/administration/files/000341](requirements/functional/administration/files/000341_file-access.md) | File access follows the access to the Antrag | approved |
| [F/administration/files/000342](requirements/functional/administration/files/000342_drafts.md) | Wizard uploads are drafts | approved |
| [F/administration/files/000464](requirements/functional/administration/files/000464_draft-caps.md) | Wizard drafts are capped and expire | approved |
| [F/administration/privacy/000457](requirements/functional/administration/privacy/000457_erasure-request.md) | An applicant can request the erasure of an Antrag | approved |
| [F/administration/privacy/000458](requirements/functional/administration/privacy/000458_data-export.md) | The data export is an audited XLSX | approved |
| [F/administration/translations/000136](requirements/functional/administration/translations/000136_all-languages-editable.md) | Every i18n text is editable in English too | approved |
| [F/administration/translations/000336](requirements/functional/administration/translations/000336_catalog-source.md) | The frontend catalog is the source of UI texts | approved |
| [F/administration/translations/000337](requirements/functional/administration/translations/000337_language-lifecycle.md) | A new language starts inactive | approved |
| [F/administration/translations/000338](requirements/functional/administration/translations/000338_extra-language-scope.md) | A text without the extra language falls back to English | approved |
| [F/applications/applications/000121](requirements/functional/applications/applications/000121_apply-buttons.md) | The wizard submit button is Antrag anlegen | approved |
| [F/applications/applications/000122](requirements/functional/applications/applications/000122_on-behalf-capture.md) | An Antrag can be captured on behalf of a person | approved |
| [F/applications/applications/000123](requirements/functional/applications/applications/000123_received-on.md) | The received date is at most 365 days back | approved |
| [F/applications/applications/000124](requirements/functional/applications/applications/000124_match-by-email.md) | A guest e-mail of an active account becomes that account | approved |
| [F/applications/applications/000125](requirements/functional/applications/applications/000125_unconfirmed-guest.md) | An unconfirmed guest Antrag rests | approved |
| [F/applications/applications/000126](requirements/functional/applications/applications/000126_transition-notes.md) | Transition notes are visible to the applicant | approved |
| [F/applications/applications/000127](requirements/functional/applications/applications/000127_applicant-view.md) | The applicant sees the Gremium as actor | approved |
| [F/applications/applications/000128](requirements/functional/applications/applications/000128_timeline-vote-link.md) | The timeline links the deciding vote | approved |
| [F/applications/applications/000129](requirements/functional/applications/applications/000129_keep-open-after-transition.md) | An Antrag stays open after a transition in Aufgaben | approved |
| [F/applications/applications/000130](requirements/functional/applications/applications/000130_pii-fields.md) | PII fields need application.read | approved |
| [F/applications/applications/000131](requirements/functional/applications/applications/000131_comments-button.md) | Comments open from a header button | approved |
| [F/applications/applications/000132](requirements/functional/applications/applications/000132_approval-with-deviation.md) | An approval can deviate | approved |
| [F/applications/applications/000374](requirements/functional/applications/applications/000374_pinned-validation.md) | Antrag data is checked against its pinned form | approved |
| [F/applications/applications/000375](requirements/functional/applications/applications/000375_versioned-edit.md) | An edit is versioned and audited without values | approved |
| [F/applications/applications/000376](requirements/functional/applications/applications/000376_anonymize-all.md) | An anonymization removes every copy of personal data | approved |
| [F/applications/applications/000377](requirements/functional/applications/applications/000377_state-since.md) | The time in a state is shown | approved |
| [F/applications/applications/000441](requirements/functional/applications/applications/000441_capture-mail.md) | The applicant gets a mail about a captured Antrag | approved |
| [F/applications/applications/000442](requirements/functional/applications/applications/000442_capture-detail.md) | The detail names who captured the Antrag | approved |
| [F/applications/applications/000542](requirements/functional/applications/applications/000542_one-predecessor.md) | An Antrag can have one Vorgänger | approved |
| [F/applications/applications/000543](requirements/functional/applications/applications/000543_predecessor-picker-scope.md) | The Vorgänger picker lists only readable Anträge | approved |
| [F/applications/applications/000544](requirements/functional/applications/applications/000544_predecessor-prefill.md) | A Vorgänger chosen at creation prefills the form | approved |
| [F/applications/applications/000545](requirements/functional/applications/applications/000545_link-later.md) | A Vorgänger linked later adds only the link | approved |
| [F/applications/applications/000546](requirements/functional/applications/applications/000546_detail-links.md) | The detail shows Vorgänger and Folgeanträge | approved |
| [F/applications/applications/000588](requirements/functional/applications/applications/000588_my-applications.md) | Meine Anträge lists the Anträge of the address | approved |
| [F/applications/dashboard/000421](requirements/functional/applications/dashboard/000421_dashboard.md) | The start page is a work list with a side sheet | approved |
| [F/applications/dashboard/000550](requirements/functional/applications/dashboard/000550_start-due-cards.md) | Start shows the due cards of the person | approved |
| [F/applications/dashboard/000650](requirements/functional/applications/dashboard/000650_start-apply-button-tab-line.md) | Antrag stellen stands in the tab line of the desktop start page | approved |
| [F/applications/flow/000137](requirements/functional/applications/flow/000137_flow-auto-layout.md) | The flow editor lays out automatically | approved |
| [F/applications/flow/000227](requirements/functional/applications/flow/000227_one-active-flow.md) | There is one active flow | approved |
| [F/applications/flow/000228](requirements/functional/applications/flow/000228_state-kinds.md) | A state is normal or a vote state | approved |
| [F/applications/flow/000229](requirements/functional/applications/flow/000229_guard-whitelist.md) | Guards and actions come from a whitelist | approved |
| [F/applications/flow/000230](requirements/functional/applications/flow/000230_actor-gates-manual.md) | Actor gates apply only to manual transitions | approved |
| [F/applications/flow/000231](requirements/functional/applications/flow/000231_compare-fails-closed.md) | A guard on a field fails closed | approved |
| [F/applications/flow/000232](requirements/functional/applications/flow/000232_optimistic-lock.md) | A transition fires only from the current state | approved |
| [F/applications/flow/000233](requirements/functional/applications/flow/000233_branch-by-vote-only.md) | Only the vote result fires a vote branch | approved |
| [F/applications/flow/000234](requirements/functional/applications/flow/000234_no-auto-exit-from-vote.md) | No automatic exit from a vote state | approved |
| [F/applications/flow/000235](requirements/functional/applications/flow/000235_leave-cancels-votes.md) | Leaving a vote state cancels its votes | approved |
| [F/applications/flow/000236](requirements/functional/applications/flow/000236_status-event.md) | A status change is recorded | approved |
| [F/applications/flow/000237](requirements/functional/applications/flow/000237_actions-after-commit.md) | Actions run after the commit and never undo it | approved |
| [F/applications/flow/000238](requirements/functional/applications/flow/000238_one-dispatcher.md) | Every fire path runs the full action chain | approved |
| [F/applications/flow/000239](requirements/functional/applications/flow/000239_add-to-meeting.md) | A transition into a vote state can add the Antrag to a meeting | approved |
| [F/applications/flow/000240](requirements/functional/applications/flow/000240_implicit-mails.md) | Every state change sends the implicit mails | approved |
| [F/applications/flow/000241](requirements/functional/applications/flow/000241_minute-cron.md) | The minute cron advances and cleans up | approved |
| [F/applications/flow/000242](requirements/functional/applications/flow/000242_revert-status.md) | A status revert works only from the reverted state | approved |
| [F/applications/flow/000243](requirements/functional/applications/flow/000243_vote-gremium-snapshot.md) | The vote Gremium is a snapshot | approved |
| [F/applications/flow/000244](requirements/functional/applications/flow/000244_budget-locked-by-vote.md) | The cost centre is locked during a budget vote | approved |
| [F/applications/flow/000245](requirements/functional/applications/flow/000245_applicant-transitions.md) | Applicant transitions need actorIsApplicant | approved |
| [F/applications/flow/000459](requirements/functional/applications/flow/000459_vote-state-branches.md) | A vote state has exactly one pass and one fail branch | approved |
| [F/applications/flow/000571](requirements/functional/applications/flow/000571_approved-state.md) | A flow state can mark an Antrag as approved or denied | approved |
| [F/applications/flow/000572](requirements/functional/applications/flow/000572_approved-amount-from-state.md) | The approved amount follows the approved state | approved |
| [F/applications/forms/000133](requirements/functional/applications/forms/000133_positions-shape.md) | A positions answer has label and offers | approved |
| [F/applications/forms/000134](requirements/functional/applications/forms/000134_offer-limits.md) | Offer counts have limits | approved |
| [F/applications/forms/000135](requirements/functional/applications/forms/000135_funding-field.md) | The requested funding is separate from the costs | approved |
| [F/applications/forms/000280](requirements/functional/applications/forms/000280_pin-not-mutate.md) | A form version is never changed | approved |
| [F/applications/forms/000281](requirements/functional/applications/forms/000281_inactive-type.md) | A type without an active form is closed | approved |
| [F/applications/forms/000282](requirements/functional/applications/forms/000282_system-title.md) | Every form has a title field | approved |
| [F/applications/forms/000283](requirements/functional/applications/forms/000283_sections.md) | Section fields make wizard steps | approved |
| [F/applications/forms/000284](requirements/functional/applications/forms/000284_definition-check.md) | A form definition is checked at save time | approved |
| [F/applications/forms/000285](requirements/functional/applications/forms/000285_jsonlogic-whitelist.md) | JsonLogic uses a whitelist | approved |
| [F/applications/forms/000286](requirements/functional/applications/forms/000286_all-errors.md) | Answer validation reports all errors | approved |
| [F/applications/forms/000287](requirements/functional/applications/forms/000287_pattern-limits.md) | A pattern check cannot hang | approved |
| [F/applications/forms/000288](requirements/functional/applications/forms/000288_finite-numbers.md) | Numbers are finite decimals | approved |
| [F/applications/forms/000289](requirements/functional/applications/forms/000289_form-revision.md) | A form change is versioned and audited | approved |
| [F/applications/forms/000471](requirements/functional/applications/forms/000471_type-retention.md) | Antrag types can keep their own retention | approved |
| [F/collaboration/notifications/000151](requirements/functional/collaboration/notifications/000151_task-mail-recipients.md) | Task mails go only to who can act | approved |
| [F/collaboration/notifications/000152](requirements/functional/collaboration/notifications/000152_team-mails-opt-in.md) | Team mails about Anträge are off by default | approved |
| [F/collaboration/notifications/000153](requirements/functional/collaboration/notifications/000153_sandboxed-templates.md) | Mail placeholders use camelCase | approved |
| [F/collaboration/notifications/000306](requirements/functional/collaboration/notifications/000306_mail-queue.md) | Mails go through the queue | approved |
| [F/collaboration/notifications/000307](requirements/functional/collaboration/notifications/000307_mail-once.md) | A mail is sent once | approved |
| [F/collaboration/notifications/000308](requirements/functional/collaboration/notifications/000308_mail-link.md) | Every mail links its element | approved |
| [F/collaboration/notifications/000309](requirements/functional/collaboration/notifications/000309_mail-preferences.md) | A person controls their mail kinds | approved |
| [F/collaboration/notifications/000310](requirements/functional/collaboration/notifications/000310_mail-languages.md) | Mail texts are in German and English | approved |
| [F/collaboration/notifications/000312](requirements/functional/collaboration/notifications/000312_task-reminders.md) | Task reminders follow the admin setting | approved |
| [F/collaboration/search/000328](requirements/functional/collaboration/search/000328_reuse-gates.md) | Search reuses the gate of each module | approved |
| [F/collaboration/search/000329](requirements/functional/collaboration/search/000329_query-length.md) | Search needs two characters | approved |
| [F/collaboration/search/000330](requirements/functional/collaboration/search/000330_per-kind-cap.md) | Search shows 5 hits per kind | approved |
| [F/collaboration/tickets/000150](requirements/functional/collaboration/tickets/000150_public-report.md) | Anyone can report a help ticket | approved |
| [F/collaboration/tickets/000313](requirements/functional/collaboration/tickets/000313_reporter-view.md) | A reporter account follows its tickets | approved |
| [F/collaboration/tickets/000314](requirements/functional/collaboration/tickets/000314_team-work.md) | The team works on tickets | approved |
| [F/collaboration/tickets/000315](requirements/functional/collaboration/tickets/000315_sender-block.md) | A sender can be blocked | approved |
| [F/collaboration/tickets/000316](requirements/functional/collaboration/tickets/000316_ticket-retention.md) | Closed tickets are anonymized after the retention time | approved |
| [F/collaboration/tickets/000317](requirements/functional/collaboration/tickets/000317_context-url.md) | A ticket context keeps only platform pages | approved |
| [F/collaboration/todos/000147](requirements/functional/collaboration/todos/000147_board-kinds.md) | Boards per Gremium, per person and per team | approved |
| [F/collaboration/todos/000148](requirements/functional/collaboration/todos/000148_move-sheet.md) | One move sheet | approved |
| [F/collaboration/todos/000149](requirements/functional/collaboration/todos/000149_no-status-sync.md) | No status sync between ticket and card | approved |
| [F/collaboration/todos/000318](requirements/functional/collaboration/todos/000318_board-rights.md) | Board rights depend on the board kind | approved |
| [F/collaboration/todos/000319](requirements/functional/collaboration/todos/000319_unreadable-404.md) | An unreadable board is not found | approved |
| [F/collaboration/todos/000320](requirements/functional/collaboration/todos/000320_members-only.md) | Only members are assigned or mentioned | approved |
| [F/collaboration/todos/000321](requirements/functional/collaboration/todos/000321_no-transfer-to-personal.md) | A shared card does not move to a personal board | approved |
| [F/collaboration/todos/000322](requirements/functional/collaboration/todos/000322_transfer-rules.md) | A transfer keeps what the target supports | approved |
| [F/collaboration/todos/000323](requirements/functional/collaboration/todos/000323_done-column.md) | The done column sets the completion time | approved |
| [F/collaboration/todos/000324](requirements/functional/collaboration/todos/000324_live-pings.md) | Boards update live | approved |
| [F/collaboration/todos/000325](requirements/functional/collaboration/todos/000325_todo-mails.md) | To-do mails go to assignees | approved |
| [F/collaboration/todos/000326](requirements/functional/collaboration/todos/000326_card-on-agenda.md) | A card can go on the agenda | approved |
| [F/collaboration/todos/000327](requirements/functional/collaboration/todos/000327_link-access.md) | A link shows nothing without access | replaced |
| [F/collaboration/todos/000443](requirements/functional/collaboration/todos/000443_board-columns.md) | A board has one done column | approved |
| [F/collaboration/todos/000444](requirements/functional/collaboration/todos/000444_boards-tab.md) | The to-do tab is Boards | approved |
| [F/collaboration/todos/000467](requirements/functional/collaboration/todos/000467_card-version-conflict.md) | Concurrent card edits give 409 | approved |
| [F/collaboration/todos/000478](requirements/functional/collaboration/todos/000478_event-card.md) | An Event is a card with event data | approved |
| [F/collaboration/todos/000479](requirements/functional/collaboration/todos/000479_event-totals.md) | An Event shows the totals of its links | approved |
| [F/collaboration/todos/000480](requirements/functional/collaboration/todos/000480_event-picker.md) | A Buchung can name its Event | approved |
| [F/collaboration/todos/000481](requirements/functional/collaboration/todos/000481_one-event-per-element.md) | An Antrag or a Buchung belongs to at most one Event | approved |
| [F/collaboration/todos/000482](requirements/functional/collaboration/todos/000482_event-decisions.md) | An Event lists its decisions | approved |
| [F/collaboration/todos/000483](requirements/functional/collaboration/todos/000483_event-series.md) | An Event can belong to a series | approved |
| [F/collaboration/todos/000484](requirements/functional/collaboration/todos/000484_next-edition.md) | Folgeveranstaltung anlegen copies the plan, not the facts | approved |
| [F/collaboration/todos/000485](requirements/functional/collaboration/todos/000485_events-findable.md) | Archived Events stay findable | approved |
| [F/collaboration/todos/000486](requirements/functional/collaboration/todos/000486_event-calendar.md) | An Event with a start is in the calendar | approved |
| [F/collaboration/todos/000487](requirements/functional/collaboration/todos/000487_card-grants-read.md) | A card gives read access to its links | approved |
| [F/collaboration/todos/000488](requirements/functional/collaboration/todos/000488_to-do-becomes-event-once.md) | A to-do becomes an Event only once | approved |
| [F/collaboration/todos/000489](requirements/functional/collaboration/todos/000489_links-are-called-linked.md) | The cards of an element are under Verknüpft | approved |
| [F/collaboration/todos/000547](requirements/functional/collaboration/todos/000547_create-card-from-element.md) | A card is created from the detail of an element | approved |
| [F/collaboration/todos/000548](requirements/functional/collaboration/todos/000548_link-card-from-element.md) | An element is linked to a card from its detail | approved |
| [F/collaboration/todos/000549](requirements/functional/collaboration/todos/000549_due-cards-in-calendar.md) | A due card of a person is in their calendar | approved |
| [F/collaboration/todos/000551](requirements/functional/collaboration/todos/000551_meeting-gremium-linked.md) | A meeting shows its linked cards and a Gremium its board | approved |
| [F/collaboration/todos/000552](requirements/functional/collaboration/todos/000552_cost-centre-link.md) | A card can link a cost centre | approved |
| [F/collaboration/todos/000553](requirements/functional/collaboration/todos/000553_card-to-agenda.md) | A card is put on the agenda from the card | approved |
| [F/collaboration/todos/000554](requirements/functional/collaboration/todos/000554_duplicate-card.md) | A card can be duplicated | approved |
| [F/collaboration/todos/000555](requirements/functional/collaboration/todos/000555_item-to-card.md) | A checklist item becomes a card | approved |
| [F/collaboration/todos/000573](requirements/functional/collaboration/todos/000573_card-links-both-ways.md) | A link between two cards shows on both cards | approved |
| [F/collaboration/todos/000735](requirements/functional/collaboration/todos/000735_termin-link.md) | A card can link a Termin | approved |
| [F/collaboration/todos/000736](requirements/functional/collaboration/todos/000736_event-times.md) | The start and the end of an Event can have a time | approved |
| [F/finance/budget/000138](requirements/functional/finance/budget/000138_cost-centre-picker.md) | The cost centre pickers are fixed | approved |
| [F/finance/budget/000139](requirements/functional/finance/budget/000139_close-fiscal-year.md) | A fiscal year closes and reopens | approved |
| [F/finance/budget/000140](requirements/functional/finance/budget/000140_default-fiscal-year.md) | The default fiscal year holds today | approved |
| [F/finance/budget/000141](requirements/functional/finance/budget/000141_fiscal-year-delete.md) | A fiscal year in use is not deleted | approved |
| [F/finance/budget/000142](requirements/functional/finance/budget/000142_duplicate-booking.md) | A booking can be duplicated | approved |
| [F/finance/budget/000143](requirements/functional/finance/budget/000143_transfer-kind.md) | A transfer is a kind in the Art filter | approved |
| [F/finance/budget/000144](requirements/functional/finance/budget/000144_cost-centre-items.md) | The cost centre card lists Anträge and bookings | approved |
| [F/finance/budget/000145](requirements/functional/finance/budget/000145_revert-keeps-invoice.md) | A reverted booking keeps the invoice status | replaced |
| [F/finance/budget/000146](requirements/functional/finance/budget/000146_legend.md) | The budget legend matches the drawing | approved |
| [F/finance/budget/000246](requirements/functional/finance/budget/000246_path-key.md) | A cost centre has a stable path key | approved |
| [F/finance/budget/000247](requirements/functional/finance/budget/000247_roll-up.md) | Allocation flows down, consumption flows up | approved |
| [F/finance/budget/000248](requirements/functional/finance/budget/000248_available-formula.md) | The available amount can be negative | approved |
| [F/finance/budget/000249](requirements/functional/finance/budget/000249_state-classes.md) | Flow states classify the amount of an Antrag | replaced |
| [F/finance/budget/000250](requirements/functional/finance/budget/000250_decision-gremium.md) | The deciding Gremium is inherited | approved |
| [F/finance/budget/000251](requirements/functional/finance/budget/000251_fiscal-year-bounds.md) | A fiscal year starts on a day from 1 to 28 | approved |
| [F/finance/budget/000252](requirements/functional/finance/budget/000252_closed-year-refuses.md) | A closed fiscal year refuses money changes | approved |
| [F/finance/budget/000253](requirements/functional/finance/budget/000253_euro-only.md) | Amounts are euro only | approved |
| [F/finance/budget/000254](requirements/functional/finance/budget/000254_delete-in-use.md) | A cost centre in use is not deleted | approved |
| [F/finance/budget/000255](requirements/functional/finance/budget/000255_money-audit.md) | Every money change is audited and revertable | approved |
| [F/finance/budget/000256](requirements/functional/finance/budget/000256_transfer-pair.md) | A transfer is a pair of bookings | approved |
| [F/finance/budget/000257](requirements/functional/finance/budget/000257_income-no-application.md) | An income never belongs to an Antrag | approved |
| [F/finance/budget/000258](requirements/functional/finance/budget/000258_sub-bookings.md) | A booking can have sub-bookings | approved |
| [F/finance/budget/000259](requirements/functional/finance/budget/000259_gremium-view.md) | Gremium members see their cost centres | approved |
| [F/finance/budget/000629](requirements/functional/finance/budget/000629_booking-lowers-bound.md) | A booking lowers the bound amount of its Antrag | approved |
| [F/finance/invoices/000260](requirements/functional/finance/invoices/000260_invoice-bookings.md) | An invoice is a document with many bookings | approved |
| [F/finance/invoices/000261](requirements/functional/finance/invoices/000261_paid-by-user.md) | Only a user sets an invoice to paid | approved |
| [F/finance/invoices/000262](requirements/functional/finance/invoices/000262_invoice-segments.md) | The invoice list has four segments | approved |
| [F/finance/invoices/000263](requirements/functional/finance/invoices/000263_zugferd-import.md) | A ZUGFeRD invoice fills the form | approved |
| [F/integrations/external/000176](requirements/functional/integrations/external/000176_optional.md) | Integrations are optional | approved |
| [F/integrations/external/000177](requirements/functional/integrations/external/000177_preview-access.md) | A link preview uses the access of the viewer | approved |
| [F/integrations/mcp/000174](requirements/functional/integrations/mcp/000174_acts-as-user.md) | The MCP server acts as the logged-in user | approved |
| [F/integrations/mcp/000272](requirements/functional/integrations/mcp/000272_token-scope.md) | An agent token has a scope and a lifetime | approved |
| [F/integrations/mcp/000273](requirements/functional/integrations/mcp/000273_forbidden-permissions.md) | An agent never casts a ballot or merges accounts | approved |
| [F/integrations/mcp/000274](requirements/functional/integrations/mcp/000274_revoke-grants.md) | Tokens can be revoked | approved |
| [F/integrations/mcp/000385](requirements/functional/integrations/mcp/000385_version-bump.md) | The MCP version moves with its tools | replaced |
| [F/integrations/mcp/000386](requirements/functional/integrations/mcp/000386_no-ballot-tool.md) | The MCP has no ballot tool | approved |
| [F/integrations/mcp/000387](requirements/functional/integrations/mcp/000387_idp-roles-read-only.md) | Memberships and roles are read-only in the MCP | approved |
| [F/integrations/mcp/000462](requirements/functional/integrations/mcp/000462_forbidden-permissions.md) | No agent token gets a human-only permission | approved |
| [F/integrations/webhooks/000298](requirements/functional/integrations/webhooks/000298_retry.md) | A failed delivery is retried with backoff | approved |
| [F/integrations/webhooks/000299](requirements/functional/integrations/webhooks/000299_idempotent-delivery.md) | A delivery runs once per key | approved |
| [F/integrations/webhooks/000402](requirements/functional/integrations/webhooks/000402_flow-action-only.md) | A webhook fires only through a flow action | approved |
| [F/integrations/webhooks/000403](requirements/functional/integrations/webhooks/000403_delete-webhook.md) | A webhook can be deleted | approved |
| [F/meetings/calendar/000331](requirements/functional/meetings/calendar/000331_feed.md) | Each person has a calendar feed | approved |
| [F/meetings/calendar/000332](requirements/functional/meetings/calendar/000332_feed-404.md) | A wrong feed token is not found | approved |
| [F/meetings/calendar/000333](requirements/functional/meetings/calendar/000333_event-defaults.md) | A calendar event has a reminder | approved |
| [F/meetings/calendar/000710](requirements/functional/meetings/calendar/000710_calendar-tab.md) | The Kalender is its own tab | approved |
| [F/meetings/calendar/000711](requirements/functional/meetings/calendar/000711_calendar-sources.md) | The Kalender shows five kinds of entries | approved |
| [F/meetings/calendar/000712](requirements/functional/meetings/calendar/000712_calendar-due-cards.md) | The Kalender shows every readable card with a due date | approved |
| [F/meetings/calendar/000713](requirements/functional/meetings/calendar/000713_calendar-filters.md) | The Kalender filters by kind and by Gremium | approved |
| [F/meetings/calendar/000714](requirements/functional/meetings/calendar/000714_calendar-entry-opens.md) | An entry opens its own element | approved |
| [F/meetings/calendar/000715](requirements/functional/meetings/calendar/000715_termin.md) | A Termin has a title and a time span | approved |
| [F/meetings/calendar/000716](requirements/functional/meetings/calendar/000716_termin-create.md) | Each signed-in person creates a Termin | approved |
| [F/meetings/calendar/000717](requirements/functional/meetings/calendar/000717_termin-invitations.md) | A Termin invites Gremien and persons | approved |
| [F/meetings/calendar/000718](requirements/functional/meetings/calendar/000718_termin-visibility.md) | Only the creator and the invited persons read a Termin | approved |
| [F/meetings/calendar/000719](requirements/functional/meetings/calendar/000719_termin-answers.md) | An invited person answers a Termin | approved |
| [F/meetings/calendar/000720](requirements/functional/meetings/calendar/000720_termin-mails.md) | An invited person gets a mail | approved |
| [F/meetings/calendar/000721](requirements/functional/meetings/calendar/000721_external-calendars.md) | An admin subscribes an external calendar | approved |
| [F/meetings/calendar/000722](requirements/functional/meetings/calendar/000722_external-fetch.md) | The worker fetches external calendars | approved |
| [F/meetings/calendar/000723](requirements/functional/meetings/calendar/000723_external-entries.md) | External entries are plain and read-only | approved |
| [F/meetings/calendar/000724](requirements/functional/meetings/calendar/000724_feed-termine-external.md) | The personal feed holds Termine and external entries | approved |
| [F/meetings/calendar/000725](requirements/functional/meetings/calendar/000725_termin-privacy.md) | Termine are part of the privacy export and erasure | approved |
| [F/meetings/calendar/000726](requirements/functional/meetings/calendar/000726_calendar-phone.md) | The Kalender on the phone is a list of days | approved |
| [F/meetings/calendar/000727](requirements/functional/meetings/calendar/000727_calendar-search.md) | The Kalender search jumps to the hit | approved |
| [F/meetings/calendar/000728](requirements/functional/meetings/calendar/000728_calendar-week-view.md) | The desktop Kalender has a week and a month view | approved |
| [F/meetings/calendar/000729](requirements/functional/meetings/calendar/000729_external-calendars-admin-page.md) | The admin page Kalender lists and edits the external calendars | approved |
| [F/meetings/calendar/000730](requirements/functional/meetings/calendar/000730_public-termin.md) | A Termin can be public | approved |
| [F/meetings/calendar/000731](requirements/functional/meetings/calendar/000731_public-calendar-page.md) | The public calendar page shows the public entries | approved |
| [F/meetings/calendar/000732](requirements/functional/meetings/calendar/000732_public-meetings.md) | The public calendar shows the meetings of Gremien with public protocols | approved |
| [F/meetings/calendar/000733](requirements/functional/meetings/calendar/000733_public-ics-feed.md) | The public calendar has an ICS feed without a token | approved |
| [F/meetings/calendar/000734](requirements/functional/meetings/calendar/000734_public-calendar-noindex.md) | The public calendar is not indexed | approved |
| [F/meetings/calendar/000737](requirements/functional/meetings/calendar/000737_event-as-termin.md) | The Kalender shows an Event like a Termin | approved |
| [F/meetings/calendar/000738](requirements/functional/meetings/calendar/000738_termin-invite-person-search.md) | The invitation search finds each active account by name | approved |
| [F/meetings/calendar/000740](requirements/functional/meetings/calendar/000740_termin-open-answers.md) | The answer list of a Termin names the invited persons without an answer | approved |
| [F/meetings/calendar/000742](requirements/functional/meetings/calendar/000742_termin-invite-search-rows.md) | The invitation search of a Termin shows its hits as rows with an avatar | approved |
| [F/meetings/calendar/000744](requirements/functional/meetings/calendar/000744_week-span-blocks.md) | A timed entry over several days is a block on each of its days in the week view | approved |
| [F/meetings/delegations/000110](requirements/functional/meetings/delegations/000110_per-gremium.md) | Vote delegation is a Gremium setting | approved |
| [F/meetings/delegations/000111](requirements/functional/meetings/delegations/000111_delegation-blocks-presence.md) | A member with an active delegation is not present | approved |
| [F/meetings/delegations/000112](requirements/functional/meetings/delegations/000112_one-pool.md) | The substitute pool is the only substitute rule | approved |
| [F/meetings/delegations/000113](requirements/functional/meetings/delegations/000113_pool-seats.md) | A pool substitute takes a free seat | approved |
| [F/meetings/delegations/000114](requirements/functional/meetings/delegations/000114_pool-read-scope.md) | Pool substitutes read like members | approved |
| [F/meetings/delegations/000362](requirements/functional/meetings/delegations/000362_meeting-bound.md) | A delegation belongs to one meeting | approved |
| [F/meetings/delegations/000363](requirements/functional/meetings/delegations/000363_moves-vote.md) | A delegation moves the vote | approved |
| [F/meetings/delegations/000364](requirements/functional/meetings/delegations/000364_eligible-delegator.md) | Only an eligible member delegates | approved |
| [F/meetings/delegations/000365](requirements/functional/meetings/delegations/000365_no-chains.md) | Delegations do not chain | approved |
| [F/meetings/delegations/000366](requirements/functional/meetings/delegations/000366_deadline.md) | A delegation has a deadline | approved |
| [F/meetings/delegations/000367](requirements/functional/meetings/delegations/000367_roster-privacy.md) | Roster names are visible only to the Gremium | approved |
| [F/meetings/delegations/000420](requirements/functional/meetings/delegations/000420_lead-enters-substitute.md) | The lead can enter a pool substitute | approved |
| [F/meetings/delegations/000445](requirements/functional/meetings/delegations/000445_pool-seat-cap.md) | Pool seats never exceed the member seats | approved |
| [F/meetings/delegations/000446](requirements/functional/meetings/delegations/000446_pool-seat-free.md) | The member frees the pool seat | approved |
| [F/meetings/delegations/000447](requirements/functional/meetings/delegations/000447_pool-seat-live.md) | Pool seats need only a live meeting | approved |
| [F/meetings/delegations/000461](requirements/functional/meetings/delegations/000461_external-delegates.md) | External delegates need a Gremium switch | approved |
| [F/meetings/meetings/000092](requirements/functional/meetings/meetings/000092_open-window.md) | A meeting opens in a configured window | approved |
| [F/meetings/meetings/000093](requirements/functional/meetings/meetings/000093_state-order.md) | Meeting states move only forward | approved |
| [F/meetings/meetings/000094](requirements/functional/meetings/meetings/000094_close-with-open-vote.md) | A meeting with an open vote does not close | approved |
| [F/meetings/meetings/000095](requirements/functional/meetings/meetings/000095_prepare-before-open.md) | The protocol and votes can be prepared before the open | approved |
| [F/meetings/meetings/000096](requirements/functional/meetings/meetings/000096_no-prep-page.md) | There is no preparation page | approved |
| [F/meetings/meetings/000097](requirements/functional/meetings/meetings/000097_delete-removes-votes.md) | A meeting delete removes its votes | approved |
| [F/meetings/meetings/000098](requirements/functional/meetings/meetings/000098_agenda-changes.md) | Agenda changes only while planned or live | approved |
| [F/meetings/meetings/000099](requirements/functional/meetings/meetings/000099_top-text-editable.md) | A TOP text is editable until the protocol is final | approved |
| [F/meetings/meetings/000100](requirements/functional/meetings/meetings/000100_agenda-subtitle.md) | An agenda row has a subtitle only for an Antrag | approved |
| [F/meetings/meetings/000101](requirements/functional/meetings/meetings/000101_application-top-row.md) | A TOP with an Antrag shows the Antrag as its first row | approved |
| [F/meetings/meetings/000102](requirements/functional/meetings/meetings/000102_top-attachments-internal.md) | TOP attachments are internal | approved |
| [F/meetings/meetings/000103](requirements/functional/meetings/meetings/000103_attendance.md) | Lead-set attendance wins | approved |
| [F/meetings/meetings/000104](requirements/functional/meetings/meetings/000104_qr-only-without-quorum.md) | Public participation only without quorum | approved |
| [F/meetings/meetings/000105](requirements/functional/meetings/meetings/000105_admit-guests.md) | The meeting lead admits each guest | approved |
| [F/meetings/meetings/000106](requirements/functional/meetings/meetings/000106_guest-modes.md) | Guests vote or only watch | approved |
| [F/meetings/meetings/000107](requirements/functional/meetings/meetings/000107_guest-view.md) | Guests see public TOPs only | approved |
| [F/meetings/meetings/000108](requirements/functional/meetings/meetings/000108_guest-pseudonyms.md) | Guest names become pseudonyms | approved |
| [F/meetings/meetings/000109](requirements/functional/meetings/meetings/000109_list-and-calendar.md) | The meeting list has a list and a calendar | replaced |
| [F/meetings/meetings/000345](requirements/functional/meetings/meetings/000345_gremium-rights.md) | Meeting rights are per Gremium | approved |
| [F/meetings/meetings/000346](requirements/functional/meetings/meetings/000346_open-needs-keeper.md) | A meeting opens only with a protokollant | approved |
| [F/meetings/meetings/000347](requirements/functional/meetings/meetings/000347_keeper-periods.md) | A keeper period follows the current TOP | approved |
| [F/meetings/meetings/000348](requirements/functional/meetings/meetings/000348_vote-needs-state.md) | A vote on an Antrag needs the matching vote state | approved |
| [F/meetings/meetings/000349](requirements/functional/meetings/meetings/000349_aggregates-only.md) | Live data shows only aggregates | approved |
| [F/meetings/meetings/000351](requirements/functional/meetings/meetings/000351_join-code.md) | A join code is short and unambiguous | approved |
| [F/meetings/meetings/000353](requirements/functional/meetings/meetings/000353_guest-vote.md) | A vote with guests has no quorum | approved |
| [F/meetings/meetings/000418](requirements/functional/meetings/meetings/000418_calendar-popover.md) | The calendar subscription is on Sitzungen | replaced |
| [F/meetings/meetings/000419](requirements/functional/meetings/meetings/000419_gremium-delete.md) | A Gremium delete deletes its meetings | approved |
| [F/meetings/meetings/000448](requirements/functional/meetings/meetings/000448_vote-deleted-timeline.md) | The timeline shows a vote deleted with its meeting | approved |
| [F/meetings/meetings/000449](requirements/functional/meetings/meetings/000449_delete-vote-count.md) | A meeting delete names the vote count | approved |
| [F/meetings/meetings/000450](requirements/functional/meetings/meetings/000450_no-global-meeting-key.md) | No global key manages meetings | approved |
| [F/meetings/meetings/000574](requirements/functional/meetings/meetings/000574_live-viewers-avatar.md) | A live viewer shows with the own avatar | approved |
| [F/meetings/meetings/000607](requirements/functional/meetings/meetings/000607_agenda-row-no-drag-handle.md) | An agenda row shows no drag handle | approved |
| [F/meetings/meetings/000610](requirements/functional/meetings/meetings/000610_attendance-month-without-meeting.md) | A month without a meeting is a narrow column with a dash | approved |
| [F/meetings/meetings/000611](requirements/functional/meetings/meetings/000611_attendance-cell-badges.md) | An attendance cell holds its badges | approved |
| [F/meetings/protocols/000115](requirements/functional/meetings/protocols/000115_keeper-permission.md) | The keeper holds protocol.write | approved |
| [F/meetings/protocols/000116](requirements/functional/meetings/protocols/000116_finalize.md) | Finalize needs a closed meeting and protocol.finalize | approved |
| [F/meetings/protocols/000117](requirements/functional/meetings/protocols/000117_delete-draft-only.md) | Only a draft protocol is deleted | approved |
| [F/meetings/protocols/000118](requirements/functional/meetings/protocols/000118_pdf-name.md) | The PDF is named after the meeting | approved |
| [F/meetings/protocols/000119](requirements/functional/meetings/protocols/000119_signatures-one-page.md) | The signature block stays on one page | approved |
| [F/meetings/protocols/000120](requirements/functional/meetings/protocols/000120_election-ranking.md) | An election shows a ranking | approved |
| [F/meetings/protocols/000354](requirements/functional/meetings/protocols/000354_built-from-tops.md) | The protocol is built from the TOP texts | approved |
| [F/meetings/protocols/000355](requirements/functional/meetings/protocols/000355_public-variant.md) | A non-public TOP gives a second PDF | approved |
| [F/meetings/protocols/000356](requirements/functional/meetings/protocols/000356_render-before-commit.md) | A failed render keeps the draft | approved |
| [F/meetings/protocols/000357](requirements/functional/meetings/protocols/000357_roster-quorum.md) | The quorum uses the roster of the meeting | approved |
| [F/meetings/protocols/000358](requirements/functional/meetings/protocols/000358_protocol-mail.md) | The protocol mail carries the PDF | approved |
| [F/meetings/protocols/000359](requirements/functional/meetings/protocols/000359_cd-variant.md) | The CD variant selects the layout | approved |
| [F/meetings/protocols/000360](requirements/functional/meetings/protocols/000360_text-is-data.md) | Protocol text is data, never code | approved |
| [F/meetings/protocols/000361](requirements/functional/meetings/protocols/000361_image-budget.md) | A protocol shows at most 48 images | approved |
| [F/meetings/protocols/000685](requirements/functional/meetings/protocols/000685_blackout-syntax.md) | Protocol text marks a segment for blackout | approved |
| [F/meetings/protocols/000686](requirements/functional/meetings/protocols/000686_blackout-unclosed.md) | An open blackout marker stops the finalize | approved |
| [F/meetings/protocols/000689](requirements/functional/meetings/protocols/000689_blackout-internal.md) | Internal views show a marked segment as marked | approved |
| [F/meetings/protocols/000690](requirements/functional/meetings/protocols/000690_blackout-format-bar.md) | The format bar marks a segment for blackout | approved |
| [F/meetings/protocols/000691](requirements/functional/meetings/protocols/000691_blackout-mail.md) | A marked segment sends the public PDF to the mailing list | approved |
| [F/meetings/voting/000024](requirements/functional/meetings/voting/000024_every-vote-is-secret.md) | Every vote is secret | approved |
| [F/meetings/voting/000025](requirements/functional/meetings/voting/000025_ballot-does-not-change.md) | A cast ballot does not change | approved |
| [F/meetings/voting/000026](requirements/functional/meetings/voting/000026_tie-rejects-motion.md) | A tie rejects a motion | approved |
| [F/meetings/voting/000027](requirements/functional/meetings/voting/000027_election-tie-by-lot.md) | A tie in an election is decided by lot | approved |
| [F/meetings/voting/000028](requirements/functional/meetings/voting/000028_protokollant-opens-and-closes.md) | Only the protokollant opens and closes a meeting vote | approved |
| [F/meetings/voting/000029](requirements/functional/meetings/voting/000029_delete-only-draft-or-cancelled.md) | A vote can be deleted only as draft or cancelled | approved |
| [F/meetings/voting/000030](requirements/functional/meetings/voting/000030_vote-in-gremium-of-antrag.md) | A vote on an Antrag belongs to the Gremium of the Antrag | approved |
| [F/meetings/voting/000031](requirements/functional/meetings/voting/000031_poll-shows-only-counts.md) | A poll shows only counts | approved |
| [F/meetings/voting/000378](requirements/functional/meetings/voting/000378_db-serializes-cast.md) | The database serializes ballots | approved |
| [F/meetings/voting/000379](requirements/functional/meetings/voting/000379_close-with-branch.md) | The close and its branch commit together | approved |
| [F/meetings/voting/000380](requirements/functional/meetings/voting/000380_quorum-close.md) | An unmet quorum blocks the manual close | approved |
| [F/meetings/voting/000381](requirements/functional/meetings/voting/000381_eligible-count.md) | The eligible count comes from the roster | approved |
| [F/meetings/voting/000382](requirements/functional/meetings/voting/000382_delegation-ballot.md) | A delegation ballot is a second ballot | approved |
| [F/public/public-pages/000170](requirements/functional/public/public-pages/000170_no-public-meetings.md) | Meetings are never public | replaced |
| [F/public/public-pages/000171](requirements/functional/public/public-pages/000171_public-protocols.md) | Only final protocols of public Gremien are public | approved |
| [F/public/public-pages/000172](requirements/functional/public/public-pages/000172_public-protocol-content.md) | A public protocol has no names and no internal TOPs | approved |
| [F/public/public-pages/000173](requirements/functional/public/public-pages/000173_noindex.md) | Public pages are not indexed | approved |
| [F/public/public-pages/000589](requirements/functional/public/public-pages/000589_login-choice.md) | Anmelden offers the account login and the e-mail link | approved |
| [F/public/public-pages/000687](requirements/functional/public/public-pages/000687_blackout-public.md) | The public variants black out a marked segment | approved |
| [F/public/public-pages/000688](requirements/functional/public/public-pages/000688_blackout-bar-width.md) | A black bar has one fixed width and the text colour | approved |
| [NF/accessibility/conformance/000490](requirements/non-functional/accessibility/conformance/000490_wcag-22-aa.md) | Every view meets WCAG 2.2 level AA | approved |
| [NF/accessibility/conformance/000491](requirements/non-functional/accessibility/conformance/000491_axe-every-route.md) | Every route passes an axe check in both themes | approved |
| [NF/accessibility/conformance/000492](requirements/non-functional/accessibility/conformance/000492_template-lint.md) | The template lint has the accessibility rules | approved |
| [NF/accessibility/conformance/000493](requirements/non-functional/accessibility/conformance/000493_axe-unit-per-component.md) | Every shared component has a jest-axe test | approved |
| [NF/accessibility/documents/000524](requirements/non-functional/accessibility/documents/000524_protocol-pdf-ua.md) | The protocol PDF is tagged as PDF/UA-1 | approved |
| [NF/accessibility/documents/000525](requirements/non-functional/accessibility/documents/000525_mail-plain-text.md) | Each mail has a plain text part | approved |
| [NF/accessibility/interaction/000217](requirements/non-functional/accessibility/interaction/000217_keyboard-and-labels.md) | Controls are reachable by keyboard and named | approved |
| [NF/accessibility/interaction/000218](requirements/non-functional/accessibility/interaction/000218_themes.md) | Light and dark themes are both supported | approved |
| [NF/accessibility/interaction/000219](requirements/non-functional/accessibility/interaction/000219_reduced-motion.md) | Motion follows the reduced motion setting | approved |
| [NF/accessibility/interaction/000508](requirements/non-functional/accessibility/interaction/000508_focus-ring.md) | The focus ring is 2 px and has a contrast of 3:1 | approved |
| [NF/accessibility/interaction/000509](requirements/non-functional/accessibility/interaction/000509_focus-not-hidden.md) | Sticky bars do not hide the focus | approved |
| [NF/accessibility/interaction/000510](requirements/non-functional/accessibility/interaction/000510_skip-link.md) | A skip link goes to the main content | approved |
| [NF/accessibility/interaction/000511](requirements/non-functional/accessibility/interaction/000511_page-title.md) | Each page has its own title | approved |
| [NF/accessibility/interaction/000512](requirements/non-functional/accessibility/interaction/000512_focus-after-navigation.md) | Focus goes to the heading after navigation | approved |
| [NF/accessibility/interaction/000513](requirements/non-functional/accessibility/interaction/000513_dialog-focus.md) | A dialog keeps the focus inside | approved |
| [NF/accessibility/interaction/000514](requirements/non-functional/accessibility/interaction/000514_gesture-alternative.md) | Each gesture has a single tap alternative | approved |
| [NF/accessibility/interaction/000515](requirements/non-functional/accessibility/interaction/000515_drag-alternative.md) | Each drag has an alternative without a drag | approved |
| [NF/accessibility/interaction/000516](requirements/non-functional/accessibility/interaction/000516_target-size.md) | A target is at least 24 by 24 px | approved |
| [NF/accessibility/interaction/000517](requirements/non-functional/accessibility/interaction/000517_status-announced.md) | A status message is announced | approved |
| [NF/accessibility/interaction/000518](requirements/non-functional/accessibility/interaction/000518_live-vote-announced.md) | The live vote announces its changes | approved |
| [NF/accessibility/interaction/000519](requirements/non-functional/accessibility/interaction/000519_form-errors.md) | A form error is a text next to the field | approved |
| [NF/accessibility/interaction/000520](requirements/non-functional/accessibility/interaction/000520_landmarks-headings.md) | Each page has landmarks and one h1 | approved |
| [NF/accessibility/interaction/000521](requirements/non-functional/accessibility/interaction/000521_no-cognitive-test.md) | The login and the captcha need no cognitive test | approved |
| [NF/accessibility/language/000216](requirements/non-functional/accessibility/language/000216_i18n-parity.md) | German and English texts are complete | replaced |
| [NF/accessibility/language/000522](requirements/non-functional/accessibility/language/000522_page-language.md) | The page language follows the UI language | approved |
| [NF/accessibility/language/000523](requirements/non-functional/accessibility/language/000523_content-language.md) | Content in a different language has its lang | approved |
| [NF/accessibility/perception/000499](requirements/non-functional/accessibility/perception/000499_text-contrast.md) | Text has a contrast of 4.5:1 | approved |
| [NF/accessibility/perception/000500](requirements/non-functional/accessibility/perception/000500_non-text-contrast.md) | Control edges and icons have a contrast of 3:1 | approved |
| [NF/accessibility/perception/000501](requirements/non-functional/accessibility/perception/000501_accent-contrast.md) | An admin accent colour keeps the contrast | approved |
| [NF/accessibility/perception/000502](requirements/non-functional/accessibility/perception/000502_colour-not-alone.md) | Colour is not the only sign of a state | approved |
| [NF/accessibility/perception/000503](requirements/non-functional/accessibility/perception/000503_reflow-320.md) | Every view works at a width of 320 px | approved |
| [NF/accessibility/perception/000504](requirements/non-functional/accessibility/perception/000504_text-spacing.md) | User text spacing does not cut text | approved |
| [NF/accessibility/perception/000506](requirements/non-functional/accessibility/perception/000506_image-alt.md) | A Markdown image has an alternative text | approved |
| [NF/accessibility/perception/000507](requirements/non-functional/accessibility/perception/000507_chart-text.md) | A chart has a text alternative | approved |
| [NF/accessibility/settings/000593](requirements/non-functional/accessibility/settings/000593_display-settings-in-accessibility-menu.md) | The accessibility menu holds the display settings | approved |
| [NF/accessibility/settings/000594](requirements/non-functional/accessibility/settings/000594_setting-overrides-system.md) | A display setting overrides the system setting | approved |
| [NF/accessibility/settings/000595](requirements/non-functional/accessibility/settings/000595_more-contrast.md) | More contrast raises the contrast of text and borders | approved |
| [NF/accessibility/settings/000596](requirements/non-functional/accessibility/settings/000596_less-transparency.md) | Less transparency makes the glass surfaces opaque | approved |
| [NF/accessibility/settings/000598](requirements/non-functional/accessibility/settings/000598_highlight-fields.md) | Very high contrast highlights the fields black on yellow | approved |
| [NF/accessibility/settings/000605](requirements/non-functional/accessibility/settings/000605_very-high-contrast.md) | Very high contrast shows the app in four colours | approved |
| [NF/accessibility/settings/000606](requirements/non-functional/accessibility/settings/000606_very-high-contrast-includes-settings.md) | Very high contrast includes the other display settings | approved |
| [NF/accessibility/settings/000608](requirements/non-functional/accessibility/settings/000608_display-reset-in-head-row.md) | The display reset lines up with the heading and the switches | approved |
| [NF/accessibility/settings/000612](requirements/non-functional/accessibility/settings/000612_attendance-matrix-very-high-contrast.md) | The attendance matrix follows very high contrast | approved |
| [NF/accessibility/settings/000614](requirements/non-functional/accessibility/settings/000614_yellow-means-press.md) | In very high contrast, yellow shows what a person can press | approved |
| [NF/accessibility/settings/000615](requirements/non-functional/accessibility/settings/000615_chosen-is-yellow-fill.md) | In very high contrast, the chosen control of a choice is yellow filled | approved |
| [NF/accessibility/settings/000616](requirements/non-functional/accessibility/settings/000616_navigation-yellow-text.md) | In very high contrast, the navigation has yellow text and yellow icons | approved |
| [NF/accessibility/settings/000617](requirements/non-functional/accessibility/settings/000617_menus-black-yellow-rows.md) | In very high contrast, every menu is black with yellow rows | approved |
| [NF/accessibility/settings/000618](requirements/non-functional/accessibility/settings/000618_choice-cards-keep-circle.md) | In very high contrast, a choice card has a yellow edge and a yellow circle | approved |
| [NF/accessibility/settings/000619](requirements/non-functional/accessibility/settings/000619_row-title-yellow.md) | In very high contrast, a row that opens something has a yellow title | approved |
| [NF/accessibility/settings/000620](requirements/non-functional/accessibility/settings/000620_switch-off-edge-on-fill.md) | In very high contrast, a switch, a checkbox and a radio button are filled only when on | approved |
| [NF/accessibility/settings/000621](requirements/non-functional/accessibility/settings/000621_black-on-yellow-fill.md) | In very high contrast, everything on a yellow fill is black | approved |
| [NF/accessibility/settings/000622](requirements/non-functional/accessibility/settings/000622_no-ring-on-script-focus.md) | A heading that a script focuses shows no focus ring | approved |
| [NF/accessibility/settings/000623](requirements/non-functional/accessibility/settings/000623_scripts-read-motion-setting.md) | A script reads the motion setting, not the system | approved |
| [NF/accessibility/settings/000647](requirements/non-functional/accessibility/settings/000647_accessibility-menu.md) | Accessibility has its own menu | approved |
| [NF/accessibility/settings/000739](requirements/non-functional/accessibility/settings/000739_copy-box-yellow-fill.md) | In very high contrast, a box with a text to copy is a yellow fill | approved |
| [NF/accessibility/statement/000495](requirements/non-functional/accessibility/statement/000495_statement-page.md) | A public page holds the accessibility statement | approved |
| [NF/accessibility/statement/000496](requirements/non-functional/accessibility/statement/000496_statement-link.md) | Every page links to the accessibility statement | approved |
| [NF/accessibility/statement/000497](requirements/non-functional/accessibility/statement/000497_barrier-report.md) | A user can report a barrier as a ticket | approved |
| [NF/compatibility/deploy/000394](requirements/non-functional/compatibility/deploy/000394_migrate-first.md) | A deploy runs the migration first | approved |
| [NF/compatibility/deploy/000435](requirements/non-functional/compatibility/deploy/000435_caddy-edge.md) | Caddy is the edge proxy | approved |
| [NF/compatibility/deploy/000627](requirements/non-functional/compatibility/deploy/000627_deploy-reports-schema-drift.md) | A deploy reports a schema that differs from the models | approved |
| [NF/compatibility/links/000592](requirements/non-functional/compatibility/links/000592_old-german-urls.md) | An old German URL redirects to its English URL | approved |
| [NF/compatibility/pwa/000220](requirements/non-functional/compatibility/pwa/000220_zoom.md) | Zoom is blocked only in the installed app | approved |
| [NF/compatibility/pwa/000221](requirements/non-functional/compatibility/pwa/000221_android-nav-bar.md) | The Android navigation bar has the manifest colour | approved |
| [NF/compatibility/pwa/000222](requirements/non-functional/compatibility/pwa/000222_update-offline.md) | The app shows update and offline bars | approved |
| [NF/compatibility/pwa/000411](requirements/non-functional/compatibility/pwa/000411_status-bar-theme.md) | The status bar follows the theme | approved |
| [NF/compatibility/pwa/000578](requirements/non-functional/compatibility/pwa/000578_server-unreachable-bar.md) | The offline bar shows when the server is unreachable | approved |
| [NF/compatibility/pwa/000579](requirements/non-functional/compatibility/pwa/000579_reload-after-unreachable.md) | An unreachable server shows no error toast, and the page loads again | approved |
| [NF/performance/loading/000189](requirements/non-functional/performance/loading/000189_load-bar.md) | The load bar shows only for slow foreground reads | approved |
| [NF/performance/loading/000190](requirements/non-functional/performance/loading/000190_batch-reads.md) | A list reads its rows in one request | approved |
| [NF/performance/loading/000191](requirements/non-functional/performance/loading/000191_search-as-you-type.md) | Search runs as you type | approved |
| [NF/privacy/personal-data/000185](requirements/non-functional/privacy/personal-data/000185_no-raw-ids.md) | The UI shows no raw IDs | approved |
| [NF/privacy/personal-data/000186](requirements/non-functional/privacy/personal-data/000186_no-plain-ip.md) | The login audit has no plain IP address | approved |
| [NF/privacy/personal-data/000187](requirements/non-functional/privacy/personal-data/000187_guest-pseudonyms.md) | Guests get pseudonyms | replaced |
| [NF/privacy/personal-data/000188](requirements/non-functional/privacy/personal-data/000188_anonymize.md) | Personal data can be anonymized | approved |
| [NF/privacy/personal-data/000290](requirements/non-functional/privacy/personal-data/000290_no-pii-in-audit.md) | An audit entry holds no personal data | approved |
| [NF/privacy/personal-data/000311](requirements/non-functional/privacy/personal-data/000311_mail-logs.md) | Mail logs hold no personal data | approved |
| [NF/privacy/personal-data/000384](requirements/non-functional/privacy/personal-data/000384_snapshot-no-pii.md) | A config snapshot holds no personal data | approved |
| [NF/privacy/personal-data/000404](requirements/non-functional/privacy/personal-data/000404_markdown-images.md) | Markdown images are outside erasure and export | approved |
| [NF/privacy/personal-data/000456](requirements/non-functional/privacy/personal-data/000456_retention-cron.md) | Terminal Anträge are anonymized after the retention time | approved |
| [NF/security/access/000179](requirements/non-functional/security/access/000179_public-allowlist.md) | A public route is on the allowlist | approved |
| [NF/security/access/000180](requirements/non-functional/security/access/000180_public-abuse-guard.md) | Public input is protected against abuse | approved |
| [NF/security/access/000275](requirements/non-functional/security/access/000275_oauth-pkce.md) | The OAuth flow needs PKCE and a loopback redirect | approved |
| [NF/security/access/000276](requirements/non-functional/security/access/000276_no-tokens-in-js.md) | Tokens never reach JavaScript | approved |
| [NF/security/access/000277](requirements/non-functional/security/access/000277_hashed-tokens.md) | Tokens are stored only as hashes | approved |
| [NF/security/access/000278](requirements/non-functional/security/access/000278_anti-enumeration.md) | A magic-link request does not reveal accounts | approved |
| [NF/security/access/000279](requirements/non-functional/security/access/000279_oidc-discovery.md) | OIDC endpoints come from discovery | approved |
| [NF/security/access/000304](requirements/non-functional/security/access/000304_no-token-backup.md) | No agent token reaches a backup | approved |
| [NF/security/access/000350](requirements/non-functional/security/access/000350_socket-origin.md) | A meeting socket checks the origin | approved |
| [NF/security/access/000352](requirements/non-functional/security/access/000352_guest-device.md) | A guest joins with one device | approved |
| [NF/security/access/000453](requirements/non-functional/security/access/000453_csrf-token.md) | Cookie writes need the CSRF token | approved |
| [NF/security/access/000460](requirements/non-functional/security/access/000460_default-write-limit.md) | Writes have a default rate limit | approved |
| [NF/security/access/000463](requirements/non-functional/security/access/000463_scope-caps-gremium-rights.md) | A scope caps every gremium right of a token | approved |
| [NF/security/access/000470](requirements/non-functional/security/access/000470_audit-read-global.md) | The audit read is global | approved |
| [NF/security/access/000472](requirements/non-functional/security/access/000472_public-application-post.md) | The public Antrag POST is protected | approved |
| [NF/security/access/000590](requirements/non-functional/security/access/000590_email-session-live-check.md) | An e-mail session reads its Anträge at each request | approved |
| [NF/security/files/000178](requirements/non-functional/security/files/000178_stream-downloads.md) | Downloads stream through the API | approved |
| [NF/security/files/000181](requirements/non-functional/security/files/000181_scan-uploads.md) | Uploaded files are scanned | approved |
| [NF/security/files/000264](requirements/non-functional/security/files/000264_invoice-download.md) | An invoice file is served as a download | approved |
| [NF/security/files/000305](requirements/non-functional/security/files/000305_restore-paths.md) | A restore writes only inside the bucket | approved |
| [NF/security/files/000343](requirements/non-functional/security/files/000343_display-name.md) | A file name is cleaned | approved |
| [NF/security/files/000344](requirements/non-functional/security/files/000344_image-reencode.md) | Markdown images are re-encoded | approved |
| [NF/security/files/000372](requirements/non-functional/security/files/000372_branding-checks.md) | Branding logos are checked by their bytes | approved |
| [NF/security/files/000373](requirements/non-functional/security/files/000373_cd-logo-download.md) | A CD logo is served as a download | approved |
| [NF/security/files/000388](requirements/non-functional/security/files/000388_token-file.md) | The MCP token file is private | approved |
| [NF/security/files/000469](requirements/non-functional/security/files/000469_invoice-xml-no-entities.md) | The ZUGFeRD XML parser resolves no entities | approved |
| [NF/security/integrity/000183](requirements/non-functional/security/integrity/000183_audit-chain.md) | The audit log is append-only | approved |
| [NF/security/integrity/000184](requirements/non-functional/security/integrity/000184_sandboxed-mail.md) | Mail templates run sandboxed | approved |
| [NF/security/integrity/000295](requirements/non-functional/security/integrity/000295_canonical-hash.md) | The hash input is canonical | approved |
| [NF/security/integrity/000296](requirements/non-functional/security/integrity/000296_secret-hidden.md) | A webhook secret is never shown | approved |
| [NF/security/integrity/000297](requirements/non-functional/security/integrity/000297_signature.md) | A webhook request is signed with a timestamp | approved |
| [NF/security/integrity/000393](requirements/non-functional/security/integrity/000393_db-roles.md) | Database roles are separated | approved |
| [NF/security/network/000182](requirements/non-functional/security/network/000182_webhook-ssrf.md) | The webhook SSRF guard runs at send time | approved |
| [NF/security/network/000335](requirements/non-functional/security/network/000335_avatar-fetch.md) | The avatar fetch is fixed and limited | approved |
| [NF/security/network/000389](requirements/non-functional/security/network/000389_typst-isolated.md) | The render service has no network egress | approved |
| [NF/security/network/000391](requirements/non-functional/security/network/000391_host-ports.md) | Only two ports are bound on the host | approved |
| [NF/security/network/000392](requirements/non-functional/security/network/000392_forwarded-ips.md) | Forwarded headers come only from the proxy | approved |
| [NF/security/network/000454](requirements/non-functional/security/network/000454_api-security-headers.md) | The API sends strict security headers and no CORS | approved |
| [NF/security/network/000466](requirements/non-functional/security/network/000466_webhook-host-allowlist.md) | Webhook targets can be limited to a host list | approved |
| [NF/usability/controls/000203](requirements/non-functional/usability/controls/000203_app-popover.md) | Every dropdown uses the app popover | approved |
| [NF/usability/controls/000204](requirements/non-functional/usability/controls/000204_whole-control.md) | The whole control is clickable | approved |
| [NF/usability/controls/000205](requirements/non-functional/usability/controls/000205_empty-state.md) | Empty states use one component | approved |
| [NF/usability/controls/000206](requirements/non-functional/usability/controls/000206_no-helper-texts.md) | The UI has no helper texts | approved |
| [NF/usability/controls/000207](requirements/non-functional/usability/controls/000207_no-title-counters.md) | Titles show no counters | replaced |
| [NF/usability/controls/000208](requirements/non-functional/usability/controls/000208_separators.md) | A separator stands only between two items | approved |
| [NF/usability/controls/000209](requirements/non-functional/usability/controls/000209_no-cut-urls.md) | URLs, IBANs and e-mail addresses are never cut | approved |
| [NF/usability/controls/000210](requirements/non-functional/usability/controls/000210_press-feedback.md) | A press gives feedback | approved |
| [NF/usability/controls/000211](requirements/non-functional/usability/controls/000211_swipe-and-select.md) | A swipe never deletes | approved |
| [NF/usability/controls/000212](requirements/non-functional/usability/controls/000212_tooltips.md) | A tooltip shows only for cut text | approved |
| [NF/usability/controls/000213](requirements/non-functional/usability/controls/000213_segments.md) | Segments have equal width | approved |
| [NF/usability/controls/000214](requirements/non-functional/usability/controls/000214_pill-icon.md) | A leading icon is centred on the end cap | approved |
| [NF/usability/controls/000399](requirements/non-functional/usability/controls/000399_design-basics.md) | The design has one accent and plain status text | approved |
| [NF/usability/controls/000400](requirements/non-functional/usability/controls/000400_danger-button.md) | A destructive action is an outlined red button | approved |
| [NF/usability/controls/000401](requirements/non-functional/usability/controls/000401_error-toast.md) | Errors show as a toast | approved |
| [NF/usability/controls/000410](requirements/non-functional/usability/controls/000410_tap-tint.md) | A tap tints the whole tile | approved |
| [NF/usability/controls/000412](requirements/non-functional/usability/controls/000412_ghost-rows-for-lists.md) | Ghost rows are only for lists | approved |
| [NF/usability/controls/000416](requirements/non-functional/usability/controls/000416_empty-chart.md) | An empty chart is a grey skeleton | approved |
| [NF/usability/controls/000528](requirements/non-functional/usability/controls/000528_segment-press.md) | A pressed segment shrinks its whole control | approved |
| [NF/usability/controls/000529](requirements/non-functional/usability/controls/000529_menu-row-tile.md) | A menu row is an inset rounded tile | approved |
| [NF/usability/controls/000560](requirements/non-functional/usability/controls/000560_no-counts-in-headings-and-selectors.md) | Headings and selectors show no counts | approved |
| [NF/usability/controls/000561](requirements/non-functional/usability/controls/000561_segment-pill.md) | A segmented control is a pill track | approved |
| [NF/usability/controls/000562](requirements/non-functional/usability/controls/000562_phone-toast-top.md) | A phone toast shows at the top | approved |
| [NF/usability/controls/000563](requirements/non-functional/usability/controls/000563_phone-one-toast.md) | A phone shows one toast at a time | approved |
| [NF/usability/controls/000564](requirements/non-functional/usability/controls/000564_phone-toast-close.md) | A phone toast closes by a swipe or by its time | approved |
| [NF/usability/controls/000565](requirements/non-functional/usability/controls/000565_phone-toast-card.md) | A phone toast is a tinted glass card | approved |
| [NF/usability/controls/000566](requirements/non-functional/usability/controls/000566_phone-toast-icon-action.md) | A phone toast action is an icon button | approved |
| [NF/usability/controls/000568](requirements/non-functional/usability/controls/000568_wide-toast-card.md) | A wide-screen toast is the same glass card | approved |
| [NF/usability/controls/000570](requirements/non-functional/usability/controls/000570_avatar-stack-cover.md) | An avatar in a stack covers the one before it | approved |
| [NF/usability/controls/000576](requirements/non-functional/usability/controls/000576_load-error-toast.md) | A load error shows as a toast with a retry action | approved |
| [NF/usability/controls/000577](requirements/non-functional/usability/controls/000577_load-error-toast-stays.md) | A load error toast stays until it is closed | approved |
| [NF/usability/controls/000581](requirements/non-functional/usability/controls/000581_card-add-buttons-dashed.md) | The add buttons of a card look like its chips with a dashed border | approved |
| [NF/usability/controls/000582](requirements/non-functional/usability/controls/000582_empty-linked-section.md) | An empty "Verknüpft" section shows an empty state | approved |
| [NF/usability/controls/000597](requirements/non-functional/usability/controls/000597_one-ghost-row-in-sections.md) | A section in a detail and a small tile show one ghost row | approved |
| [NF/usability/controls/000603](requirements/non-functional/usability/controls/000603_one-centre-line-in-controls.md) | Text, icons and counts of a control share one centre line | approved |
| [NF/usability/controls/000604](requirements/non-functional/usability/controls/000604_count-plate-in-button.md) | A count in a button is the count plate of the kit button | approved |
| [NF/usability/controls/000613](requirements/non-functional/usability/controls/000613_one-ghost-row-holds-message.md) | One ghost row holds the message and shows no bars | approved |
| [NF/usability/controls/000631](requirements/non-functional/usability/controls/000631_settings-row.md) | A settings row is a row of a row group, 56 px high | approved |
| [NF/usability/controls/000633](requirements/non-functional/usability/controls/000633_note-is-data-state.md) | A note shows a state of the data, not a failed request | approved |
| [NF/usability/controls/000661](requirements/non-functional/usability/controls/000661_list-search-names-the-count.md) | The search field of a list names the count | approved |
| [NF/usability/controls/000662](requirements/non-functional/usability/controls/000662_no-shown-of-total-counter.md) | A list shows no "X von Y" counter | approved |
| [NF/usability/controls/000663](requirements/non-functional/usability/controls/000663_filter-chip-label.md) | A filter chip shows its name, then name and value | approved |
| [NF/usability/controls/000665](requirements/non-functional/usability/controls/000665_empty-detail-pane-text.md) | The empty detail pane says "Kein … geöffnet" | approved |
| [NF/usability/controls/000666](requirements/non-functional/usability/controls/000666_create-wording.md) | A create form has the name of its button | approved |
| [NF/usability/controls/000667](requirements/non-functional/usability/controls/000667_status-filter-is-a-chip.md) | A list filters the status with a chip | approved |
| [NF/usability/controls/000668](requirements/non-functional/usability/controls/000668_fiscal-year-chip.md) | The fiscal year is chosen with a chip | approved |
| [NF/usability/controls/000669](requirements/non-functional/usability/controls/000669_linked-section-icon-actions.md) | The actions of a "Verknüpft" section are icon buttons | approved |
| [NF/usability/controls/000671](requirements/non-functional/usability/controls/000671_one-place-per-action.md) | A view shows an action in one place | approved |
| [NF/usability/controls/000675](requirements/non-functional/usability/controls/000675_phone-row-end.md) | A phone list row ends with a menu or with nothing | approved |
| [NF/usability/controls/000676](requirements/non-functional/usability/controls/000676_tickets-word-in-admin.md) | Verwaltung says "Tickets" | approved |
| [NF/usability/controls/000678](requirements/non-functional/usability/controls/000678_live-connection-lost-toast.md) | A lost live connection shows as a toast | approved |
| [NF/usability/controls/000700](requirements/non-functional/usability/controls/000700_date-field-relative-shortcut.md) | A date field takes a shortcut relative to today | approved |
| [NF/usability/controls/000701](requirements/non-functional/usability/controls/000701_date-shortcut-resolves-on-commit.md) | A date shortcut becomes the date when the field commits | approved |
| [NF/usability/controls/000702](requirements/non-functional/usability/controls/000702_date-shortcut-month-end.md) | A month or year shortcut stops at the end of the month | approved |
| [NF/usability/controls/000741](requirements/non-functional/usability/controls/000741_load-more-button.md) | A button that loads more rows of a list is centred with a chevron | approved |
| [NF/usability/layout/000192](requirements/non-functional/usability/layout/000192_one-geometry.md) | All list and detail pages share one geometry | approved |
| [NF/usability/layout/000193](requirements/non-functional/usability/layout/000193_scroll-edges.md) | A scroll edge fades, or cuts at a line | approved |
| [NF/usability/layout/000194](requirements/non-functional/usability/layout/000194_phone-breakpoint.md) | The phone layout starts below 768 px | approved |
| [NF/usability/layout/000195](requirements/non-functional/usability/layout/000195_bottom-bar.md) | The phone bottom bar is fixed | approved |
| [NF/usability/layout/000196](requirements/non-functional/usability/layout/000196_phone-sheets.md) | The phone opens pickers as bottom sheets | approved |
| [NF/usability/layout/000197](requirements/non-functional/usability/layout/000197_header-actions.md) | A header has a title, at most one action and a menu | approved |
| [NF/usability/layout/000198](requirements/non-functional/usability/layout/000198_floating-actions.md) | Neu and Speichern float at the bottom | approved |
| [NF/usability/layout/000199](requirements/non-functional/usability/layout/000199_footer.md) | The footer shows only on start and public pages | approved |
| [NF/usability/layout/000200](requirements/non-functional/usability/layout/000200_surfaces.md) | Surfaces step up | approved |
| [NF/usability/layout/000201](requirements/non-functional/usability/layout/000201_fill-or-centre.md) | Content fills its width or is centred | approved |
| [NF/usability/layout/000202](requirements/non-functional/usability/layout/000202_top-layer.md) | Dialogs and toasts are on the top layer | approved |
| [NF/usability/layout/000215](requirements/non-functional/usability/layout/000215_comments-beside.md) | Comments sit beside the fields | approved |
| [NF/usability/layout/000406](requirements/non-functional/usability/layout/000406_desktop-unchanged.md) | The phone layout does not change the desktop | approved |
| [NF/usability/layout/000407](requirements/non-functional/usability/layout/000407_mehr-and-search.md) | Mehr and Suche are always in reach | approved |
| [NF/usability/layout/000408](requirements/non-functional/usability/layout/000408_bottom-inset.md) | Fixed bottom elements sit above the bottom bar | approved |
| [NF/usability/layout/000409](requirements/non-functional/usability/layout/000409_phone-panes.md) | The phone shows tables as cards | approved |
| [NF/usability/layout/000413](requirements/non-functional/usability/layout/000413_card-mode.md) | A table in card mode keeps its controls in the card head | approved |
| [NF/usability/layout/000414](requirements/non-functional/usability/layout/000414_admin-heading.md) | Admin pages share one heading | approved |
| [NF/usability/layout/000415](requirements/non-functional/usability/layout/000415_balanced-bars.md) | Bars and headers are vertically balanced | approved |
| [NF/usability/layout/000417](requirements/non-functional/usability/layout/000417_antraege-pattern.md) | Work lists follow the Anträge pattern | approved |
| [NF/usability/layout/000451](requirements/non-functional/usability/layout/000451_phone-one-pane.md) | The phone shows one pane at a time | approved |
| [NF/usability/layout/000452](requirements/non-functional/usability/layout/000452_phone-dialog-sheet.md) | A phone dialog is a near-fullscreen sheet | approved |
| [NF/usability/layout/000527](requirements/non-functional/usability/layout/000527_glass-list-head.md) | A list head is one glass surface over its rows | approved |
| [NF/usability/layout/000530](requirements/non-functional/usability/layout/000530_phone-start-search-pinned.md) | The search bar of the start page stays at the top on the phone | approved |
| [NF/usability/layout/000531](requirements/non-functional/usability/layout/000531_head-under-sheet.md) | The page head stays in view under an open sheet | approved |
| [NF/usability/layout/000532](requirements/non-functional/usability/layout/000532_stacked-glass.md) | A sheet over a sheet is as opaque as the first one | approved |
| [NF/usability/layout/000567](requirements/non-functional/usability/layout/000567_phone-fab-folds.md) | A phone FAB folds to its icon on scroll | approved |
| [NF/usability/layout/000575](requirements/non-functional/usability/layout/000575_card-sheet-cut-at-edge.md) | The details of a card cut at the lower screen edge | approved |
| [NF/usability/layout/000580](requirements/non-functional/usability/layout/000580_card-end-clears-bottom-bar.md) | The end of a card keeps room above the bottom bar | approved |
| [NF/usability/layout/000599](requirements/non-functional/usability/layout/000599_glass-head-top-fade.md) | A glass list head fades into the page colour at the top screen edge | approved |
| [NF/usability/layout/000601](requirements/non-functional/usability/layout/000601_scrollbar-below-glass-head.md) | The scroll bar of a list column starts below its glass head | approved |
| [NF/usability/layout/000602](requirements/non-functional/usability/layout/000602_composer-bottom-gap.md) | The comment input has the same gap below as at its side | approved |
| [NF/usability/layout/000609](requirements/non-functional/usability/layout/000609_attendance-matrix-row-group.md) | The attendance matrix looks like a row group | approved |
| [NF/usability/layout/000624](requirements/non-functional/usability/layout/000624_start-work-list-sticky-head.md) | The work list on Start keeps its column header and cuts at the window edge | approved |
| [NF/usability/layout/000634](requirements/non-functional/usability/layout/000634_admin-record-row.md) | A record row in Verwaltung has one anatomy | approved |
| [NF/usability/layout/000635](requirements/non-functional/usability/layout/000635_discard-with-save.md) | A page with Speichern offers Verwerfen in its header | approved |
| [NF/usability/layout/000660](requirements/non-functional/usability/layout/000660_nav-rail-shows-active-item.md) | The navigation rail shows the active item | approved |
| [NF/usability/layout/000664](requirements/non-functional/usability/layout/000664_list-opens-no-item-by-itself.md) | A list page opens no item by itself | approved |
| [NF/usability/layout/000670](requirements/non-functional/usability/layout/000670_detail-head-icons-and-menu.md) | A detail head has icon buttons and a menu | approved |
| [NF/usability/layout/000672](requirements/non-functional/usability/layout/000672_content-language-in-page-head.md) | The language of a content editor stands in the page head | approved |
| [NF/usability/layout/000673](requirements/non-functional/usability/layout/000673_phone-detail-tabs-packed.md) | The tabs of a phone detail are packed at the start | approved |
| [NF/usability/layout/000674](requirements/non-functional/usability/layout/000674_phone-vote-detail-bar.md) | The phone vote detail uses the bar of the other details | approved |
| [NF/usability/layout/000677](requirements/non-functional/usability/layout/000677_public-page-title-size.md) | A public page has a title of 28 px | approved |
| [NF/usability/layout/000743](requirements/non-functional/usability/layout/000743_week-day-lines-on-pull.md) | The day lines of the week grid stay when the hours are pulled | approved |
| [NF/usability/layout/000745](requirements/non-functional/usability/layout/000745_week-blocks-overlap.md) | A later entry lies on an earlier one in the week view | approved |
| [S/backend/database/000068](style/backend/database/000068_hash-revision.md) | A migration has a hash ID | approved |
| [S/backend/database/000069](style/backend/database/000069_one-head.md) | Alembic has one head | approved |
| [S/backend/database/000070](style/backend/database/000070_idempotent-tables.md) | A migration that adds a table is idempotent | approved |
| [S/backend/database/000071](style/backend/database/000071_data-revision.md) | A data change has its own revision | approved |
| [S/backend/database/000072](style/backend/database/000072_immutable-records.md) | Five record types are immutable | approved |
| [S/backend/database/000625](style/backend/database/000625_upgrade-path-test.md) | CI runs the new migrations on the schema of the last release | approved |
| [S/backend/database/000626](style/backend/database/000626_schema-equals-models.md) | A migrated database has the schema of the models | approved |
| [S/backend/functional/000090](style/backend/functional/000090_no-gather-on-session.md) | One AsyncSession is never used concurrently | approved |
| [S/backend/python/000058](style/backend/python/000058_aware-datetimes.md) | Datetimes are timezone-aware | approved |
| [S/backend/python/000059](style/backend/python/000059_server-side-rbac.md) | Permissions are checked on the server | approved |
| [S/backend/python/000060](style/backend/python/000060_permission-not-role.md) | A gate names a permission, not a role | approved |
| [S/backend/python/000061](style/backend/python/000061_strict-types.md) | Inputs are strictly typed | approved |
| [S/backend/python/000062](style/backend/python/000062_docstrings.md) | Docstrings instead of comments | approved |
| [S/backend/python/000063](style/backend/python/000063_no-eval.md) | No eval | approved |
| [S/backend/python/000064](style/backend/python/000064_resolve-names.md) | Names are resolved on the server | replaced |
| [S/backend/python/000065](style/backend/python/000065_merge-columns.md) | A principal column is known to the account merge | approved |
| [S/backend/python/000066](style/backend/python/000066_public-routes.md) | Public endpoints are a fixed list | replaced |
| [S/backend/python/000473](style/backend/python/000473_no-role-check.md) | A permission check never reads principal.roles | approved |
| [S/backend/python/000474](style/backend/python/000474_services-do-not-commit.md) | Service functions do not commit | approved |
| [S/backend/python/000640](style/backend/python/000640_service-commit-ratchet.md) | A CI ratchet lowers the commits in services | approved |
| [S/backend/python/000643](style/backend/python/000643_module-layers.md) | A backend module imports only from its layer and from lower layers | approved |
| [S/backend/python/000644](style/backend/python/000644_shared-imports-no-module.md) | The shared code imports no module | approved |
| [S/backend/python/000645](style/backend/python/000645_model-in-subject-module.md) | A model is in the module of its subject | approved |
| [S/backend/python/000646](style/backend/python/000646_import-exception-ratchet.md) | A CI ratchet lowers the accepted import violations | approved |
| [S/backend/python/000648](style/backend/python/000648_notifications-mail-engine-only.md) | The module notifications holds the mail engine only | approved |
| [S/backend/python/000649](style/backend/python/000649_auth-audit-no-upward-import.md) | The modules auth and audit import no higher module | approved |
| [S/backend/python/000651](style/backend/python/000651_no-import-exception.md) | The import contract has no exception | approved |
| [S/backend/python/000652](style/backend/python/000652_meeting-core-module.md) | The meeting core is in the module meetings | approved |
| [S/frontend/angular/000073](style/frontend/angular/000073_i18n-parity.md) | Every UI text is in both catalogs | approved |
| [S/frontend/angular/000074](style/frontend/angular/000074_production-build.md) | Run the production build after style changes | approved |
| [S/frontend/angular/000075](style/frontend/angular/000075_narrow-with-as.md) | A template narrows a signal with as | approved |
| [S/frontend/angular/000076](style/frontend/angular/000076_tailwind-borders.md) | A Tailwind border has a style | approved |
| [S/frontend/angular/000077](style/frontend/angular/000077_load-bar.md) | Only foreground reads show the load bar | replaced |
| [S/frontend/angular/000078](style/frontend/angular/000078_after-next-render.md) | Wait for a render with afterNextRender | approved |
| [S/frontend/angular/000079](style/frontend/angular/000079_ui-kit-parts.md) | Shared UI parts live in the ui-kit | approved |
| [S/frontend/angular/000080](style/frontend/angular/000080_standalone-components.md) | Components are standalone with own files | approved |
| [S/frontend/angular/000395](style/frontend/angular/000395_semantic-tokens.md) | Components use semantic colour tokens | approved |
| [S/frontend/angular/000396](style/frontend/angular/000396_route-guards.md) | A route guard is only for the UX | approved |
| [S/frontend/angular/000397](style/frontend/angular/000397_gremium-checks.md) | Gremium rights come from the Gremium API | approved |
| [S/frontend/angular/000398](style/frontend/angular/000398_mock-dev-only.md) | The mock API runs only in dev builds | approved |
| [S/frontend/angular/000526](style/frontend/angular/000526_use-shared-parts.md) | A view uses the shared components | approved |
| [S/frontend/angular/000632](style/frontend/angular/000632_admin-load-state.md) | An admin page shows its load states through app-load-state | approved |
| [S/frontend/angular/000636](style/frontend/angular/000636_no-unused-class.md) | A component stylesheet has no class without a use | approved |
| [S/frontend/angular/000637](style/frontend/angular/000637_admin-container-widths.md) | Container queries in Verwaltung use three named widths | approved |
| [S/frontend/angular/000639](style/frontend/angular/000639_admin-folder-is-route.md) | The folder of an admin page has the name of its route | approved |
| [S/frontend/functional/000091](style/frontend/functional/000091_signal-update.md) | A signal update returns a new value | approved |
| [S/frontend/functional/000438](style/frontend/functional/000438_eslint-functional.md) | eslint-plugin-functional warns on mutation | approved |
| [S/shared/agents/000175](style/shared/agents/000175_prod-data.md) | Production data changes only on request | approved |
| [S/shared/agents/000426](style/shared/agents/000426_ask-with-options.md) | Ask with options | approved |
| [S/shared/agents/000427](style/shared/agents/000427_report-bugs.md) | Report a possible bug | approved |
| [S/shared/agents/000428](style/shared/agents/000428_no-unasked-features.md) | Do not build what exists | approved |
| [S/shared/agents/000429](style/shared/agents/000429_mockup-remark.md) | A mockup remark does not change the ui-kit | approved |
| [S/shared/agents/000430](style/shared/agents/000430_attach-mockups.md) | Mockup images go into the thread | approved |
| [S/shared/agents/000431](style/shared/agents/000431_plan-in-main.md) | Plan in the main session | approved |
| [S/shared/agents/000432](style/shared/agents/000432_no-main-checkout.md) | Do not touch the main checkout | approved |
| [S/shared/agents/000433](style/shared/agents/000433_no-imitation.md) | No page imitates an organization | approved |
| [S/shared/api/000039](style/shared/api/000039_same-names.md) | Field names are the same in frontend and backend | approved |
| [S/shared/api/000040](style/shared/api/000040_camelcase-base-model.md) | Schemas use the shared camelCase base model | approved |
| [S/shared/api/000041](style/shared/api/000041_one-source.md) | Shared data has one source | approved |
| [S/shared/api/000042](style/shared/api/000042_problem-json.md) | Every error is problem+json | approved |
| [S/shared/api/000468](style/shared/api/000468_specific-conflict-code.md) | A conflict names a specific code | approved |
| [S/shared/api/000475](style/shared/api/000475_oauth-error-shape.md) | The OAuth token endpoint uses the RFC 6749 error shape | approved |
| [S/shared/api/000591](style/shared/api/000591_english-urls.md) | Every URL is in English | approved |
| [S/shared/functional/000081](style/shared/functional/000081_body-shape.md) | A function body has one shape | approved |
| [S/shared/functional/000082](style/shared/functional/000082_readability-limit.md) | Readability limits the single expression | approved |
| [S/shared/functional/000083](style/shared/functional/000083_bind-once.md) | A local is bound once | approved |
| [S/shared/functional/000084](style/shared/functional/000084_no-mutation.md) | A value is not mutated | approved |
| [S/shared/functional/000085](style/shared/functional/000085_comprehensions.md) | Comprehensions instead of loops | approved |
| [S/shared/functional/000086](style/shared/functional/000086_exhaustive-match.md) | A branch on one value is an exhaustive match | approved |
| [S/shared/functional/000087](style/shared/functional/000087_frozen-data.md) | Data types are frozen by default | approved |
| [S/shared/functional/000088](style/shared/functional/000088_effects-at-edge.md) | Effects stay at the edge | approved |
| [S/shared/functional/000089](style/shared/functional/000089_exceptions.md) | The exceptions are named | approved |
| [S/shared/functional/000437](style/shared/functional/000437_functional-ratchet.md) | A CI ratchet keeps the functional style from getting worse | approved |
| [S/shared/git/000043](style/shared/git/000043_mcp-version.md) | The MCP version rises with the tool set | approved |
| [S/shared/git/000051](style/shared/git/000051_commits.md) | Commits are unsigned and have no trailers | approved |
| [S/shared/git/000052](style/shared/git/000052_no-auto-merge.md) | A pull request is never set to auto-merge | approved |
| [S/shared/git/000053](style/shared/git/000053_release-tags.md) | Only the owner tags a release | approved |
| [S/shared/git/000054](style/shared/git/000054_merge-go.md) | A merge needs the go of the owner | approved |
| [S/shared/git/000055](style/shared/git/000055_ui-screenshots.md) | A UI change is approved on screenshots | approved |
| [S/shared/git/000056](style/shared/git/000056_ui-kit-flow.md) | ui-kit changes go to ui-kit development first | approved |
| [S/shared/git/000057](style/shared/git/000057_release-notes.md) | Release notes list migrations and steps | approved |
| [S/shared/git/000224](style/shared/git/000224_target-development.md) | An app pull request targets development | approved |
| [S/shared/git/000225](style/shared/git/000225_found-bugs.md) | A found bug is fixed, a behaviour change is asked | approved |
| [S/shared/git/000390](style/shared/git/000390_typst-pin.md) | The typst version is pinned in two places | approved |
| [S/shared/git/000423](style/shared/git/000423_one-pr-per-package.md) | One branch and one pull request per package | approved |
| [S/shared/git/000424](style/shared/git/000424_sync-main.md) | Sync main into development first | approved |
| [S/shared/git/000425](style/shared/git/000425_shared-in-kit.md) | Shared list parts live in the ui-kit | replaced |
| [S/shared/git/000434](style/shared/git/000434_environments.md) | Dev follows development, production follows tags | approved |
| [S/shared/git/000436](style/shared/git/000436_release-flow.md) | A release goes from development to main by pull request | approved |
| [S/shared/git/000477](style/shared/git/000477_readme-links-git-specs.md) | The README links to the git specs | approved |
| [S/shared/git/000628](style/shared/git/000628_required-checks.md) | The branches development and main require the CI checks | approved |
| [S/shared/testing/000044](style/shared/testing/000044_test-first.md) | Tests come first | approved |
| [S/shared/testing/000045](style/shared/testing/000045_coverage-gates.md) | Coverage gates hold | approved |
| [S/shared/testing/000046](style/shared/testing/000046_critical-modules.md) | Critical modules have full branch coverage | approved |
| [S/shared/testing/000047](style/shared/testing/000047_own-test-keys.md) | An integration test uses its own keys | approved |
| [S/shared/testing/000048](style/shared/testing/000048_run-integration.md) | CI runs the full suites | approved |
| [S/shared/testing/000049](style/shared/testing/000049_check-pixels.md) | A visual bug is checked on pixels | approved |
| [S/shared/testing/000050](style/shared/testing/000050_mockups-from-real-app.md) | UI mockups come from the real app | approved |
| [S/shared/testing/000223](style/shared/testing/000223_test-refers-to-rule.md) | A test refers back to its rule | approved |
| [S/shared/testing/000476](style/shared/testing/000476_fake-principal.md) | Test doubles of Principal model the admin bypass | approved |
| [S/shared/testing/000641](style/shared/testing/000641_query-test-on-postgres.md) | A test of a database query runs on Postgres | approved |
| [S/shared/testing/000642](style/shared/testing/000642_session-fake-ratchet.md) | A CI ratchet lowers the fake sessions in tests | approved |
| [S/shared/tooling/000067](style/shared/tooling/000067_nix-dev-shell.md) | Commands run in the Nix dev shell | approved |
| [S/shared/writing/000034](style/shared/writing/000034_ste-english.md) | Repository texts are written in STE English | approved |
| [S/shared/writing/000035](style/shared/writing/000035_stupa-in-capitals.md) | STUPA is written in capitals | approved |
| [S/shared/writing/000036](style/shared/writing/000036_no-task-references.md) | Texts do not refer to old tasks | approved |
| [S/shared/writing/000037](style/shared/writing/000037_current-fact.md) | Texts state the current fact | approved |
| [S/shared/writing/000038](style/shared/writing/000038_true-docstrings.md) | A docstring is true | approved |
| [S/specs/content/000015](style/specs/content/000015_only-the-rule.md) | A spec contains only the rule | approved |
| [S/specs/content/000016](style/specs/content/000016_one-thing.md) | One rule controls one thing | approved |
| [S/specs/content/000017](style/specs/content/000017_examinable.md) | A rule can be examined | approved |
| [S/specs/content/000018](style/specs/content/000018_must-and-must-not.md) | The rule text uses must and must not | approved |
| [S/specs/content/000019](style/specs/content/000019_reason.md) | A rule gives its reason | approved |
| [S/specs/content/000020](style/specs/content/000020_test.md) | A rule names its test | approved |
| [S/specs/content/000021](style/specs/content/000021_current-rule.md) | A spec states the current rule | approved |
| [S/specs/content/000022](style/specs/content/000022_ste.md) | A spec is written in ASD-STE100 | approved |
| [S/specs/content/000023](style/specs/content/000023_product-terms.md) | Product terms stay as the UI shows them | approved |
| [S/specs/format/000001](style/specs/format/000001_copy-the-template.md) | A new spec starts as a copy of the template | approved |
| [S/specs/format/000002](style/specs/format/000002_front-matter.md) | A spec starts with a YAML front matter | approved |
| [S/specs/format/000003](style/specs/format/000003_status.md) | The status shows the approval | approved |
| [S/specs/format/000004](style/specs/format/000004_one-rule-per-file.md) | One file holds one rule | approved |
| [S/specs/format/000005](style/specs/format/000005_rule-id.md) | The rule ID has kind, path and number | approved |
| [S/specs/format/000006](style/specs/format/000006_unique-number.md) | The number is the identity of a rule | approved |
| [S/specs/format/000007](style/specs/format/000007_moved-rule.md) | A moved rule keeps its number | approved |
| [S/specs/format/000008](style/specs/format/000008_labels.md) | Labels in a rule are fixed | approved |
| [S/specs/format/000032](style/specs/format/000032_section-sign-reference.md) | Code refers to a rule with the § sign | approved |
| [S/specs/format/000033](style/specs/format/000033_file-name.md) | The file name is number and name | approved |
| [S/specs/structure/000009](style/specs/structure/000009_precedence.md) | A spec wins over other guidance | approved |
| [S/specs/structure/000010](style/specs/structure/000010_tree.md) | The tree sorts by kind, then by area and topic | approved |
| [S/specs/structure/000011](style/specs/structure/000011_folder-names.md) | Folder names are lower case kebab case | approved |
| [S/specs/structure/000012](style/specs/structure/000012_one-place.md) | A rule is written in one place | approved |
| [S/specs/structure/000013](style/specs/structure/000013_index.md) | The index lists every rule | approved |
| [S/specs/structure/000014](style/specs/structure/000014_change-process.md) | A change goes through a pull request | approved |
| [S/specs/structure/000226](style/specs/structure/000226_spec-first.md) | A change request starts as a spec | approved |
| [S/specs/uml/000679](style/specs/uml/000679_uml-folder.md) | The UML data of the app is in specs/uml | approved |
| [S/specs/uml/000680](style/specs/uml/000680_uml-generated.md) | A script writes the generated UML views, and CI checks that they are current | approved |
| [S/specs/uml/000681](style/specs/uml/000681_uml-components.md) | The component view shows the backend modules, their layers and their imports | approved |
| [S/specs/uml/000682](style/specs/uml/000682_uml-classes.md) | The class view shows every database model and its relations | approved |
| [S/specs/uml/000683](style/specs/uml/000683_uml-deployment.md) | The deployment view shows the services of the compose stack | approved |
| [S/specs/uml/000684](style/specs/uml/000684_uml-states.md) | A state view is written by hand and has the states of its check constraint | approved |
