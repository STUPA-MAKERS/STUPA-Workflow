# Specs

The binding rules of STUPA-Workflow. One file holds one rule. A protocol spec in `protocols/`
holds one whole data exchange format. The rules for specs are in [style/specs/](style/specs/).
Copy [TEMPLATE.md](TEMPLATE.md) to start a new rule, and
[TEMPLATE-protocol.md](TEMPLATE-protocol.md) to start a new protocol spec.

## Tree

```
specs/
  style/
    backend/   database, functional, python
    frontend/  angular, functional
    shared/    agents, api, functional, git, testing, tooling, writing
    specs/     content, format, protocols, structure, uml
  requirements/
    functional/
      administration/  accounts, admin, audit, backups, files, privacy, translations
      applications/    applications, dashboard, flow, forms
      collaboration/   activity, committees, graph, links, notifications, search, tickets, todos
      finance/         budget, invoices
      integrations/    external, mcp, paperless, ticket-mail, webhooks
      meetings/        calendar, delegations, meetings, protocols, voting
      public/          public-pages
    non-functional/
      accessibility/  documents, interaction, language, perception, statement
      compatibility/  deploy, links, pwa
      performance/    loading, rendering
      privacy/        personal-data
      security/       access, files, integrity, network
      usability/      controls, layout
  protocols/
    integrations/  webhooks
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
| [F/administration/accounts/000266](requirements/functional/administration/accounts/000266_member-role.md) | Every user holds the member role | replaced |
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
| [F/administration/accounts/001095](requirements/functional/administration/accounts/001095_account-name.md) | The account on the login names the short name | approved |
| [F/administration/accounts/001120](requirements/functional/administration/accounts/001120_profile-page.md) | The account area has a profile page with the SSO claims | approved |
| [F/administration/accounts/001121](requirements/functional/administration/accounts/001121_profile-token-claims.md) | The profile page hides the claims of the token itself | approved |
| [F/administration/accounts/001122](requirements/functional/administration/accounts/001122_profile-gravatar-link.md) | The profile picture links to Gravatar | approved |
| [F/administration/admin/000161](requirements/functional/administration/admin/000161_crud-complete.md) | Every entity has create, read, update and delete | approved |
| [F/administration/admin/000162](requirements/functional/administration/admin/000162_cd-variant-delete.md) | A CD variant in use is not deleted | approved |
| [F/administration/admin/000163](requirements/functional/administration/admin/000163_audit-revert.md) | The audit revert reverses effects, never entries | approved |
| [F/administration/admin/000164](requirements/functional/administration/admin/000164_translations.md) | Admins edit UI texts and add languages | replaced |
| [F/administration/admin/000166](requirements/functional/administration/admin/000166_dsgvo-delete.md) | A privacy erasure starts from Benutzer | approved |
| [F/administration/admin/000368](requirements/functional/administration/admin/000368_role-keys.md) | Role keys are fixed lower case | approved |
| [F/administration/admin/000369](requirements/functional/administration/admin/000369_page-permissions.md) | Each admin page has its own permission | approved |
| [F/administration/admin/000370](requirements/functional/administration/admin/000370_self-lockout.md) | An admin cannot deactivate the own account | approved |
| [F/administration/admin/000371](requirements/functional/administration/admin/000371_repin-by-key.md) | A flow save moves Anträge by state key | approved |
| [F/administration/admin/000383](requirements/functional/administration/admin/000383_revert-forward.md) | A config revert goes forward | approved |
| [F/administration/admin/000405](requirements/functional/administration/admin/000405_revert-permissions.md) | A revert needs the right of the original change | approved |
| [F/administration/admin/000638](requirements/functional/administration/admin/000638_admin-menu-icons.md) | Each entry of the admin menu has its own icon | approved |
| [F/administration/admin/000756](requirements/functional/administration/admin/000756_feature-switches.md) | An admin switches each feature on and off | approved |
| [F/administration/admin/000757](requirements/functional/administration/admin/000757_feature-off-server.md) | A feature that is off is closed on the server | approved |
| [F/administration/admin/000758](requirements/functional/administration/admin/000758_feature-off-ui.md) | A feature that is off does not show in the UI | approved |
| [F/administration/admin/000759](requirements/functional/administration/admin/000759_feature-keeps-data.md) | A switch keeps the data of the feature | approved |
| [F/administration/admin/000760](requirements/functional/administration/admin/000760_feature-dependencies.md) | A feature that needs another feature goes off with it | approved |
| [F/administration/admin/000761](requirements/functional/administration/admin/000761_feature-in-use.md) | A feature in use by the Antrag flow cannot go off | approved |
| [F/administration/admin/000762](requirements/functional/administration/admin/000762_features-page.md) | The admin page Funktionen holds the feature switches | approved |
| [F/administration/admin/000891](requirements/functional/administration/admin/000891_export-logo.md) | Exported PDFs carry the export logo of the branding | approved |
| [F/administration/admin/000892](requirements/functional/administration/admin/000892_pdf-footer-graphic.md) | Every PDF carries the footer graphic of the branding | approved |
| [F/administration/admin/000906](requirements/functional/administration/admin/000906_gremium-defaults.md) | A new Gremium starts with the meeting defaults | approved |
| [F/administration/admin/000917](requirements/functional/administration/admin/000917_meeting-periods.md) | The meeting settings hold the periods of the Geschäftsordnung | approved |
| [F/administration/admin/000942](requirements/functional/administration/admin/000942_periods-fixed-at-start.md) | A changed period does not reach a started case | approved |
| [F/administration/admin/000980](requirements/functional/administration/admin/000980_embedded-pdfs-follow-sitzungen.md) | The embedded PDFs belong to the feature Sitzungen | approved |
| [F/administration/admin/001005](requirements/functional/administration/admin/001005_pdf-default-preview.md) | The branding page shows the built-in PDF graphics | approved |
| [F/administration/admin/001090](requirements/functional/administration/admin/001090_page-head-branding.md) | The page head follows the branding before any script runs | approved |
| [F/administration/admin/001091](requirements/functional/administration/admin/001091_link-preview-image.md) | The link preview shows the Bildmarke | approved |
| [F/administration/admin/001092](requirements/functional/administration/admin/001092_app-icons-from-bildmarke.md) | The app icons follow the Bildmarke | approved |
| [F/administration/admin/001093](requirements/functional/administration/admin/001093_branding-description.md) | The branding holds the description of the platform | approved |
| [F/administration/admin/001230](requirements/functional/administration/admin/001230_platform-name-from-branding.md) | Every visible name of the platform comes from the branding | approved |
| [F/administration/admin/001231](requirements/functional/administration/admin/001231_seeded-mail-subject-branding.md) | The seeded subject of the access link mail names the branding | approved |
| [F/administration/admin/002601](requirements/functional/administration/admin/002601_gremien-page-opens-asked-row.md) | The Gremien page opens and shows the Gremium of the link | approved |
| [F/administration/admin/002620](requirements/functional/administration/admin/002620_users-no-group-mapping-link.md) | Benutzer and Gremien have no link to the Gruppen-Zuordnung | approved |
| [F/administration/admin/002691](requirements/functional/administration/admin/002691_admin-list-search.md) | The search of a Verwaltung list finds the text of a row | approved |
| [F/administration/admin/002693](requirements/functional/administration/admin/002693_audit-log-search.md) | The Audit-Log searches on the server | approved |
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
| [F/administration/privacy/002532](requirements/functional/administration/privacy/002532_erasure-lists-paperless.md) | An erasure names the filed Paperless documents | approved |
| [F/administration/privacy/002533](requirements/functional/administration/privacy/002533_export-names-paperless.md) | The data export names the filed Paperless documents | approved |
| [F/administration/privacy/002747](requirements/functional/administration/privacy/002747_erasure-lists-ticket-mails.md) | An erasure names the mails that stay on the mail server | approved |
| [F/administration/privacy/002748](requirements/functional/administration/privacy/002748_export-holds-mail-tickets.md) | The data export holds the mail tickets of the addresses of the person | approved |
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
| [F/applications/applications/000751](requirements/functional/applications/applications/000751_observers.md) | An Antrag can have observers | approved |
| [F/applications/applications/000752](requirements/functional/applications/applications/000752_observer-reads.md) | An observer reads the Antrag and does not change it | approved |
| [F/applications/applications/000753](requirements/functional/applications/applications/000753_observer-no-pii.md) | An observer does not see personal fields | approved |
| [F/applications/applications/000754](requirements/functional/applications/applications/000754_observer-mails.md) | An observer gets the status mails | approved |
| [F/applications/applications/000755](requirements/functional/applications/applications/000755_observer-removal.md) | A removed observer loses the access at once | approved |
| [F/applications/applications/000880](requirements/functional/applications/applications/000880_pdf-export.md) | An Antrag downloads as PDF | approved |
| [F/applications/applications/000881](requirements/functional/applications/applications/000881_pdf-content.md) | The Antrag PDF shows the Antrag like the detail page | approved |
| [F/applications/applications/000882](requirements/functional/applications/applications/000882_pdf-no-pii-without-right.md) | The Antrag PDF shows only what the reader may see | approved |
| [F/applications/applications/000883](requirements/functional/applications/applications/000883_pdf-name.md) | The Antrag PDF is named after the Antrag | approved |
| [F/applications/applications/000888](requirements/functional/applications/applications/000888_pdf-signatures.md) | The Antrag PDF of an Antragsart can end with a signature section | approved |
| [F/applications/applications/001170](requirements/functional/applications/applications/001170_apply-type-in-url.md) | The chosen Antragsart stands in the apply URL | approved |
| [F/applications/applications/001171](requirements/functional/applications/applications/001171_apply-unknown-type.md) | An apply link to an unknown Antragsart opens the type step | approved |
| [F/applications/applications/001172](requirements/functional/applications/applications/001172_public-type-key.md) | The public list of Antragstypen gives the key | approved |
| [F/applications/applications/001173](requirements/functional/applications/applications/001173_apply-old-type-link.md) | An old apply link with the type id still works | approved |
| [F/applications/applications/001180](requirements/functional/applications/applications/001180_type-groups.md) | Admins group the Antragsarten | approved |
| [F/applications/applications/001181](requirements/functional/applications/applications/001181_apply-type-groups.md) | Step 1 shows the Antragsarten by group with the group text | approved |
| [F/applications/applications/001182](requirements/functional/applications/applications/001182_apply-ungrouped-types.md) | Antragsarten without a group stand last under Weitere Anträge | approved |
| [F/applications/applications/001183](requirements/functional/applications/applications/001183_type-group-order.md) | Admins set the order of the groups and of the Antragsarten | approved |
| [F/applications/applications/001184](requirements/functional/applications/applications/001184_no-general-apply-text.md) | Step 1 has no general text, only the group texts | approved |
| [F/applications/applications/001610](requirements/functional/applications/applications/001610_approval-asks-amount.md) | Every approval asks for the approved amount | approved |
| [F/applications/applications/001611](requirements/functional/applications/applications/001611_vote-stores-amount.md) | A vote that approves stores the approved amount | approved |
| [F/applications/applications/001612](requirements/functional/applications/applications/001612_both-amounts-shown.md) | List, detail and export show the requested and the approved amount | approved |
| [F/applications/applications/001613](requirements/functional/applications/applications/001613_backfill-approved-amount.md) | Existing approvals get their approved amount | approved |
| [F/applications/applications/001620](requirements/functional/applications/applications/001620_amend-approved-amount.md) | An approved Antrag takes a new approved amount | approved |
| [F/applications/applications/001621](requirements/functional/applications/applications/001621_amend-shows-old-and-new.md) | The timeline and the audit show the old and the new approved amount | approved |
| [F/applications/applications/001622](requirements/functional/applications/applications/001622_amend-above-requested.md) | A changed approved amount can be higher than the requested amount | approved |
| [F/applications/applications/001660](requirements/functional/applications/applications/001660_change-application-type.md) | A submitted Antrag can change its Antragsart | approved |
| [F/applications/applications/001661](requirements/functional/applications/applications/001661_change-type-missing-fields.md) | A change of the Antragsart sends missing required fields to the applicant | approved |
| [F/applications/applications/001662](requirements/functional/applications/applications/001662_change-type-old-values.md) | Values the new form does not have stay readable | approved |
| [F/applications/applications/001663](requirements/functional/applications/applications/001663_change-type-timeline.md) | The timeline and the audit show the old and the new Antragsart | approved |
| [F/applications/applications/001690](requirements/functional/applications/applications/001690_member-comment-internal.md) | A member comment is internal by default | approved |
| [F/applications/applications/001691](requirements/functional/applications/applications/001691_comment-visibility-labels.md) | The visibility switch names who reads the comment | approved |
| [F/applications/applications/001692](requirements/functional/applications/applications/001692_comment-visibility-visible.md) | The chosen visibility shows before sending | approved |
| [F/applications/applications/001700](requirements/functional/applications/applications/001700_list-multi-select.md) | The Antrag list has a multiple selection | approved |
| [F/applications/applications/001701](requirements/functional/applications/applications/001701_bulk-transition.md) | A bulk status change uses only transitions allowed for each selected Antrag | approved |
| [F/applications/applications/001702](requirements/functional/applications/applications/001702_bulk-message.md) | A bulk message adds one public comment to each Antrag | approved |
| [F/applications/applications/001704](requirements/functional/applications/applications/001704_bulk-set-status.md) | The bulk action of the Antrag list sets a status and skips the Anträge that cannot take it | approved |
| [F/applications/applications/001710](requirements/functional/applications/applications/001710_draft-not-submitted.md) | A draft says that it is not submitted | approved |
| [F/applications/applications/001711](requirements/functional/applications/applications/001711_draft-reminder-mail.md) | A draft without a change for 7 days gets one reminder mail | approved |
| [F/applications/applications/001712](requirements/functional/applications/applications/001712_withdraw-confirm.md) | A withdrawal asks first and does not show in a draft | approved |
| [F/applications/applications/001720](requirements/functional/applications/applications/001720_new-version-button.md) | A denied or returned Antrag offers a new version | approved |
| [F/applications/applications/001721](requirements/functional/applications/applications/001721_new-version-link.md) | A new version links to the old Antrag | approved |
| [F/applications/applications/001722](requirements/functional/applications/applications/001722_new-version-closes-old.md) | Submitting the new version closes the old Antrag | approved |
| [F/applications/applications/001982](requirements/functional/applications/applications/001982_applications-list-two-fabs.md) | The Anträge list has the FABs Antrag stellen and Antrag erfassen | approved |
| [F/applications/dashboard/000421](requirements/functional/applications/dashboard/000421_dashboard.md) | The start page is a work list with a side sheet | replaced |
| [F/applications/dashboard/000550](requirements/functional/applications/dashboard/000550_start-due-cards.md) | Start shows the due cards of the person | replaced |
| [F/applications/dashboard/000650](requirements/functional/applications/dashboard/000650_start-apply-button-tab-line.md) | Antrag stellen stands in the tab line of the desktop start page | replaced |
| [F/applications/dashboard/000750](requirements/functional/applications/dashboard/000750_start-tab-line-buttons-same-size.md) | The two buttons in the tab line of the start page have the same size | replaced |
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
| [F/applications/flow/001600](requirements/functional/applications/flow/001600_decision-outside-platform.md) | A vote state takes a decision made outside the platform | approved |
| [F/applications/flow/001601](requirements/functional/applications/flow/001601_outside-decision-cancels-votes.md) | A decision made outside the platform cancels the open votes | approved |
| [F/applications/flow/001602](requirements/functional/applications/flow/001602_outside-decision-timeline.md) | The timeline shows a decision made outside the platform | approved |
| [F/applications/flow/001603](requirements/functional/applications/flow/001603_record-decision-permission.md) | Recording a decision made outside the platform needs its own permission | approved |
| [F/applications/flow/001650](requirements/functional/applications/flow/001650_force-status-reason.md) | A forced status needs a reason from a list | approved |
| [F/applications/flow/001651](requirements/functional/applications/flow/001651_force-status-report.md) | An admin page lists the forced status changes | approved |
| [F/applications/flow/001652](requirements/functional/applications/flow/001652_force-status-old-reason.md) | A forced change without a reason counts as Ohne Grund | approved |
| [F/applications/flow/001653](requirements/functional/applications/flow/001653_force-approval-asks-amount.md) | A forced approval asks for the approved amount | approved |
| [F/applications/forms/000133](requirements/functional/applications/forms/000133_positions-shape.md) | A positions answer has label and offers | approved |
| [F/applications/forms/000134](requirements/functional/applications/forms/000134_offer-limits.md) | Offer counts have limits | approved |
| [F/applications/forms/000135](requirements/functional/applications/forms/000135_funding-field.md) | The requested funding is separate from the costs | approved |
| [F/applications/forms/000280](requirements/functional/applications/forms/000280_pin-not-mutate.md) | A form version is never changed | approved |
| [F/applications/forms/000281](requirements/functional/applications/forms/000281_inactive-type.md) | A type without an active form is closed | approved |
| [F/applications/forms/000282](requirements/functional/applications/forms/000282_system-title.md) | Every form has a title field | approved |
| [F/applications/forms/000284](requirements/functional/applications/forms/000284_definition-check.md) | A form definition is checked at save time | approved |
| [F/applications/forms/000285](requirements/functional/applications/forms/000285_jsonlogic-whitelist.md) | JsonLogic uses a whitelist | approved |
| [F/applications/forms/000286](requirements/functional/applications/forms/000286_all-errors.md) | Answer validation reports all errors | approved |
| [F/applications/forms/000287](requirements/functional/applications/forms/000287_pattern-limits.md) | A pattern check cannot hang | approved |
| [F/applications/forms/000288](requirements/functional/applications/forms/000288_finite-numbers.md) | Numbers are finite decimals | approved |
| [F/applications/forms/000289](requirements/functional/applications/forms/000289_form-revision.md) | A form change is versioned and audited | approved |
| [F/applications/forms/000471](requirements/functional/applications/forms/000471_type-retention.md) | Antrag types can keep their own retention | approved |
| [F/applications/forms/001630](requirements/functional/applications/forms/001630_cost-total-line.md) | The Kostenaufstellung shows the total cost and the requested amount | approved |
| [F/applications/forms/001631](requirements/functional/applications/forms/001631_cost-per-person.md) | The cost line shows the amount per person | approved |
| [F/applications/forms/001632](requirements/functional/applications/forms/001632_cost-line-in-detail.md) | The Antrag detail shows no cost line | approved |
| [F/applications/forms/001640](requirements/functional/applications/forms/001640_placeholder-offer-warning.md) | The form warns about a placeholder offer | approved |
| [F/applications/forms/001641](requirements/functional/applications/forms/001641_placeholder-warning-not-blocking.md) | A placeholder warning does not block the submit | approved |
| [F/applications/forms/001670](requirements/functional/applications/forms/001670_form-rules.md) | A form version has rules across fields | approved |
| [F/applications/forms/001671](requirements/functional/applications/forms/001671_form-rules-same-check.md) | Frontend and backend check the same form rules | approved |
| [F/applications/forms/001680](requirements/functional/applications/forms/001680_cost-centre-field-subtree.md) | A Kostenstelle field can limit its picker to a subtree | approved |
| [F/applications/forms/001681](requirements/functional/applications/forms/001681_cost-centre-outside-subtree.md) | The server refuses a Kostenstelle outside the subtree | approved |
| [F/applications/forms/001730](requirements/functional/applications/forms/001730_position-files.md) | A position takes files in the form | approved |
| [F/applications/forms/001731](requirements/functional/applications/forms/001731_submit-without-file-warning.md) | A submit without a file asks for a confirmation | approved |
| [F/applications/forms/001732](requirements/functional/applications/forms/001732_type-requires-file.md) | An Antragsart can require a file | approved |
| [F/applications/forms/002840](requirements/functional/applications/forms/002840_computed-amount.md) | The server computes a computed amount | approved |
| [F/applications/forms/002841](requirements/functional/applications/forms/002841_computed-amount-cents.md) | A computed amount is a whole number of cents | approved |
| [F/applications/forms/002842](requirements/functional/applications/forms/002842_computed-amount-display.md) | A computed amount shows as money | approved |
| [F/applications/forms/002843](requirements/functional/applications/forms/002843_computed-amount-toggle.md) | The form builder makes a computed field the amount | approved |
| [F/collaboration/activity/001270](requirements/functional/collaboration/activity/001270_activity-page.md) | The activity page lists the events of the items of a person | approved |
| [F/collaboration/activity/001271](requirements/functional/collaboration/activity/001271_items-of-a-person.md) | An item belongs to a person when they made, hold or touched it | approved |
| [F/collaboration/activity/001272](requirements/functional/collaboration/activity/001272_reuse-gates.md) | The activity page reuses the read gate of each module | approved |
| [F/collaboration/activity/001273](requirements/functional/collaboration/activity/001273_hide-own-actions.md) | The activity page hides the own actions by default | approved |
| [F/collaboration/activity/001274](requirements/functional/collaboration/activity/001274_kind-filter.md) | The activity page filters by the kind of item | approved |
| [F/collaboration/activity/001275](requirements/functional/collaboration/activity/001275_new-since-last-visit.md) | New events since the last visit are marked | approved |
| [F/collaboration/activity/001276](requirements/functional/collaboration/activity/001276_paging.md) | The activity page loads 50 events per step without a time limit | approved |
| [F/collaboration/activity/001300](requirements/functional/collaboration/activity/001300_activity-is-the-start-page.md) | The activity page is the start page | approved |
| [F/collaboration/activity/001301](requirements/functional/collaboration/activity/001301_apply-button-in-activity-header.md) | Antrag stellen stands in the header of the activity page | replaced |
| [F/collaboration/activity/001302](requirements/functional/collaboration/activity/001302_live-meeting-on-activity.md) | The activity page shows a running meeting above the list | approved |
| [F/collaboration/activity/001307](requirements/functional/collaboration/activity/001307_no-system-archive.md) | The automatic archive of a to-do card is not an activity | approved |
| [F/collaboration/committees/001010](requirements/functional/collaboration/committees/001010_info-tab.md) | A Gremium has an Info tab | approved |
| [F/collaboration/committees/001011](requirements/functional/collaboration/committees/001011_info-edit-permission.md) | Only info.write edits the Info of a Gremium | approved |
| [F/collaboration/committees/001012](requirements/functional/collaboration/committees/001012_info-links.md) | An Info link has a label and a web address | approved |
| [F/collaboration/committees/001013](requirements/functional/collaboration/committees/001013_info-markdown.md) | The Info text is sanitized Markdown | approved |
| [F/collaboration/committees/001014](requirements/functional/collaboration/committees/001014_info-save.md) | An Info save is versioned and audited | approved |
| [F/collaboration/committees/001015](requirements/functional/collaboration/committees/001015_info-empty.md) | An empty Info tab shows only to its editors | approved |
| [F/collaboration/committees/001850](requirements/functional/collaboration/committees/001850_notify-members.md) | A Gremium notifies its members | approved |
| [F/collaboration/committees/001851](requirements/functional/collaboration/committees/001851_notify-permission.md) | Only members.notify sends a message to the members | approved |
| [F/collaboration/committees/001852](requirements/functional/collaboration/committees/001852_notify-recipients.md) | The message goes to the members and the substitute pool | approved |
| [F/collaboration/committees/001853](requirements/functional/collaboration/committees/001853_notify-template.md) | The members message is a mail template | approved |
| [F/collaboration/committees/001854](requirements/functional/collaboration/committees/001854_notify-checks.md) | A members message is checked and audited | approved |
| [F/collaboration/committees/002600](requirements/functional/collaboration/committees/002600_manage-opens-gremien-page.md) | Gremium verwalten opens the Gremium on the Gremien page | approved |
| [F/collaboration/graph/001420](requirements/functional/collaboration/graph/001420_graph-page.md) | The page Graph shows the elements of a person and their relations | approved |
| [F/collaboration/graph/001421](requirements/functional/collaboration/graph/001421_graph-permission.md) | The graph needs its own permission | approved |
| [F/collaboration/graph/001422](requirements/functional/collaboration/graph/001422_graph-read-rules.md) | The graph shows only what the person reads | approved |
| [F/collaboration/graph/001423](requirements/functional/collaboration/graph/001423_graph-nodes.md) | The graph shows the elements that have a relation | approved |
| [F/collaboration/graph/001424](requirements/functional/collaboration/graph/001424_graph-relations.md) | The graph shows links and the built-in relations | approved |
| [F/collaboration/graph/001431](requirements/functional/collaboration/graph/001431_graph-api.md) | The graph has its own API | approved |
| [F/collaboration/graph/001432](requirements/functional/collaboration/graph/001432_graph-features.md) | A kind of a feature that is off does not show in the graph | approved |
| [F/collaboration/graph/001434](requirements/functional/collaboration/graph/001434_graph-neighbour-steps.md) | The graph shows the neighbours of the hits up to a count of steps | approved |
| [F/collaboration/graph/002790](requirements/functional/collaboration/graph/002790_graph-load-more.md) | "Mehr laden" of the graph stands over the zoom buttons | approved |
| [F/collaboration/links/001400](requirements/functional/collaboration/links/001400_any-to-any.md) | Any two elements can link to each other | approved |
| [F/collaboration/links/001401](requirements/functional/collaboration/links/001401_no-direction.md) | A link has no direction | approved |
| [F/collaboration/links/001402](requirements/functional/collaboration/links/001402_one-row-two-ends.md) | A link is one row with two typed ends | approved |
| [F/collaboration/links/001403](requirements/functional/collaboration/links/001403_card-links-move.md) | The card links move to the new table | approved |
| [F/collaboration/links/001404](requirements/functional/collaboration/links/001404_link-rights.md) | A person links what the person reads and writes on one end | approved |
| [F/collaboration/links/001405](requirements/functional/collaboration/links/001405_only-card-grants.md) | Only a card gives read access to its links | approved |
| [F/collaboration/links/001406](requirements/functional/collaboration/links/001406_predecessor-stays.md) | The Vorgänger stays its own relation | approved |
| [F/collaboration/links/001407](requirements/functional/collaboration/links/001407_one-linked-section.md) | Each element shows all its links in Verknüpft | approved |
| [F/collaboration/links/001408](requirements/functional/collaboration/links/001408_one-picker.md) | Verknüpfen searches every kind | approved |
| [F/collaboration/links/001409](requirements/functional/collaboration/links/001409_links-api.md) | The links have their own API | approved |
| [F/collaboration/links/001410](requirements/functional/collaboration/links/001410_cost-centre-needs-budget-write.md) | A cost centre link needs a budget write right | approved |
| [F/collaboration/notifications/000151](requirements/functional/collaboration/notifications/000151_task-mail-recipients.md) | Task mails go only to who can act | approved |
| [F/collaboration/notifications/000152](requirements/functional/collaboration/notifications/000152_team-mails-opt-in.md) | Team mails about Anträge are off by default | approved |
| [F/collaboration/notifications/000153](requirements/functional/collaboration/notifications/000153_sandboxed-templates.md) | Mail placeholders use camelCase | approved |
| [F/collaboration/notifications/000306](requirements/functional/collaboration/notifications/000306_mail-queue.md) | Mails go through the queue | approved |
| [F/collaboration/notifications/000307](requirements/functional/collaboration/notifications/000307_mail-once.md) | A mail is sent once | approved |
| [F/collaboration/notifications/000308](requirements/functional/collaboration/notifications/000308_mail-link.md) | Every mail links its element | approved |
| [F/collaboration/notifications/000309](requirements/functional/collaboration/notifications/000309_mail-preferences.md) | A person controls their mail kinds | approved |
| [F/collaboration/notifications/000310](requirements/functional/collaboration/notifications/000310_mail-languages.md) | Mail texts are in German and English | approved |
| [F/collaboration/notifications/000312](requirements/functional/collaboration/notifications/000312_task-reminders.md) | Task reminders follow the admin setting | approved |
| [F/collaboration/notifications/000998](requirements/functional/collaboration/notifications/000998_mail-platform-name.md) | A mail names the platform by its branding name | approved |
| [F/collaboration/notifications/000999](requirements/functional/collaboration/notifications/000999_mail-logo.md) | The head of a mail shows the logo of the branding | approved |
| [F/collaboration/notifications/001000](requirements/functional/collaboration/notifications/001000_mail-accent.md) | The button and the links of a mail use the accent colour | approved |
| [F/collaboration/notifications/001001](requirements/functional/collaboration/notifications/001001_mail-footer-text.md) | The footer of a mail shows the E-Mail-Fußzeile | approved |
| [F/collaboration/notifications/001002](requirements/functional/collaboration/notifications/001002_mail-footer-copyright.md) | The footer of a mail shows the copyright line | approved |
| [F/collaboration/notifications/001003](requirements/functional/collaboration/notifications/001003_mail-footer-legal-links.md) | The footer of a mail shows the legal links | approved |
| [F/collaboration/notifications/001004](requirements/functional/collaboration/notifications/001004_mail-dark-colours.md) | A mail has light and dark colours | approved |
| [F/collaboration/notifications/002500](requirements/functional/collaboration/notifications/002500_push-per-device.md) | A person switches on push for one device | approved |
| [F/collaboration/notifications/002501](requirements/functional/collaboration/notifications/002501_push-switch-per-kind.md) | Push has its own switch per kind | approved |
| [F/collaboration/notifications/002502](requirements/functional/collaboration/notifications/002502_push-urgent-defaults.md) | Only urgent kinds push by default | approved |
| [F/collaboration/notifications/002503](requirements/functional/collaboration/notifications/002503_push-content.md) | A push shows a title and one short line | approved |
| [F/collaboration/notifications/002504](requirements/functional/collaboration/notifications/002504_push-feature-switch.md) | Push has a feature switch | approved |
| [F/collaboration/notifications/002505](requirements/functional/collaboration/notifications/002505_push-vapid-key.md) | The platform makes its own push key | approved |
| [F/collaboration/notifications/002506](requirements/functional/collaboration/notifications/002506_push-expired-devices.md) | An expired device subscription is removed | approved |
| [F/collaboration/notifications/002507](requirements/functional/collaboration/notifications/002507_push-accounts-only.md) | Only accounts get push | approved |
| [F/collaboration/notifications/002508](requirements/functional/collaboration/notifications/002508_push-jump-buttons.md) | A push can carry jump buttons | approved |
| [F/collaboration/notifications/002509](requirements/functional/collaboration/notifications/002509_push-direct-actions.md) | A push can act without opening the app | approved |
| [F/collaboration/notifications/002510](requirements/functional/collaboration/notifications/002510_push-endpoint-guard.md) | A push goes only to a known push service | approved |
| [F/collaboration/notifications/002550](requirements/functional/collaboration/notifications/002550_push-bell-activity.md) | A bell in the head of Aktivität asks for push and opens the settings | approved |
| [F/collaboration/search/000328](requirements/functional/collaboration/search/000328_reuse-gates.md) | Search reuses the gate of each module | approved |
| [F/collaboration/search/000329](requirements/functional/collaboration/search/000329_query-length.md) | Search needs two characters | approved |
| [F/collaboration/search/000330](requirements/functional/collaboration/search/000330_per-kind-cap.md) | Search shows 5 hits per kind | approved |
| [F/collaboration/tickets/000150](requirements/functional/collaboration/tickets/000150_public-report.md) | Anyone can report a help ticket | approved |
| [F/collaboration/tickets/000313](requirements/functional/collaboration/tickets/000313_reporter-view.md) | A reporter account follows its tickets | approved |
| [F/collaboration/tickets/000314](requirements/functional/collaboration/tickets/000314_team-work.md) | The team works on tickets | replaced |
| [F/collaboration/tickets/000315](requirements/functional/collaboration/tickets/000315_sender-block.md) | A sender can be blocked | approved |
| [F/collaboration/tickets/000316](requirements/functional/collaboration/tickets/000316_ticket-retention.md) | Closed tickets are anonymized after the retention time | approved |
| [F/collaboration/tickets/000317](requirements/functional/collaboration/tickets/000317_context-url.md) | A ticket context keeps only platform pages | approved |
| [F/collaboration/tickets/001096](requirements/functional/collaboration/tickets/001096_system-entry-name.md) | A system entry names the short name | approved |
| [F/collaboration/tickets/002700](requirements/functional/collaboration/tickets/002700_ticket-bereich.md) | Each ticket belongs to one Bereich | approved |
| [F/collaboration/tickets/002701](requirements/functional/collaboration/tickets/002701_bereich-plattform.md) | The Bereich Plattform takes the reports of the help menu | approved |
| [F/collaboration/tickets/002702](requirements/functional/collaboration/tickets/002702_bereich-gremium.md) | A Bereich belongs to one Gremium or to no Gremium | approved |
| [F/collaboration/tickets/002703](requirements/functional/collaboration/tickets/002703_work-right.md) | The work right in a Bereich comes from the Gremium | approved |
| [F/collaboration/tickets/002704](requirements/functional/collaboration/tickets/002704_assignee-in-bereich.md) | Only a person with the work right in the Bereich is assignee or mentioned | approved |
| [F/collaboration/tickets/002705](requirements/functional/collaboration/tickets/002705_bereich-settings.md) | The admin page Hilfe & Tickets holds the Bereiche | approved |
| [F/collaboration/tickets/002706](requirements/functional/collaboration/tickets/002706_kategorien.md) | Each Bereich has its own Kategorien | approved |
| [F/collaboration/tickets/002707](requirements/functional/collaboration/tickets/002707_move-ticket.md) | A ticket can move to a different Bereich | approved |
| [F/collaboration/tickets/002708](requirements/functional/collaboration/tickets/002708_status-waiting.md) | A ticket has the status Wartet auf Antwort | approved |
| [F/collaboration/tickets/002709](requirements/functional/collaboration/tickets/002709_answer-ends-waiting.md) | An answer of the sender ends Wartet auf Antwort | approved |
| [F/collaboration/tickets/002710](requirements/functional/collaboration/tickets/002710_reopen-window.md) | An answer on a closed ticket opens it again for 14 days | approved |
| [F/collaboration/tickets/002711](requirements/functional/collaboration/tickets/002711_ticket-source.md) | A ticket names its source | approved |
| [F/collaboration/tickets/002712](requirements/functional/collaboration/tickets/002712_ticket-by-hand.md) | The team creates a ticket by hand | approved |
| [F/collaboration/tickets/002713](requirements/functional/collaboration/tickets/002713_bereich-in-app.md) | A Bereich can take tickets from signed-in persons | approved |
| [F/collaboration/tickets/002714](requirements/functional/collaboration/tickets/002714_random-ticket-number.md) | A new ticket gets a random number of eight characters | approved |
| [F/collaboration/tickets/002715](requirements/functional/collaboration/tickets/002715_bereich-filter.md) | The ticket list shows the Bereiche of the person | approved |
| [F/collaboration/tickets/002716](requirements/functional/collaboration/tickets/002716_anonymization-removes-mail-data.md) | The anonymization of a ticket removes its mail data | approved |
| [F/collaboration/tickets/002717](requirements/functional/collaboration/tickets/002717_new-ticket-mail.md) | A new ticket is mailed to the team of its Bereich | approved |
| [F/collaboration/tickets/002718](requirements/functional/collaboration/tickets/002718_assigned-mail.md) | The new assignee gets a mail | approved |
| [F/collaboration/tickets/002719](requirements/functional/collaboration/tickets/002719_existing-tickets.md) | The tickets from before the Bereiche belong to Plattform | approved |
| [F/collaboration/todos/000147](requirements/functional/collaboration/todos/000147_board-kinds.md) | Boards per Gremium, per person and per team | approved |
| [F/collaboration/todos/000149](requirements/functional/collaboration/todos/000149_no-status-sync.md) | No status sync between ticket and card | approved |
| [F/collaboration/todos/000318](requirements/functional/collaboration/todos/000318_board-rights.md) | Board rights depend on the board kind | replaced |
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
| [F/collaboration/todos/000489](requirements/functional/collaboration/todos/000489_links-are-called-linked.md) | The cards of an element are under Verknüpft | replaced |
| [F/collaboration/todos/000547](requirements/functional/collaboration/todos/000547_create-card-from-element.md) | A card is created from the detail of an element | approved |
| [F/collaboration/todos/000548](requirements/functional/collaboration/todos/000548_link-card-from-element.md) | An element is linked to a card from its detail | replaced |
| [F/collaboration/todos/000549](requirements/functional/collaboration/todos/000549_due-cards-in-calendar.md) | A due card of a person is in their calendar | approved |
| [F/collaboration/todos/000551](requirements/functional/collaboration/todos/000551_meeting-gremium-linked.md) | A meeting shows its links and a Gremium its board | approved |
| [F/collaboration/todos/000552](requirements/functional/collaboration/todos/000552_cost-centre-link.md) | A card can link a cost centre | approved |
| [F/collaboration/todos/000553](requirements/functional/collaboration/todos/000553_card-to-agenda.md) | A card is put on the agenda from the card | approved |
| [F/collaboration/todos/000554](requirements/functional/collaboration/todos/000554_duplicate-card.md) | A card can be duplicated | approved |
| [F/collaboration/todos/000555](requirements/functional/collaboration/todos/000555_item-to-card.md) | A checklist item becomes a card | approved |
| [F/collaboration/todos/000573](requirements/functional/collaboration/todos/000573_card-links-both-ways.md) | A link between two cards shows on both cards | replaced |
| [F/collaboration/todos/000735](requirements/functional/collaboration/todos/000735_termin-link.md) | A card can link a Termin | approved |
| [F/collaboration/todos/000736](requirements/functional/collaboration/todos/000736_event-times.md) | The start and the end of an Event can have a time | approved |
| [F/collaboration/todos/001060](requirements/functional/collaboration/todos/001060_free-boards.md) | A free board belongs to no single Gremium | approved |
| [F/collaboration/todos/001061](requirements/functional/collaboration/todos/001061_free-board-create.md) | Admins and holders of todo.create_board create a free board | approved |
| [F/collaboration/todos/001062](requirements/functional/collaboration/todos/001062_free-board-roles.md) | Each member entry of a free board has a role | approved |
| [F/collaboration/todos/001063](requirements/functional/collaboration/todos/001063_gremium-entry-live.md) | A Gremium entry stands for the members of the Gremium at the time of the read | approved |
| [F/collaboration/todos/001064](requirements/functional/collaboration/todos/001064_free-board-manage.md) | Members with Verwalten and admins manage a free board | approved |
| [F/collaboration/todos/001065](requirements/functional/collaboration/todos/001065_free-board-assignees.md) | Assignees of a free board are its members who edit | approved |
| [F/collaboration/todos/001066](requirements/functional/collaboration/todos/001066_free-board-global-keys.md) | todo.all and todo.read_all reach free boards | approved |
| [F/collaboration/todos/001067](requirements/functional/collaboration/todos/001067_free-boards-in-picker.md) | Free boards show in the board picker after the boards of the Gremien | approved |
| [F/collaboration/todos/001068](requirements/functional/collaboration/todos/001068_free-board-archive.md) | A manager archives a free board and only an admin deletes it | approved |
| [F/collaboration/todos/001069](requirements/functional/collaboration/todos/001069_free-board-agenda.md) | A card of a free board goes on the agenda of each of its Gremien | approved |
| [F/collaboration/todos/001070](requirements/functional/collaboration/todos/001070_gremium-tab-own-board.md) | The To-Dos tab of a Gremium shows only the board of the Gremium | approved |
| [F/collaboration/todos/001071](requirements/functional/collaboration/todos/001071_free-board-added-mail.md) | A person added to a free board by name gets a mail | approved |
| [F/collaboration/todos/001072](requirements/functional/collaboration/todos/001072_gremium-boards-stay.md) | The board of a Gremium stays its own kind | approved |
| [F/collaboration/todos/001073](requirements/functional/collaboration/todos/001073_team-board-stays.md) | The team board Plattform stays a team board | approved |
| [F/collaboration/todos/001075](requirements/functional/collaboration/todos/001075_free-board-transfer.md) | A card moves between a free board and other shared boards | approved |
| [F/collaboration/todos/001076](requirements/functional/collaboration/todos/001076_free-board-api.md) | Free boards are created and managed through the API and MCP | approved |
| [F/collaboration/todos/001077](requirements/functional/collaboration/todos/001077_gremium-board-entries.md) | A board of a Gremium takes more Gremien and persons | approved |
| [F/collaboration/todos/001078](requirements/functional/collaboration/todos/001078_board-rights.md) | Board rights depend on the board kind and its entries | approved |
| [F/finance/budget/000138](requirements/functional/finance/budget/000138_cost-centre-picker.md) | The cost centre pickers are fixed | approved |
| [F/finance/budget/000139](requirements/functional/finance/budget/000139_close-fiscal-year.md) | A fiscal year closes and reopens | approved |
| [F/finance/budget/000140](requirements/functional/finance/budget/000140_default-fiscal-year.md) | The default fiscal year holds today | approved |
| [F/finance/budget/000141](requirements/functional/finance/budget/000141_fiscal-year-delete.md) | A fiscal year in use is not deleted | approved |
| [F/finance/budget/000142](requirements/functional/finance/budget/000142_duplicate-booking.md) | A booking can be duplicated | approved |
| [F/finance/budget/000143](requirements/functional/finance/budget/000143_transfer-kind.md) | A transfer is a kind in the Art filter | approved |
| [F/finance/budget/000144](requirements/functional/finance/budget/000144_cost-centre-items.md) | The cost centre card lists Anträge and bookings | replaced |
| [F/finance/budget/000145](requirements/functional/finance/budget/000145_revert-keeps-invoice.md) | A reverted booking keeps the invoice status | replaced |
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
| [F/finance/budget/000790](requirements/functional/finance/budget/000790_cost-centre-side.md) | A Kostenstelle below the top level has a side | replaced |
| [F/finance/budget/000791](requirements/functional/finance/budget/000791_budget-plan.md) | A fiscal year has one Haushaltsplan with versions | approved |
| [F/finance/budget/000792](requirements/functional/finance/budget/000792_plan-version-steps.md) | A plan version passes the steps of its budget | approved |
| [F/finance/budget/000793](requirements/functional/finance/budget/000793_plan-version-editable.md) | Only a draft version can be edited | approved |
| [F/finance/budget/000794](requirements/functional/finance/budget/000794_plan-line.md) | A plan line holds the Ansatz of one Kostenstelle | approved |
| [F/finance/budget/000795](requirements/functional/finance/budget/000795_plan-balanced.md) | A plan version is balanced before the decision | approved |
| [F/finance/budget/000796](requirements/functional/finance/budget/000796_one-version-in-force.md) | One version of a plan is in force | approved |
| [F/finance/budget/000797](requirements/functional/finance/budget/000797_allocation-from-plan.md) | The plan in force sets the allocations | approved |
| [F/finance/budget/000798](requirements/functional/finance/budget/000798_allocation-locked-by-plan.md) | A year with a plan in force refuses a direct allocation change | approved |
| [F/finance/budget/000799](requirements/functional/finance/budget/000799_nachtrag-from-in-force.md) | A Nachtrag starts as a copy of the version in force | approved |
| [F/finance/budget/000800](requirements/functional/finance/budget/000800_plan-permission.md) | A plan write needs budget.structure | approved |
| [F/finance/budget/000801](requirements/functional/finance/budget/000801_plan-closed-year.md) | A closed fiscal year refuses plan changes | approved |
| [F/finance/budget/000802](requirements/functional/finance/budget/000802_plan-audit.md) | Each plan state change is audited | approved |
| [F/finance/budget/000803](requirements/functional/finance/budget/000803_plan-switch-creates-stammplan.md) | A new fiscal year of a Haushalt with the plan switch gets its draft at once | approved |
| [F/finance/budget/000804](requirements/functional/finance/budget/000804_budget-tab-views.md) | The Haushalt tab has the views Bewirtschaftung and Planung | approved |
| [F/finance/budget/000805](requirements/functional/finance/budget/000805_planning-list.md) | The list of Planung shows the plan as a tree | approved |
| [F/finance/budget/000806](requirements/functional/finance/budget/000806_plan-page-steps.md) | The plan page shows the steps of the version | approved |
| [F/finance/budget/000807](requirements/functional/finance/budget/000807_plan-page-sums.md) | The plan page shows the sums and the balance | approved |
| [F/finance/budget/000808](requirements/functional/finance/budget/000808_plan-page-tables.md) | The plan page lists income and expenses in two tables | approved |
| [F/finance/budget/000809](requirements/functional/finance/budget/000809_plan-page-nachtrag-columns.md) | A Nachtrag is shown beside the version in force | approved |
| [F/finance/budget/000810](requirements/functional/finance/budget/000810_draft-edit-in-table.md) | A draft is edited in the table | approved |
| [F/finance/budget/000811](requirements/functional/finance/budget/000811_plan-submit-needs-balance.md) | An unbalanced draft cannot go to the vote | approved |
| [F/finance/budget/000812](requirements/functional/finance/budget/000812_draft-field-saves-on-leave.md) | An amount field of a draft saves when the person leaves it | approved |
| [F/finance/budget/000814](requirements/functional/finance/budget/000814_plan-switch.md) | A top-level Kostenstelle has a plan switch | approved |
| [F/finance/budget/000815](requirements/functional/finance/budget/000815_planning-detail.md) | The detail of Planung shows the plan or one line | approved |
| [F/finance/budget/000816](requirements/functional/finance/budget/000816_plan-line-marks.md) | A plan line of an expense holds the Vermerke | approved |
| [F/finance/budget/000817](requirements/functional/finance/budget/000817_cost-centre-side-set.md) | The side is set on a direct child of the top level | replaced |
| [F/finance/budget/000818](requirements/functional/finance/budget/000818_plan-line-is-membership.md) | A plan line makes a Kostenstelle part of the year | approved |
| [F/finance/budget/000819](requirements/functional/finance/budget/000819_plan-line-remove.md) | A draft version can lose a line | approved |
| [F/finance/budget/000820](requirements/functional/finance/budget/000820_cost-centre-in-plan-no-delete.md) | A Kostenstelle of a decided plan cannot be deleted | approved |
| [F/finance/budget/000821](requirements/functional/finance/budget/000821_plan-line-snapshot.md) | A decided version keeps the name and the key of each line | approved |
| [F/finance/budget/000822](requirements/functional/finance/budget/000822_year-shows-plan-members.md) | A year with a plan shows only its Kostenstellen | approved |
| [F/finance/budget/000823](requirements/functional/finance/budget/000823_plan-steps-per-budget.md) | A budget holds the steps of its Haushaltsplan | approved |
| [F/finance/budget/000824](requirements/functional/finance/budget/000824_plan-version-keeps-steps.md) | A version keeps the steps it started with | approved |
| [F/finance/budget/000825](requirements/functional/finance/budget/000825_plan-step-recorded.md) | A person records a passed step | approved |
| [F/finance/budget/000826](requirements/functional/finance/budget/000826_plan-step-by-vote.md) | An accepted vote of the Gremium passes its step | replaced |
| [F/finance/budget/000827](requirements/functional/finance/budget/000827_plan-steps-edit.md) | The steps of a budget are edited in its edit form | approved |
| [F/finance/budget/000828](requirements/functional/finance/budget/000828_admin-lists-budgets.md) | Verwaltung lists only the budgets | approved |
| [F/finance/budget/000829](requirements/functional/finance/budget/000829_cost-centre-create-in-budget-tab.md) | A Kostenstelle is created in the Haushalt tab | approved |
| [F/finance/budget/000830](requirements/functional/finance/budget/000830_cost-centre-create-in-draft.md) | A Kostenstelle created in a draft gets a line | approved |
| [F/finance/budget/000831](requirements/functional/finance/budget/000831_cost-centre-edit-in-budget-tab.md) | A Kostenstelle is edited in the Haushalt tab | approved |
| [F/finance/budget/000832](requirements/functional/finance/budget/000832_cost-centre-delete-in-budget-tab.md) | A Kostenstelle is deleted in the Haushalt tab | approved |
| [F/finance/budget/000833](requirements/functional/finance/budget/000833_allocation-set-in-budget-tab.md) | The allocation of a year without a plan in force is set in the Haushalt tab | approved |
| [F/finance/budget/000834](requirements/functional/finance/budget/000834_inactive-cost-centre-hidden.md) | An inactive Kostenstelle is hidden in the Haushalt tab | approved |
| [F/finance/budget/000835](requirements/functional/finance/budget/000835_plan-version-delete.md) | A draft version can be deleted | approved |
| [F/finance/budget/000836](requirements/functional/finance/budget/000836_fiscal-year-delete-with-plan.md) | A fiscal year with a decided plan cannot be deleted | approved |
| [F/finance/budget/000837](requirements/functional/finance/budget/000837_plan-copy-from-year.md) | A new plan can copy the plan of another year | approved |
| [F/finance/budget/000838](requirements/functional/finance/budget/000838_plan-step-vote.md) | The vote of a plan step runs in a meeting of its Gremium | approved |
| [F/finance/budget/000839](requirements/functional/finance/budget/000839_plan-back-to-draft-ends-votes.md) | A version back in draft ends the votes of its steps | approved |
| [F/finance/budget/000840](requirements/functional/finance/budget/000840_plan-page-confirmations.md) | The plan page asks before an action that binds or deletes | approved |
| [F/finance/budget/000841](requirements/functional/finance/budget/000841_plan-step-named.md) | A request that records a step names the step | approved |
| [F/finance/budget/000842](requirements/functional/finance/budget/000842_plan-write-lock.md) | A write in the tree of a budget takes the lock of the budget | approved |
| [F/finance/budget/000844](requirements/functional/finance/budget/000844_gremium-with-budget-not-deleted.md) | A Gremium with a budget is not deleted | approved |
| [F/finance/budget/000845](requirements/functional/finance/budget/000845_fiscal-year-only-through-its-budget.md) | A fiscal year changes only through its own budget | approved |
| [F/finance/budget/000846](requirements/functional/finance/budget/000846_allocation-two-decimal-places.md) | An allocation by hand has at most two decimal places | approved |
| [F/finance/budget/000848](requirements/functional/finance/budget/000848_plan-page-other-budget.md) | Another budget takes the budget before off the plan page | approved |
| [F/finance/budget/000849](requirements/functional/finance/budget/000849_cost-centre-settings-save-order.md) | The settings of a Kostenstelle save one change after the other | approved |
| [F/finance/budget/000850](requirements/functional/finance/budget/000850_cost-centre-text-saved-on-close.md) | A typed text of a Kostenstelle is saved when its section goes off the page | approved |
| [F/finance/budget/000851](requirements/functional/finance/budget/000851_tree-read-order.md) | A budget page drops the answer of an older tree read | approved |
| [F/finance/budget/000852](requirements/functional/finance/budget/000852_budget-law-terms.md) | The budget pages use the words Haushalt, Titel, Ansatz and Haushaltsplan | approved |
| [F/finance/budget/000853](requirements/functional/finance/budget/000853_plan-line-side.md) | The side of a Titel is a part of its plan line | approved |
| [F/finance/budget/000854](requirements/functional/finance/budget/000854_plan-starts-as-draft.md) | A Haushaltsplan starts as a draft | approved |
| [F/finance/budget/000855](requirements/functional/finance/budget/000855_plan-state-by-hand.md) | A person with an own permission sets the state of a plan by hand | approved |
| [F/finance/budget/000874](requirements/functional/finance/budget/000874_plan-coverable-default.md) | A budget says if its new plan lines start deckungsfähig | approved |
| [F/finance/budget/000875](requirements/functional/finance/budget/000875_plan-export.md) | A version of a Haushaltsplan exports as XLSX and as PDF | approved |
| [F/finance/budget/000876](requirements/functional/finance/budget/000876_plan-in-protocol.md) | A plan on the agenda is an Anlage of the protocol | approved |
| [F/finance/budget/000877](requirements/functional/finance/budget/000877_rename-in-draft.md) | A Kostenstelle of a Haushalt with a plan gets a new key or name in a draft | approved |
| [F/finance/budget/000878](requirements/functional/finance/budget/000878_path-key-one-hyphen.md) | The path key of a Kostenstelle has one hyphen | approved |
| [F/finance/budget/000879](requirements/functional/finance/budget/000879_budget-year-before-cost-centre.md) | A person chooses Haushalt and Haushaltsjahr before the Kostenstelle | approved |
| [F/finance/budget/000889](requirements/functional/finance/budget/000889_year-before-needs-plan.md) | The columns of the year before show only when that year has a plan | approved |
| [F/finance/budget/000890](requirements/functional/finance/budget/000890_deciding-gremium-reads-haushalt.md) | A Gremium that decides a plan reads the Haushalt | approved |
| [F/finance/budget/000927](requirements/functional/finance/budget/000927_gremium-delete-takes-tree-lock.md) | The delete of a Gremium takes the lock of each tree that names it | approved |
| [F/finance/budget/000928](requirements/functional/finance/budget/000928_plan-readable-question.md) | A page asks whether the reader reads a plan and gets no 403 | approved |
| [F/finance/budget/000929](requirements/functional/finance/budget/000929_plan-line-with-bookings-stays.md) | The line of a Kostenstelle with bookings is not removed | approved |
| [F/finance/budget/000930](requirements/functional/finance/budget/000930_fiscal-year-audit.md) | The create and the change of a fiscal year are in the audit log | approved |
| [F/finance/budget/000964](requirements/functional/finance/budget/000964_plan-pdf-head-line.md) | The head line of the plan PDF sits tight between the title and the table | approved |
| [F/finance/budget/000968](requirements/functional/finance/budget/000968_plan-pdf-parent-lines-grey.md) | The plan PDF prints a line with lines below it in grey | approved |
| [F/finance/budget/000990](requirements/functional/finance/budget/000990_late-booking-in-past-year.md) | A past fiscal year that is not closed takes a booking with a date in the year | approved |
| [F/finance/budget/000991](requirements/functional/finance/budget/000991_close-names-open-antraege.md) | The close of a fiscal year names what stays open, and an Antrag can leave a closed year | approved |
| [F/finance/budget/000992](requirements/functional/finance/budget/000992_stichtag-keeps-closed-years.md) | A new Stichtag moves only the fiscal years that are not closed | approved |
| [F/finance/budget/001021](requirements/functional/finance/budget/001021_plan-change-needs-comparison.md) | A plan shows the Änderung only against an Ansatz | approved |
| [F/finance/budget/001030](requirements/functional/finance/budget/001030_antrag-takes-expense-cost-centre.md) | An Antrag takes only a Kostenstelle on the expense side | approved |
| [F/finance/budget/001031](requirements/functional/finance/budget/001031_antrag-takes-leaf-cost-centre.md) | An Antrag takes only a Kostenstelle without a Kostenstelle below it | approved |
| [F/finance/budget/001032](requirements/functional/finance/budget/001032_booking-takes-leaf-cost-centre.md) | A booking takes only a Kostenstelle without a Kostenstelle below it | approved |
| [F/finance/budget/001033](requirements/functional/finance/budget/001033_antrag-without-money-takes-no-cost-centre.md) | An Antrag of a type without money takes no Kostenstelle | approved |
| [F/finance/budget/001040](requirements/functional/finance/budget/001040_plan-line-predecessor.md) | A plan line can name its predecessor in the year before | approved |
| [F/finance/budget/001041](requirements/functional/finance/budget/001041_plan-row-sums-rows-below.md) | A row without its own figure of the year before sums the rows below it | approved |
| [F/finance/budget/001042](requirements/functional/finance/budget/001042_plan-line-year-before-by-hand.md) | A plan line can set the Ansatz and the Ist of the year before by hand | approved |
| [F/finance/budget/001130](requirements/functional/finance/budget/001130_plan-lines-as-tree.md) | The lines of a plan show as a tree | approved |
| [F/finance/budget/001260](requirements/functional/finance/budget/001260_income-titel-figures.md) | An income Titel shows Ansatz, Ist and the deviation | approved |
| [F/finance/budget/001261](requirements/functional/finance/budget/001261_income-titel-refund.md) | An expense booking on an income Titel is a Rückzahlung | approved |
| [F/finance/budget/001262](requirements/functional/finance/budget/001262_income-titel-not-available.md) | The Ist of an income Titel does not raise the Verfügbar of the Haushalt | approved |
| [F/finance/budget/001263](requirements/functional/finance/budget/001263_income-titel-tree-row.md) | The tree row of an income Titel shows its Ansatz and the reached part | approved |
| [F/finance/budget/001264](requirements/functional/finance/budget/001264_income-titel-section.md) | Income nodes are listed under "Einnahmen" | approved |
| [F/finance/budget/001872](requirements/functional/finance/budget/001872_view-bookings-filtered.md) | Buchungen ansehen opens the bookings of the cost centre and the year | approved |
| [F/finance/budget/001873](requirements/functional/finance/budget/001873_cost-centre-items-two-links.md) | The cost centre card lists Anträge and bookings and links to both lists | approved |
| [F/finance/budget/001874](requirements/functional/finance/budget/001874_bookings-fiscal-year-filter.md) | The bookings list filters by Haushaltsjahr | approved |
| [F/finance/invoices/000260](requirements/functional/finance/invoices/000260_invoice-bookings.md) | An invoice is a document with many bookings | approved |
| [F/finance/invoices/000261](requirements/functional/finance/invoices/000261_paid-by-user.md) | Only a user sets an invoice to paid | replaced |
| [F/finance/invoices/000263](requirements/functional/finance/invoices/000263_zugferd-import.md) | A ZUGFeRD invoice fills the form | approved |
| [F/finance/invoices/001290](requirements/functional/finance/invoices/001290_booking-pays-invoice.md) | A new booking sets its invoice to paid | approved |
| [F/finance/invoices/001291](requirements/functional/finance/invoices/001291_revert-reopens-invoice.md) | The revert of a booking sets the invoice it paid back to open | approved |
| [F/finance/invoices/001292](requirements/functional/finance/invoices/001292_invoice-menu-books.md) | The head menu of an invoice has "Buchung anlegen" | approved |
| [F/integrations/external/000176](requirements/functional/integrations/external/000176_optional.md) | Integrations are optional | approved |
| [F/integrations/external/000177](requirements/functional/integrations/external/000177_preview-access.md) | A link preview uses the access of the viewer | approved |
| [F/integrations/mcp/000174](requirements/functional/integrations/mcp/000174_acts-as-user.md) | The MCP server acts as the logged-in user | approved |
| [F/integrations/mcp/000272](requirements/functional/integrations/mcp/000272_token-scope.md) | An agent token has a scope and a lifetime | approved |
| [F/integrations/mcp/000273](requirements/functional/integrations/mcp/000273_forbidden-permissions.md) | An agent never casts a ballot or merges accounts | replaced |
| [F/integrations/mcp/000274](requirements/functional/integrations/mcp/000274_revoke-grants.md) | Tokens can be revoked | approved |
| [F/integrations/mcp/000385](requirements/functional/integrations/mcp/000385_version-bump.md) | The MCP version moves with its tools | replaced |
| [F/integrations/mcp/000386](requirements/functional/integrations/mcp/000386_no-ballot-tool.md) | The MCP has no ballot tool | approved |
| [F/integrations/mcp/000387](requirements/functional/integrations/mcp/000387_idp-roles-read-only.md) | Memberships and roles are read-only in the MCP | replaced |
| [F/integrations/mcp/000462](requirements/functional/integrations/mcp/000462_forbidden-permissions.md) | No agent token gets a human-only permission | approved |
| [F/integrations/mcp/001200](requirements/functional/integrations/mcp/001200_mcp-parity.md) | The MCP server has a tool for every app function | approved |
| [F/integrations/mcp/001201](requirements/functional/integrations/mcp/001201_mcp-exclusions.md) | The MCP leaves out a closed list of functions | approved |
| [F/integrations/mcp/001232](requirements/functional/integrations/mcp/001232_mcp-name.md) | The MCP server presents itself as workflow | approved |
| [F/integrations/paperless/002511](requirements/functional/integrations/paperless/002511_connection-page.md) | An admin connects one Paperless instance | approved |
| [F/integrations/paperless/002512](requirements/functional/integrations/paperless/002512_switch.md) | Each part of the Paperless integration has its own switch | approved |
| [F/integrations/paperless/002513](requirements/functional/integrations/paperless/002513_service-account.md) | Each call to Paperless uses the token of the connection | approved |
| [F/integrations/paperless/002516](requirements/functional/integrations/paperless/002516_file-final-protocol.md) | A final protocol is filed in Paperless | approved |
| [F/integrations/paperless/002517](requirements/functional/integrations/paperless/002517_file-decided-antrag.md) | The PDF of an Antrag is filed at each decision | approved |
| [F/integrations/paperless/002518](requirements/functional/integrations/paperless/002518_file-plan-in-force.md) | A Haushaltsplan is filed when it comes into force | approved |
| [F/integrations/paperless/002519](requirements/functional/integrations/paperless/002519_document-data.md) | A filed document carries type, date, Gremium and link | approved |
| [F/integrations/paperless/002520](requirements/functional/integrations/paperless/002520_filed-once.md) | A file is filed only once | approved |
| [F/integrations/paperless/002521](requirements/functional/integrations/paperless/002521_new-version.md) | A new version becomes a new document | approved |
| [F/integrations/paperless/002522](requirements/functional/integrations/paperless/002522_no-delete.md) | The platform deletes no document in Paperless | approved |
| [F/integrations/paperless/002523](requirements/functional/integrations/paperless/002523_filing-in-worker.md) | Filing runs in the worker and never blocks an action | approved |
| [F/integrations/paperless/002524](requirements/functional/integrations/paperless/002524_permission-use.md) | One permission gives the use of Paperless | approved |
| [F/integrations/paperless/002525](requirements/functional/integrations/paperless/002525_open-in-paperless.md) | An element with a filed document links to Paperless | approved |
| [F/integrations/paperless/002526](requirements/functional/integrations/paperless/002526_failed-filings.md) | The admin page lists the filings that failed | approved |
| [F/integrations/paperless/002527](requirements/functional/integrations/paperless/002527_insert-slash-command.md) | The command Paperless opens the Paperless search in a protocol text | approved |
| [F/integrations/paperless/002528](requirements/functional/integrations/paperless/002528_insert-copies.md) | An insert from Paperless copies the document as an embedded PDF | approved |
| [F/integrations/paperless/002529](requirements/functional/integrations/paperless/002529_search-outage.md) | The Paperless search tells an outage and keeps the editor | approved |
| [F/integrations/paperless/002530](requirements/functional/integrations/paperless/002530_backfill.md) | An admin can file the final documents that exist | approved |
| [F/integrations/paperless/002531](requirements/functional/integrations/paperless/002531_audit.md) | Each filing and each insert has an audit entry | approved |
| [F/integrations/paperless/002534](requirements/functional/integrations/paperless/002534_search-like-global-search.md) | The Paperless search looks like the global search | approved |
| [F/integrations/paperless/002535](requirements/functional/integrations/paperless/002535_file-antrag-attachments.md) | The attachments of an Antrag are filed with its PDF | approved |
| [F/integrations/paperless/002762](requirements/functional/integrations/paperless/002762_feature-switch.md) | Paperless has a feature switch | approved |
| [F/integrations/paperless/002763](requirements/functional/integrations/paperless/002763_link-kind.md) | A Paperless document is a kind of link end | approved |
| [F/integrations/paperless/002764](requirements/functional/integrations/paperless/002764_link-permission.md) | A Paperless link needs the Paperless permission | approved |
| [F/integrations/paperless/002765](requirements/functional/integrations/paperless/002765_link-title-stored.md) | A Paperless link keeps the title from the moment of the link | approved |
| [F/integrations/paperless/002766](requirements/functional/integrations/paperless/002766_link-search.md) | The link search finds Paperless documents | approved |
| [F/integrations/paperless/002767](requirements/functional/integrations/paperless/002767_link-switch.md) | The links to Paperless have their own switch | approved |
| [F/integrations/paperless/002768](requirements/functional/integrations/paperless/002768_link-graph.md) | The graph shows linked Paperless documents | approved |
| [F/integrations/paperless/002813](requirements/functional/integrations/paperless/002813_address-change-needs-token.md) | A change of the Paperless address needs the token again | approved |
| [F/integrations/paperless/002844](requirements/functional/integrations/paperless/002844_links-name-public-address.md) | A link to Paperless names the address for links | approved |
| [F/integrations/ticket-mail/002720](requirements/functional/integrations/ticket-mail/002720_postfach-per-bereich.md) | A Bereich has at most one Postfach | approved |
| [F/integrations/ticket-mail/002721](requirements/functional/integrations/ticket-mail/002721_postfach-page.md) | An admin sets the Postfach on the admin page | approved |
| [F/integrations/ticket-mail/002722](requirements/functional/integrations/ticket-mail/002722_postfach-switch.md) | Each Postfach has a switch | approved |
| [F/integrations/ticket-mail/002723](requirements/functional/integrations/ticket-mail/002723_fetch-in-worker.md) | The worker fetches the mails each minute | approved |
| [F/integrations/ticket-mail/002724](requirements/functional/integrations/ticket-mail/002724_mail-imported-once.md) | A mail is imported one time | approved |
| [F/integrations/ticket-mail/002725](requirements/functional/integrations/ticket-mail/002725_mail-becomes-ticket.md) | A new mail becomes a ticket | approved |
| [F/integrations/ticket-mail/002726](requirements/functional/integrations/ticket-mail/002726_thread-by-headers.md) | An answer joins its ticket through the mail headers | approved |
| [F/integrations/ticket-mail/002727](requirements/functional/integrations/ticket-mail/002727_thread-by-number.md) | The number in the subject joins only a mail of a participant | approved |
| [F/integrations/ticket-mail/002728](requirements/functional/integrations/ticket-mail/002728_mail-as-text.md) | A mail shows as text only | approved |
| [F/integrations/ticket-mail/002729](requirements/functional/integrations/ticket-mail/002729_mail-source-kept.md) | The platform keeps the source of each mail | approved |
| [F/integrations/ticket-mail/002730](requirements/functional/integrations/ticket-mail/002730_mail-attachments.md) | The attachments of a mail become files of the message | approved |
| [F/integrations/ticket-mail/002731](requirements/functional/integrations/ticket-mail/002731_mail-stays-in-postfach.md) | An imported mail moves to a folder and is never deleted | approved |
| [F/integrations/ticket-mail/002732](requirements/functional/integrations/ticket-mail/002732_automatic-mails.md) | An automatic mail opens no ticket | approved |
| [F/integrations/ticket-mail/002733](requirements/functional/integrations/ticket-mail/002733_answer-as-mail.md) | A public message on a mail ticket goes out as a mail | approved |
| [F/integrations/ticket-mail/002734](requirements/functional/integrations/ticket-mail/002734_answer-headers.md) | A sent mail carries the thread headers and the number | approved |
| [F/integrations/ticket-mail/002735](requirements/functional/integrations/ticket-mail/002735_answer-recipients.md) | An answer goes to the sender and to the Cc addresses of the thread | approved |
| [F/integrations/ticket-mail/002736](requirements/functional/integrations/ticket-mail/002736_answer-sender.md) | A sent mail comes from the address of the Postfach | approved |
| [F/integrations/ticket-mail/002737](requirements/functional/integrations/ticket-mail/002737_send-in-worker.md) | The worker sends a mail and shows a failure on the message | approved |
| [F/integrations/ticket-mail/002738](requirements/functional/integrations/ticket-mail/002738_confirmation-mail.md) | A new mail ticket gets a confirmation | approved |
| [F/integrations/ticket-mail/002739](requirements/functional/integrations/ticket-mail/002739_mail-sender-is-address.md) | The sender of a mail ticket is the address, not an account | approved |
| [F/integrations/ticket-mail/002740](requirements/functional/integrations/ticket-mail/002740_blocked-mail-sender.md) | The mail of a blocked sender becomes no ticket | approved |
| [F/integrations/ticket-mail/002741](requirements/functional/integrations/ticket-mail/002741_mail-rate-limit.md) | One address opens at most 20 tickets an hour by mail | approved |
| [F/integrations/ticket-mail/002742](requirements/functional/integrations/ticket-mail/002742_file-to-paperless.md) | The team files an attachment of a ticket in Paperless | approved |
| [F/integrations/ticket-mail/002743](requirements/functional/integrations/ticket-mail/002743_postfach-audit.md) | A change of a Postfach is in the audit log | approved |
| [F/integrations/ticket-mail/002812](requirements/functional/integrations/ticket-mail/002812_account-change-needs-password.md) | A change of a mail account needs its password again | approved |
| [F/integrations/ticket-mail/002814](requirements/functional/integrations/ticket-mail/002814_confirmation-names-number.md) | The confirmation names only the number of the ticket | approved |
| [F/integrations/ticket-mail/002815](requirements/functional/integrations/ticket-mail/002815_confirmation-cap.md) | A Postfach sends at most 30 confirmations an hour | approved |
| [F/integrations/ticket-mail/002816](requirements/functional/integrations/ticket-mail/002816_unchecked-sender-marked.md) | A mail message of an unchecked sender is marked | approved |
| [F/integrations/webhooks/000298](requirements/functional/integrations/webhooks/000298_retry.md) | A failed delivery is retried with backoff | approved |
| [F/integrations/webhooks/000299](requirements/functional/integrations/webhooks/000299_idempotent-delivery.md) | A delivery runs once per key | approved |
| [F/integrations/webhooks/000402](requirements/functional/integrations/webhooks/000402_flow-action-only.md) | A webhook fires only through a flow action | replaced |
| [F/integrations/webhooks/000403](requirements/functional/integrations/webhooks/000403_delete-webhook.md) | A webhook can be deleted | approved |
| [F/integrations/webhooks/002410](requirements/functional/integrations/webhooks/002410_event-subscriptions.md) | A webhook subscribes to events | approved |
| [F/integrations/webhooks/002411](requirements/functional/integrations/webhooks/002411_event-catalog.md) | The webhook events come from a fixed catalog | approved |
| [F/integrations/webhooks/002412](requirements/functional/integrations/webhooks/002412_payload-fields.md) | A webhook chooses the payload fields per event | approved |
| [F/integrations/webhooks/002413](requirements/functional/integrations/webhooks/002413_personal-fields.md) | A personal payload field is marked and off by default | approved |
| [F/integrations/webhooks/002414](requirements/functional/integrations/webhooks/002414_filters.md) | A webhook filters by Gremium, Antragsart and target status | approved |
| [F/integrations/webhooks/002415](requirements/functional/integrations/webhooks/002415_payload-preview.md) | The webhook dialog shows a payload preview | approved |
| [F/integrations/webhooks/002416](requirements/functional/integrations/webhooks/002416_test-delivery.md) | A webhook can send a test delivery | approved |
| [F/integrations/webhooks/002417](requirements/functional/integrations/webhooks/002417_payload-at-event-time.md) | The payload is built when the event occurs | approved |
| [F/integrations/webhooks/002749](requirements/functional/integrations/webhooks/002749_ticket-event-bereich.md) | The ticket event names the Bereich and follows the Gremium filter | approved |
| [F/integrations/webhooks/002750](requirements/functional/integrations/webhooks/002750_ticket-message-event.md) | A message of the sender is a webhook event | approved |
| [F/integrations/webhooks/002751](requirements/functional/integrations/webhooks/002751_ticket-status-event.md) | A status change of a ticket is a webhook event | approved |
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
| [F/meetings/calendar/000727](requirements/functional/meetings/calendar/000727_calendar-search.md) | The Kalender search jumps to the hit | approved |
| [F/meetings/calendar/000729](requirements/functional/meetings/calendar/000729_external-calendars-admin-page.md) | The admin page Kalender lists and edits the external calendars | approved |
| [F/meetings/calendar/000730](requirements/functional/meetings/calendar/000730_public-termin.md) | A Termin can be public | approved |
| [F/meetings/calendar/000731](requirements/functional/meetings/calendar/000731_public-calendar-page.md) | The public calendar page shows the public entries | approved |
| [F/meetings/calendar/000732](requirements/functional/meetings/calendar/000732_public-meetings.md) | The public calendar shows the meetings of Gremien with public protocols | approved |
| [F/meetings/calendar/000733](requirements/functional/meetings/calendar/000733_public-ics-feed.md) | The public calendar has an ICS feed without a token | approved |
| [F/meetings/calendar/000734](requirements/functional/meetings/calendar/000734_public-calendar-noindex.md) | The public calendar is not indexed | approved |
| [F/meetings/calendar/000737](requirements/functional/meetings/calendar/000737_event-as-termin.md) | The Kalender shows an Event like a Termin | approved |
| [F/meetings/calendar/000738](requirements/functional/meetings/calendar/000738_termin-invite-person-search.md) | The invitation search finds each active account by name | approved |
| [F/meetings/calendar/000740](requirements/functional/meetings/calendar/000740_termin-open-answers.md) | The answer list of a Termin names the invited persons without an answer | approved |
| [F/meetings/calendar/000973](requirements/functional/meetings/calendar/000973_rule-with-day-times.md) | A recurrence rule with times of the day gives only the first date | approved |
| [F/meetings/calendar/000974](requirements/functional/meetings/calendar/000974_feed-read-time-limit.md) | The read of an external feed has a time limit | approved |
| [F/meetings/calendar/001094](requirements/functional/meetings/calendar/001094_feed-name.md) | A calendar feed is named by the short name | approved |
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
| [F/meetings/delegations/000447](requirements/functional/meetings/delegations/000447_pool-seat-live.md) | Pool seats need only a live meeting | replaced |
| [F/meetings/delegations/000461](requirements/functional/meetings/delegations/000461_external-delegates.md) | External delegates need a Gremium switch | approved |
| [F/meetings/delegations/000909](requirements/functional/meetings/delegations/000909_delegate-limit.md) | A delegate holds a limited number of delegations | approved |
| [F/meetings/delegations/000910](requirements/functional/meetings/delegations/000910_no-delegation-in-election.md) | An election takes no delegation ballot | approved |
| [F/meetings/delegations/000938](requirements/functional/meetings/delegations/000938_pool-substitute-votes-in-election.md) | A pool substitute votes in an election | approved |
| [F/meetings/delegations/002692](requirements/functional/meetings/delegations/002692_substitutes-page-per-gremium.md) | The Stellvertretungen of a Gremium have their own page | approved |
| [F/meetings/delegations/002900](requirements/functional/meetings/delegations/002900_delegation-carries-the-vote.md) | A delegation always transfers the voting right | approved |
| [F/meetings/delegations/002901](requirements/functional/meetings/delegations/002901_planned-delegations-get-the-vote.md) | Delegations of planned meetings get the voting right | approved |
| [F/meetings/meetings/000092](requirements/functional/meetings/meetings/000092_open-window.md) | A meeting opens in a configured window | approved |
| [F/meetings/meetings/000093](requirements/functional/meetings/meetings/000093_state-order.md) | Meeting states move only forward | approved |
| [F/meetings/meetings/000094](requirements/functional/meetings/meetings/000094_close-with-open-vote.md) | A meeting with an open vote does not close | approved |
| [F/meetings/meetings/000095](requirements/functional/meetings/meetings/000095_prepare-before-open.md) | The protocol and votes can be prepared before the open | approved |
| [F/meetings/meetings/000096](requirements/functional/meetings/meetings/000096_no-prep-page.md) | There is no preparation page | approved |
| [F/meetings/meetings/000097](requirements/functional/meetings/meetings/000097_delete-removes-votes.md) | A meeting delete removes its votes | approved |
| [F/meetings/meetings/000098](requirements/functional/meetings/meetings/000098_agenda-changes.md) | Agenda changes only while planned or live | approved |
| [F/meetings/meetings/000099](requirements/functional/meetings/meetings/000099_top-text-editable.md) | A TOP text is editable until the protocol is final | approved |
| [F/meetings/meetings/000102](requirements/functional/meetings/meetings/000102_top-attachments-internal.md) | TOP attachments are internal | approved |
| [F/meetings/meetings/000103](requirements/functional/meetings/meetings/000103_attendance.md) | Lead-set attendance wins | approved |
| [F/meetings/meetings/000104](requirements/functional/meetings/meetings/000104_qr-only-without-quorum.md) | Public participation only without quorum | replaced |
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
| [F/meetings/meetings/000861](requirements/functional/meetings/meetings/000861_freetext-top-description.md) | A free-text TOP takes a description that opens its text as a quote | approved |
| [F/meetings/meetings/000903](requirements/functional/meetings/meetings/000903_meeting-kind.md) | A meeting has a kind | approved |
| [F/meetings/meetings/000904](requirements/functional/meetings/meetings/000904_guests-may-vote.md) | Guest ballots are a Gremium setting | approved |
| [F/meetings/meetings/000905](requirements/functional/meetings/meetings/000905_public-watch-with-quorum.md) | A Gremium with a quorum lets guests only watch | approved |
| [F/meetings/meetings/000907](requirements/functional/meetings/meetings/000907_meeting-place-form.md) | A meeting has a place and a form | approved |
| [F/meetings/meetings/000918](requirements/functional/meetings/meetings/000918_late-invite-warning.md) | A late meeting date shows a warning | approved |
| [F/meetings/meetings/000920](requirements/functional/meetings/meetings/000920_unexcused-count.md) | The Gremium page counts the unexcused absences of a term | approved |
| [F/meetings/meetings/000921](requirements/functional/meetings/meetings/000921_absence-notice.md) | The lead gets a mail before a member reaches the absence limit | approved |
| [F/meetings/meetings/000922](requirements/functional/meetings/meetings/000922_late-excuse.md) | A member can give an excuse after the meeting | approved |
| [F/meetings/meetings/000923](requirements/functional/meetings/meetings/000923_attendance-export.md) | The attendance of a Gremium exports as XLSX | approved |
| [F/meetings/meetings/000940](requirements/functional/meetings/meetings/000940_repeat-names-first-meeting.md) | A repeat meeting names its first meeting | approved |
| [F/meetings/meetings/000941](requirements/functional/meetings/meetings/000941_absence-term-choice.md) | The absence count and the export offer each term | approved |
| [F/meetings/meetings/000943](requirements/functional/meetings/meetings/000943_late-excuse-notice.md) | A late excuse sends a mail to the lead | approved |
| [F/meetings/meetings/000946](requirements/functional/meetings/meetings/000946_one-present-count.md) | A meeting shows one count of present members | approved |
| [F/meetings/meetings/000948](requirements/functional/meetings/meetings/000948_term-start-per-gremium.md) | Each Gremium has its own start month of the term | approved |
| [F/meetings/meetings/000951](requirements/functional/meetings/meetings/000951_attendance-until-final.md) | The lead corrects the attendance until the protocol is final | approved |
| [F/meetings/meetings/000982](requirements/functional/meetings/meetings/000982_closed-meeting-open-until-final.md) | A closed meeting stays open for corrections until its protocol is final | approved |
| [F/meetings/meetings/001140](requirements/functional/meetings/meetings/001140_top-duration.md) | A TOP carries an estimated duration | approved |
| [F/meetings/meetings/001141](requirements/functional/meetings/meetings/001141_agenda-time-plan.md) | The agenda shows a time plan from the durations | approved |
| [F/meetings/meetings/001142](requirements/functional/meetings/meetings/001142_plan-without-start.md) | Without a start time the agenda shows only durations | approved |
| [F/meetings/meetings/001143](requirements/functional/meetings/meetings/001143_live-plan.md) | A live Sitzung computes the plan of the open TOPs again | approved |
| [F/meetings/meetings/001144](requirements/functional/meetings/meetings/001144_planned-end-overrun.md) | The agenda shows no planned end and no overrun | approved |
| [F/meetings/meetings/001145](requirements/functional/meetings/meetings/001145_time-plan-internal.md) | The time plan stays internal | approved |
| [F/meetings/meetings/001310](requirements/functional/meetings/meetings/001310_attendance-pool-rows.md) | The attendance matrix shows the pool substitutes | approved |
| [F/meetings/meetings/001311](requirements/functional/meetings/meetings/001311_attendance-pool-cell.md) | A pool cell counts the pool seats | approved |
| [F/meetings/meetings/001312](requirements/functional/meetings/meetings/001312_attendance-average-pool-seats.md) | The attendance average counts the pool seats | approved |
| [F/meetings/meetings/001462](requirements/functional/meetings/meetings/001462_sheet-opens-for-voters.md) | The vote sheet opens by itself for a voter | approved |
| [F/meetings/meetings/001738](requirements/functional/meetings/meetings/001738_live-channel-reconnects.md) | The meeting page opens a dropped live channel again | approved |
| [F/meetings/meetings/001739](requirements/functional/meetings/meetings/001739_live-resync-on-return.md) | A live meeting page connects and reads again when the page returns | approved |
| [F/meetings/meetings/001804](requirements/functional/meetings/meetings/001804_vote-tab-final-protocol.md) | A closed meeting keeps the vote tab | approved |
| [F/meetings/meetings/001871](requirements/functional/meetings/meetings/001871_meetings-committee-param.md) | The meeting list reads the Gremium filter from the URL | approved |
| [F/meetings/protocols/000115](requirements/functional/meetings/protocols/000115_keeper-permission.md) | The keeper holds protocol.write | approved |
| [F/meetings/protocols/000116](requirements/functional/meetings/protocols/000116_finalize.md) | Finalize needs a closed meeting and protocol.finalize | approved |
| [F/meetings/protocols/000117](requirements/functional/meetings/protocols/000117_delete-draft-only.md) | Only a draft protocol is deleted | approved |
| [F/meetings/protocols/000118](requirements/functional/meetings/protocols/000118_pdf-name.md) | The PDF is named after the meeting | approved |
| [F/meetings/protocols/000119](requirements/functional/meetings/protocols/000119_signatures-one-page.md) | The signature block stays on one page | approved |
| [F/meetings/protocols/000120](requirements/functional/meetings/protocols/000120_election-ranking.md) | An election shows a ranking | approved |
| [F/meetings/protocols/000354](requirements/functional/meetings/protocols/000354_built-from-tops.md) | The protocol is built from the TOP texts | approved |
| [F/meetings/protocols/000355](requirements/functional/meetings/protocols/000355_public-variant.md) | A non-public TOP gives a second PDF | approved |
| [F/meetings/protocols/000356](requirements/functional/meetings/protocols/000356_render-before-commit.md) | A failed render keeps the draft | approved |
| [F/meetings/protocols/000357](requirements/functional/meetings/protocols/000357_roster-quorum.md) | The quorum of a protocol uses the counts of the close | approved |
| [F/meetings/protocols/000358](requirements/functional/meetings/protocols/000358_protocol-mail.md) | The protocol mail carries the PDF | approved |
| [F/meetings/protocols/000359](requirements/functional/meetings/protocols/000359_cd-variant.md) | The CD variant selects the layout | approved |
| [F/meetings/protocols/000360](requirements/functional/meetings/protocols/000360_text-is-data.md) | Protocol text is data, never code | approved |
| [F/meetings/protocols/000361](requirements/functional/meetings/protocols/000361_image-budget.md) | A protocol shows at most 48 images | approved |
| [F/meetings/protocols/000685](requirements/functional/meetings/protocols/000685_blackout-syntax.md) | Protocol text marks a segment for blackout | approved |
| [F/meetings/protocols/000686](requirements/functional/meetings/protocols/000686_blackout-unclosed.md) | An open blackout marker stops the finalize | approved |
| [F/meetings/protocols/000691](requirements/functional/meetings/protocols/000691_blackout-mail.md) | A marked segment sends the public PDF to the mailing list | approved |
| [F/meetings/protocols/000862](requirements/functional/meetings/protocols/000862_pdf-embed.md) | A protocol text embeds a PDF | approved |
| [F/meetings/protocols/000864](requirements/functional/meetings/protocols/000864_pdf-appendix.md) | The protocol PDF appends each embedded PDF as an Anlage | approved |
| [F/meetings/protocols/000865](requirements/functional/meetings/protocols/000865_pdf-watermark.md) | Each page of an Anlage has a watermark | approved |
| [F/meetings/protocols/000866](requirements/functional/meetings/protocols/000866_pdf-reference-link.md) | The place of an embedded PDF links to its Anlage | approved |
| [F/meetings/protocols/000867](requirements/functional/meetings/protocols/000867_pdf-public-variant.md) | The PDF of a non-public TOP stays internal | approved |
| [F/meetings/protocols/000868](requirements/functional/meetings/protocols/000868_pdf-budget.md) | A protocol holds at most 20 Anlagen | approved |
| [F/meetings/protocols/000870](requirements/functional/meetings/protocols/000870_top-time-recorded.md) | The move to a TOP records its time | approved |
| [F/meetings/protocols/000871](requirements/functional/meetings/protocols/000871_top-time-in-pdf.md) | The protocol PDF shows the time above each TOP | approved |
| [F/meetings/protocols/000872](requirements/functional/meetings/protocols/000872_time-note-syntax.md) | A protocol text marks a time note | approved |
| [F/meetings/protocols/000884](requirements/functional/meetings/protocols/000884_application-appendix.md) | An Antrag on the agenda is an Anlage of the protocol | approved |
| [F/meetings/protocols/000885](requirements/functional/meetings/protocols/000885_application-snapshot.md) | The Anlage holds the Antrag as the Sitzung treated it | approved |
| [F/meetings/protocols/000886](requirements/functional/meetings/protocols/000886_application-public-redaction.md) | The public Anlage blacks out the personal data | approved |
| [F/meetings/protocols/000908](requirements/functional/meetings/protocols/000908_protocol-header-place-form.md) | The protocol names the kind, the place and the form of the meeting | approved |
| [F/meetings/protocols/000916](requirements/functional/meetings/protocols/000916_circular-in-protocol.md) | The next protocol lists the Umlaufverfahren | replaced |
| [F/meetings/protocols/000924](requirements/functional/meetings/protocols/000924_protocol-approved.md) | A final protocol can be marked as approved | approved |
| [F/meetings/protocols/000925](requirements/functional/meetings/protocols/000925_protocol-draft-mail.md) | The keeper sends the protocol draft to the members | approved |
| [F/meetings/protocols/000934](requirements/functional/meetings/protocols/000934_circular-decisions-public.md) | A circular decision is public where the protocol is public | replaced |
| [F/meetings/protocols/000937](requirements/functional/meetings/protocols/000937_draft-mail-limits.md) | The draft mail waits for the end of the meeting and asks before a repeat | approved |
| [F/meetings/protocols/000950](requirements/functional/meetings/protocols/000950_protocol-draft-pdf.md) | The draft of a protocol reads as a PDF after the meeting | approved |
| [F/meetings/protocols/000952](requirements/functional/meetings/protocols/000952_finalize-asks-first.md) | The finalize of a protocol asks first | approved |
| [F/meetings/protocols/000965](requirements/functional/meetings/protocols/000965_blackout-block.md) | Protocol text marks a block for blackout | approved |
| [F/meetings/protocols/000966](requirements/functional/meetings/protocols/000966_blackout-block-attachments.md) | An attachment in a blackout block stays out of the public protocol | approved |
| [F/meetings/protocols/000970](requirements/functional/meetings/protocols/000970_known-names.md) | The known names are the persons of the platform | approved |
| [F/meetings/protocols/000983](requirements/functional/meetings/protocols/000983_final-protocol-back-to-draft.md) | A final protocol goes back to draft until it is approved | approved |
| [F/meetings/protocols/000997](requirements/functional/meetings/protocols/000997_sent-only-with-mail.md) | A protocol counts as sent only when its mail went out | approved |
| [F/meetings/protocols/002780](requirements/functional/meetings/protocols/002780_selection-format-bar.md) | A text selection shows a format bar | approved |
| [F/meetings/protocols/002781](requirements/functional/meetings/protocols/002781_selection-bar-formats.md) | The format bar holds the inline formats | approved |
| [F/meetings/protocols/002782](requirements/functional/meetings/protocols/002782_selection-bar-place.md) | The format bar shows below the selection | approved |
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
| [F/meetings/voting/000382](requirements/functional/meetings/voting/000382_delegation-ballot.md) | A delegation ballot is a ballot of its own | approved |
| [F/meetings/voting/000894](requirements/functional/meetings/voting/000894_members-majority.md) | A vote can need the majority of the members | approved |
| [F/meetings/voting/000895](requirements/functional/meetings/voting/000895_members-two-thirds.md) | A vote can need two thirds of the members | approved |
| [F/meetings/voting/000896](requirements/functional/meetings/voting/000896_members-rule-fails-closed.md) | A members rule without an eligible count rejects | approved |
| [F/meetings/voting/000897](requirements/functional/meetings/voting/000897_majority-rule-choice.md) | The vote form offers five majority rules | approved |
| [F/meetings/voting/000898](requirements/functional/meetings/voting/000898_members-rule-no-guests.md) | A vote with a members rule has no guest ballots | approved |
| [F/meetings/voting/000899](requirements/functional/meetings/voting/000899_plan-vote-members-majority.md) | The vote on a Haushaltsplan needs the majority of the members | approved |
| [F/meetings/voting/000900](requirements/functional/meetings/voting/000900_quorum-counts-present.md) | The quorum of a meeting vote counts the present members | approved |
| [F/meetings/voting/000901](requirements/functional/meetings/voting/000901_quorum-min-present.md) | A Gremium can need a least number of present members | approved |
| [F/meetings/voting/000902](requirements/functional/meetings/voting/000902_repeat-quorum.md) | A Wiederholungssitzung has its own quorum | approved |
| [F/meetings/voting/000912](requirements/functional/meetings/voting/000912_election-members-majority.md) | An election for one seat can need the majority of the members | approved |
| [F/meetings/voting/000914](requirements/functional/meetings/voting/000914_circular-vote.md) | A Gremium can decide by Umlaufverfahren | approved |
| [F/meetings/voting/000915](requirements/functional/meetings/voting/000915_circular-objection.md) | An objection ends an Umlaufverfahren | approved |
| [F/meetings/voting/000932](requirements/functional/meetings/voting/000932_one-cast-for-all-ballots.md) | One cast counts for the own ballot and all represented ballots | approved |
| [F/meetings/voting/000933](requirements/functional/meetings/voting/000933_turnout-counts-persons.md) | The turnout of a running vote counts persons | approved |
| [F/meetings/voting/000935](requirements/functional/meetings/voting/000935_quorum-not-per-vote.md) | A vote takes its quorum from the Gremium | approved |
| [F/meetings/voting/000936](requirements/functional/meetings/voting/000936_cancelled-circular-in-list.md) | The vote list shows a circular vote that an objection ended | approved |
| [F/meetings/voting/000939](requirements/functional/meetings/voting/000939_member-count-at-open.md) | A vote without a meeting counts the members at its open | approved |
| [F/meetings/voting/000944](requirements/functional/meetings/voting/000944_circular-mails.md) | A circular vote sends a mail at its open and before its end | approved |
| [F/meetings/voting/000947](requirements/functional/meetings/voting/000947_objection-button.md) | The objection to a circular vote is a button | approved |
| [F/meetings/voting/000949](requirements/functional/meetings/voting/000949_circular-in-decisions-only.md) | A circular decision shows in the list of decisions and in no protocol | approved |
| [F/meetings/voting/000971](requirements/functional/meetings/voting/000971_election-three-rounds.md) | An election by the majority of the members has up to three Wahlgänge | approved |
| [F/meetings/voting/000993](requirements/functional/meetings/voting/000993_repeat-vote-way-back.md) | A repeated application vote moves the application in one step and has a way back | approved |
| [F/meetings/voting/000994](requirements/functional/meetings/voting/000994_one-open-vote.md) | A meeting has one open vote at a time | approved |
| [F/meetings/voting/000995](requirements/functional/meetings/voting/000995_cancelled-vote-frees-item.md) | A cancelled vote does not block the vote of an application item | approved |
| [F/meetings/voting/000996](requirements/functional/meetings/voting/000996_round-and-repeat-lock.md) | The next Wahlgang and the repeat of an election lock each other | approved |
| [F/public/public-pages/000170](requirements/functional/public/public-pages/000170_no-public-meetings.md) | Meetings are never public | replaced |
| [F/public/public-pages/000171](requirements/functional/public/public-pages/000171_public-protocols.md) | Only final protocols of public Gremien are public | approved |
| [F/public/public-pages/000172](requirements/functional/public/public-pages/000172_public-protocol-content.md) | A public protocol has no names and no non-public TOPs | approved |
| [F/public/public-pages/000173](requirements/functional/public/public-pages/000173_noindex.md) | Public pages are not indexed | approved |
| [F/public/public-pages/000589](requirements/functional/public/public-pages/000589_login-choice.md) | Anmelden offers the account login and the e-mail link | approved |
| [F/public/public-pages/000687](requirements/functional/public/public-pages/000687_blackout-public.md) | The public variants black out a marked segment | approved |
| [F/public/public-pages/000887](requirements/functional/public/public-pages/000887_blackout-bar-baseline.md) | A black bar in the PDF sits on the baseline of its line | approved |
| [F/public/public-pages/000926](requirements/functional/public/public-pages/000926_public-decisions.md) | The decisions of a public Gremium are public | approved |
| [F/public/public-pages/000945](requirements/functional/public/public-pages/000945_public-decisions-last-result.md) | The public decisions show the last result of a TOP | approved |
| [F/public/public-pages/000967](requirements/functional/public/public-pages/000967_blackout-block-public.md) | The public variants show a blackout block as one bar | approved |
| [F/public/public-pages/001303](requirements/functional/public/public-pages/001303_public-pages-in-navigation.md) | The navigation leads a signed-in person to the public pages | approved |
| [F/public/public-pages/002400](requirements/functional/public/public-pages/002400_protocols-per-gremium.md) | The public protocols have one page per Gremium | approved |
| [F/public/public-pages/002401](requirements/functional/public/public-pages/002401_decisions-per-gremium.md) | The public decisions have one page per Gremium | approved |
| [F/public/public-pages/002402](requirements/functional/public/public-pages/002402_gremium-pages-link-each-other.md) | The two public pages of a Gremium link each other | approved |
| [F/public/public-pages/002403](requirements/functional/public/public-pages/002403_unknown-gremium-page.md) | An unknown Gremium page shows that it has no protocols | approved |
| [F/public/public-pages/002404](requirements/functional/public/public-pages/002404_committee-query-redirect.md) | An old Gremium filter link opens the page of the Gremium | approved |
| [NF/accessibility/documents/000524](requirements/non-functional/accessibility/documents/000524_protocol-pdf-ua.md) | The protocol PDF is tagged as PDF/UA-1 | approved |
| [NF/accessibility/documents/000525](requirements/non-functional/accessibility/documents/000525_mail-plain-text.md) | Each mail has a plain text part | approved |
| [NF/accessibility/interaction/000521](requirements/non-functional/accessibility/interaction/000521_no-cognitive-test.md) | The login and the captcha need no cognitive test | approved |
| [NF/accessibility/interaction/002783](requirements/non-functional/accessibility/interaction/002783_selection-bar-keyboard.md) | The format bar works with the keyboard | approved |
| [NF/accessibility/language/000216](requirements/non-functional/accessibility/language/000216_i18n-parity.md) | German and English texts are complete | replaced |
| [NF/accessibility/perception/000501](requirements/non-functional/accessibility/perception/000501_accent-contrast.md) | An admin accent colour keeps the contrast | approved |
| [NF/accessibility/statement/000495](requirements/non-functional/accessibility/statement/000495_statement-page.md) | A public page holds the accessibility statement | approved |
| [NF/accessibility/statement/000496](requirements/non-functional/accessibility/statement/000496_statement-link.md) | Every page links to the accessibility statement | approved |
| [NF/accessibility/statement/000497](requirements/non-functional/accessibility/statement/000497_barrier-report.md) | A user can report a barrier as a ticket | approved |
| [NF/compatibility/deploy/000394](requirements/non-functional/compatibility/deploy/000394_migrate-first.md) | A deploy runs the migration first | approved |
| [NF/compatibility/deploy/000435](requirements/non-functional/compatibility/deploy/000435_caddy-edge.md) | Caddy is the edge proxy | approved |
| [NF/compatibility/deploy/000627](requirements/non-functional/compatibility/deploy/000627_deploy-reports-schema-drift.md) | A deploy reports a schema that differs from the models | approved |
| [NF/compatibility/deploy/000975](requirements/non-functional/compatibility/deploy/000975_worker-watchdog.md) | A worker that hangs ends its process | approved |
| [NF/compatibility/deploy/000978](requirements/non-functional/compatibility/deploy/000978_build-downloads.md) | An image build fetches no signing key and repeats a download | approved |
| [NF/compatibility/deploy/000981](requirements/non-functional/compatibility/deploy/000981_pinned-digests.md) | Images and CI actions are pinned by digest | approved |
| [NF/compatibility/links/000592](requirements/non-functional/compatibility/links/000592_old-german-urls.md) | An old German URL redirects to its English URL | approved |
| [NF/compatibility/pwa/002150](requirements/non-functional/compatibility/pwa/002150_app-version-header.md) | Every answer of the server carries the app version | approved |
| [NF/compatibility/pwa/002340](requirements/non-functional/compatibility/pwa/002340_reload-loads-page-from-network.md) | The reload to a new app version loads the page from the network | approved |
| [NF/compatibility/pwa/002341](requirements/non-functional/compatibility/pwa/002341_version-check-on-return.md) | The app checks the version when the page comes back | approved |
| [NF/performance/loading/000190](requirements/non-functional/performance/loading/000190_batch-reads.md) | A list reads its rows in one request | approved |
| [NF/performance/loading/000847](requirements/non-functional/performance/loading/000847_read-after-write-is-fresh.md) | A read after a write does not stand on a read from before it | approved |
| [NF/performance/loading/001280](requirements/non-functional/performance/loading/001280_skeleton-until-logos.md) | The Gremien list shows its skeleton until the logos have loaded | approved |
| [NF/performance/loading/002000](requirements/non-functional/performance/loading/002000_read-ahead-on-intent.md) | A list reads the details of a row ahead only on a sign of intent | approved |
| [NF/performance/loading/002001](requirements/non-functional/performance/loading/002001_navigation-marks-one-read.md) | The marks of the navigation come in one read, not on every page change | approved |
| [NF/performance/loading/002003](requirements/non-functional/performance/loading/002003_lazy-editor-and-texts.md) | The Markdown editor and the DE texts load in chunks of their own | approved |
| [NF/performance/loading/002004](requirements/non-functional/performance/loading/002004_api-workers.md) | The API serves requests in four processes | approved |
| [NF/performance/rendering/002002](requirements/non-functional/performance/rendering/002002_zoneless.md) | The app runs its change detection without zone.js | approved |
| [NF/performance/rendering/002160](requirements/non-functional/performance/rendering/002160_scroll-without-check.md) | A scroll event runs no change detection | approved |
| [NF/performance/rendering/002161](requirements/non-functional/performance/rendering/002161_reads-before-writes.md) | Layout reads wait for the render and come before the writes of a frame | approved |
| [NF/performance/rendering/002406](requirements/non-functional/performance/rendering/002406_no-root-has-on-scroll.md) | No :has() at the page root | approved |
| [NF/performance/rendering/002407](requirements/non-functional/performance/rendering/002407_fab-fold-without-layout.md) | The FAB fold runs between two measured sizes and ends in the folded layout | approved |
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
| [NF/security/access/000304](requirements/non-functional/security/access/000304_no-token-backup.md) | No agent token reaches a backup | replaced |
| [NF/security/access/000350](requirements/non-functional/security/access/000350_socket-origin.md) | A meeting socket checks the origin | approved |
| [NF/security/access/000352](requirements/non-functional/security/access/000352_guest-device.md) | A guest joins with one device | approved |
| [NF/security/access/000453](requirements/non-functional/security/access/000453_csrf-token.md) | Cookie writes need the CSRF token | approved |
| [NF/security/access/000460](requirements/non-functional/security/access/000460_default-write-limit.md) | Writes have a default rate limit | approved |
| [NF/security/access/000463](requirements/non-functional/security/access/000463_scope-caps-gremium-rights.md) | A scope caps every gremium right of a token | approved |
| [NF/security/access/000470](requirements/non-functional/security/access/000470_audit-read-global.md) | The audit read is global | approved |
| [NF/security/access/000472](requirements/non-functional/security/access/000472_public-application-post.md) | The public Antrag POST is protected | replaced |
| [NF/security/access/000590](requirements/non-functional/security/access/000590_email-session-live-check.md) | An e-mail session reads its Anträge at each request | approved |
| [NF/security/access/000976](requirements/non-functional/security/access/000976_pdf-render-limit.md) | A PDF made on request has a rate limit | approved |
| [NF/security/access/000977](requirements/non-functional/security/access/000977_observer-add-limit.md) | Adding observers has a rate limit | approved |
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
| [NF/security/files/000869](requirements/non-functional/security/files/000869_pdf-upload.md) | An embedded PDF is checked on upload | approved |
| [NF/security/files/000979](requirements/non-functional/security/files/000979_embedded-pdf-read-right.md) | An embedded PDF needs the read right of its Sitzung | approved |
| [NF/security/files/001083](requirements/non-functional/security/files/001083_framable-pdf-preview.md) | A file that the viewer shows has a sandboxed inline preview | approved |
| [NF/security/integrity/000183](requirements/non-functional/security/integrity/000183_audit-chain.md) | The audit log is append-only | approved |
| [NF/security/integrity/000184](requirements/non-functional/security/integrity/000184_sandboxed-mail.md) | Mail templates run sandboxed | approved |
| [NF/security/integrity/000295](requirements/non-functional/security/integrity/000295_canonical-hash.md) | The hash input is canonical | approved |
| [NF/security/integrity/000296](requirements/non-functional/security/integrity/000296_secret-hidden.md) | A webhook secret is never shown | approved |
| [NF/security/integrity/000297](requirements/non-functional/security/integrity/000297_signature.md) | A webhook request is signed with a timestamp | approved |
| [NF/security/integrity/000393](requirements/non-functional/security/integrity/000393_db-roles.md) | Database roles are separated | approved |
| [NF/security/integrity/002810](requirements/non-functional/security/integrity/002810_secrets-sealed.md) | A secret of an integration is sealed in the database | approved |
| [NF/security/integrity/002811](requirements/non-functional/security/integrity/002811_secrets-key.md) | The key of the sealed secrets comes from the deploy | approved |
| [NF/security/network/000182](requirements/non-functional/security/network/000182_webhook-ssrf.md) | The webhook SSRF guard runs at send time | approved |
| [NF/security/network/000335](requirements/non-functional/security/network/000335_avatar-fetch.md) | The avatar fetch is fixed and limited | approved |
| [NF/security/network/000389](requirements/non-functional/security/network/000389_typst-isolated.md) | The render service has no network egress | approved |
| [NF/security/network/000391](requirements/non-functional/security/network/000391_host-ports.md) | Only two ports are bound on the host | approved |
| [NF/security/network/000392](requirements/non-functional/security/network/000392_forwarded-ips.md) | Forwarded headers come only from the proxy | approved |
| [NF/security/network/000454](requirements/non-functional/security/network/000454_api-security-headers.md) | The API sends strict security headers and no CORS | approved |
| [NF/security/network/000466](requirements/non-functional/security/network/000466_webhook-host-allowlist.md) | Webhook targets can be limited to a host list | approved |
| [NF/security/network/002514](requirements/non-functional/security/network/002514_paperless-host-allowlist.md) | The Paperless address needs a host from the deploy settings | approved |
| [NF/security/network/002515](requirements/non-functional/security/network/002515_paperless-token-secret.md) | The Paperless token never leaves the server | approved |
| [NF/security/network/002744](requirements/non-functional/security/network/002744_ticket-mail-host-allowlist.md) | The hosts of a Postfach need the deploy settings | approved |
| [NF/security/network/002745](requirements/non-functional/security/network/002745_ticket-mail-tls.md) | The platform talks to a mail server only through TLS | approved |
| [NF/security/network/002746](requirements/non-functional/security/network/002746_ticket-mail-password.md) | No read returns the password of a Postfach | approved |
| [NF/security/network/002817](requirements/non-functional/security/network/002817_push-token-not-logged.md) | An access log holds no token of a path | approved |
| [NF/usability/controls/000668](requirements/non-functional/usability/controls/000668_fiscal-year-chip.md) | The fiscal year is chosen with a chip | approved |
| [NF/usability/controls/000676](requirements/non-functional/usability/controls/000676_tickets-word-in-admin.md) | Verwaltung says "Tickets" | approved |
| [NF/usability/controls/000931](requirements/non-functional/usability/controls/000931_back-closes-budget-dialogs.md) | The dialogs of the Haushalt close on Back | approved |
| [NF/usability/controls/002163](requirements/non-functional/usability/controls/002163_bar-pill-at-press.md) | The pill of the navigation bar moves at the press | approved |
| [NF/usability/controls/002164](requirements/non-functional/usability/controls/002164_ripple-in-surface.md) | The ripple is the ripple of Angular Material inside the pressed surface | approved |
| [NF/usability/controls/002570](requirements/non-functional/usability/controls/002570_one-icon-look-in-a-group.md) | Every icon of a button group has one size and one colour | approved |
| [NF/usability/controls/002581](requirements/non-functional/usability/controls/002581_select-in-form-fills-row.md) | A multiple choice in a form fills its row and names its values | approved |
| [NF/usability/controls/002582](requirements/non-functional/usability/controls/002582_webhook-needs-name.md) | The webhook dialog saves only with a name and a valid URL | approved |
| [NF/usability/layout/000199](requirements/non-functional/usability/layout/000199_footer.md) | The footer shows only on start and public pages | approved |
| [NF/usability/layout/000530](requirements/non-functional/usability/layout/000530_phone-start-search-pinned.md) | The search bar of the start page stays at the top on the phone | replaced |
| [NF/usability/layout/000624](requirements/non-functional/usability/layout/000624_start-work-list-sticky-head.md) | The work list on Start keeps its column header and cuts at the window edge | replaced |
| [NF/usability/layout/001313](requirements/non-functional/usability/layout/001313_attendance-pool-row-group.md) | The pool substitutes are an own row group | approved |
| [NF/usability/layout/001480](requirements/non-functional/usability/layout/001480_admin-list-detail.md) | Verwaltung and Konto are ordinary list/detail pages | approved |
| [NF/usability/layout/001482](requirements/non-functional/usability/layout/001482_admin-editors-full-width.md) | The form editor and the flow editor open without the list | approved |
| [NF/usability/layout/002162](requirements/non-functional/usability/layout/002162_section-switch-at-once.md) | A switch between sections shows the new section at once | approved |
| [NF/usability/layout/002590](requirements/non-functional/usability/layout/002590_role-matrix-one-line-per-role.md) | Each role of the role matrix is one line | approved |
| [NF/usability/layout/002610](requirements/non-functional/usability/layout/002610_settings-no-change-date.md) | A settings screen of Verwaltung shows no change date | approved |
| [NF/usability/layout/002690](requirements/non-functional/usability/layout/002690_admin-lists-like-users.md) | Every list page of Verwaltung looks like Benutzer | approved |
| [NF/usability/layout/002800](requirements/non-functional/usability/layout/002800_phone-dock-sheets-full-screen.md) | A sheet from the phone dock of a meeting opens over the whole screen | approved |
| [NF/usability/layout/002902](requirements/non-functional/usability/layout/002902_delegation-search-pinned.md) | The delegation dialogs pin the search | approved |
| [NF/usability/layout/002903](requirements/non-functional/usability/layout/002903_delegation-pick-rows.md) | The delegation dialogs use the pick rows | approved |
| [NF/usability/layout/002904](requirements/non-functional/usability/layout/002904_delegation-vote-line.md) | The delegation dialog says that the vote moves | removed |
| [P/integrations/webhooks/000963](protocols/integrations/webhooks/000963_webhook-delivery.md) | A webhook delivery is a signed JSON POST | approved |
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
| [S/backend/python/000473](style/backend/python/000473_no-role-check.md) | A permission check never reads principal.roles | replaced |
| [S/backend/python/000474](style/backend/python/000474_services-do-not-commit.md) | Service functions do not commit | approved |
| [S/backend/python/000640](style/backend/python/000640_service-commit-ratchet.md) | A CI ratchet lowers the commits in services | approved |
| [S/backend/python/000643](style/backend/python/000643_module-layers.md) | A backend module imports only from its layer and from lower layers | approved |
| [S/backend/python/000644](style/backend/python/000644_shared-imports-no-module.md) | The shared code imports no module | approved |
| [S/backend/python/000645](style/backend/python/000645_model-in-subject-module.md) | A model is in the module of its subject | approved |
| [S/backend/python/000646](style/backend/python/000646_import-exception-ratchet.md) | A CI ratchet lowers the accepted import violations | replaced |
| [S/backend/python/000648](style/backend/python/000648_notifications-mail-engine-only.md) | The module notifications holds the mail engine only | approved |
| [S/backend/python/000649](style/backend/python/000649_auth-audit-no-upward-import.md) | The modules auth and audit import no higher module | approved |
| [S/backend/python/000651](style/backend/python/000651_no-import-exception.md) | The import contract has no exception | approved |
| [S/backend/python/000652](style/backend/python/000652_meeting-core-module.md) | The meeting core is in the module meetings | approved |
| [S/backend/python/002818](style/backend/python/002818_one-host-allowlist.md) | A host allowlist has one check | approved |
| [S/frontend/angular/000073](style/frontend/angular/000073_i18n-parity.md) | Every UI text is in both catalogs | approved |
| [S/frontend/angular/000074](style/frontend/angular/000074_production-build.md) | Run the production build after style changes | approved |
| [S/frontend/angular/000075](style/frontend/angular/000075_narrow-with-as.md) | A template narrows a signal with as | approved |
| [S/frontend/angular/000076](style/frontend/angular/000076_tailwind-borders.md) | A Tailwind border has a style | approved |
| [S/frontend/angular/000078](style/frontend/angular/000078_after-next-render.md) | Wait for a render with afterNextRender | approved |
| [S/frontend/angular/000079](style/frontend/angular/000079_ui-kit-parts.md) | Shared UI parts live in the ui-kit | approved |
| [S/frontend/angular/000080](style/frontend/angular/000080_standalone-components.md) | Components are standalone with own files | approved |
| [S/frontend/angular/000396](style/frontend/angular/000396_route-guards.md) | A route guard is only for the UX | approved |
| [S/frontend/angular/000397](style/frontend/angular/000397_gremium-checks.md) | Gremium rights come from the Gremium API | approved |
| [S/frontend/angular/000398](style/frontend/angular/000398_mock-dev-only.md) | The mock API runs only in dev builds | approved |
| [S/frontend/angular/000526](style/frontend/angular/000526_use-shared-parts.md) | A view uses the shared components | approved |
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
| [S/shared/api/000843](style/shared/api/000843_unstorable-text.md) | A text that the database cannot store answers 422 | approved |
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
| [S/shared/testing/000044](style/shared/testing/000044_test-first.md) | A change comes with its tests | approved |
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
| [S/shared/testing/001240](style/shared/testing/001240_changed-parts.md) | CI runs only the jobs of the changed parts | approved |
| [S/shared/testing/001241](style/shared/testing/001241_green-base.md) | The base of a change is the newest green CI run before it | approved |
| [S/shared/testing/001242](style/shared/testing/001242_full-runs.md) | Main, a manual run and a change of the CI run every job | approved |
| [S/shared/testing/001243](style/shared/testing/001243_part-table.md) | A part also runs for a change of a file that it reads | approved |
| [S/shared/testing/001244](style/shared/testing/001244_gate-job.md) | One gate job sums up the CI run | approved |
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
| [S/specs/protocols/000957](style/specs/protocols/000957_whole-format.md) | A protocol spec describes one whole format | approved |
| [S/specs/protocols/000958](style/specs/protocols/000958_schema-file.md) | A JSON format has a JSON Schema file beside its spec | approved |
| [S/specs/protocols/000959](style/specs/protocols/000959_checked-example.md) | The example of a JSON format matches its schema | approved |
| [S/specs/protocols/000960](style/specs/protocols/000960_breaking-change.md) | A breaking change of a format is a new protocol spec | approved |
| [S/specs/protocols/000961](style/specs/protocols/000961_code-against-schema.md) | A test checks the output of the code against the schema | approved |
| [S/specs/protocols/000962](style/specs/protocols/000962_protocols-key.md) | A rule names the formats that it uses | approved |
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
