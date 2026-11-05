# Specs

The binding rules of STUPA-Workflow. One file holds one rule. The rules for specs are in
[style/specs/](style/specs/). Copy [TEMPLATE.md](TEMPLATE.md) to start a new rule.

## Tree

```
specs/
  style/
    specs/        format, structure, content
    shared/       writing, api, testing, git, functional
    backend/      python, database, functional
    frontend/     angular, functional
  requirements/
    functional/
      meetings/        meetings, voting, delegations, protocols
      applications/    applications, forms
      finance/         budget
      collaboration/   todos, tickets, notifications
      administration/  accounts, admin, files
      public/          public-pages
      integrations/    mcp, external
    non-functional/
      security/        access, files, network, integrity
      privacy/         personal-data
      performance/     loading
      usability/       layout, controls
      accessibility/   language, interaction
      compatibility/   pwa
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
| [F/administration/admin/000161](requirements/functional/administration/admin/000161_crud-complete.md) | Every entity has create, read, update and delete | draft |
| [F/administration/admin/000162](requirements/functional/administration/admin/000162_cd-variant-delete.md) | A CD variant in use is not deleted | draft |
| [F/administration/admin/000163](requirements/functional/administration/admin/000163_audit-revert.md) | The audit revert reverses effects, never entries | draft |
| [F/administration/admin/000164](requirements/functional/administration/admin/000164_translations.md) | Admins edit UI texts and add languages | draft |
| [F/administration/admin/000165](requirements/functional/administration/admin/000165_admin-start.md) | Verwaltung starts with an empty state | draft |
| [F/administration/admin/000166](requirements/functional/administration/admin/000166_dsgvo-delete.md) | A privacy erasure starts from Benutzer | draft |
| [F/administration/files/000167](requirements/functional/administration/files/000167_ascii-names.md) | File names replace non-ASCII characters | draft |
| [F/administration/files/000168](requirements/functional/administration/files/000168_confirm-delete.md) | Every attachment delete is confirmed | draft |
| [F/administration/files/000169](requirements/functional/administration/files/000169_drop-files.md) | Attachments can be dropped | draft |
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
| [F/applications/forms/000133](requirements/functional/applications/forms/000133_positions-shape.md) | A positions answer has label and offers | draft |
| [F/applications/forms/000134](requirements/functional/applications/forms/000134_offer-limits.md) | Offer counts have limits | draft |
| [F/applications/forms/000135](requirements/functional/applications/forms/000135_funding-field.md) | The requested funding is separate from the costs | draft |
| [F/applications/forms/000136](requirements/functional/applications/forms/000136_all-languages-editable.md) | Every i18n text is editable in English too | draft |
| [F/applications/forms/000137](requirements/functional/applications/forms/000137_flow-auto-layout.md) | The flow editor lays out automatically | draft |
| [F/collaboration/notifications/000151](requirements/functional/collaboration/notifications/000151_task-mail-recipients.md) | Task mails go only to who can act | draft |
| [F/collaboration/notifications/000152](requirements/functional/collaboration/notifications/000152_team-mails-opt-in.md) | Team mails about Anträge are off by default | draft |
| [F/collaboration/notifications/000153](requirements/functional/collaboration/notifications/000153_sandboxed-templates.md) | Mail templates are sandboxed | draft |
| [F/collaboration/tickets/000150](requirements/functional/collaboration/tickets/000150_one-way-report.md) | A help ticket is a one-way report | draft |
| [F/collaboration/todos/000147](requirements/functional/collaboration/todos/000147_board-kinds.md) | Boards per Gremium, per person and per team | draft |
| [F/collaboration/todos/000148](requirements/functional/collaboration/todos/000148_move-sheet.md) | One move sheet | draft |
| [F/collaboration/todos/000149](requirements/functional/collaboration/todos/000149_no-status-sync.md) | No status sync between ticket and card | draft |
| [F/finance/budget/000138](requirements/functional/finance/budget/000138_cost-centre-picker.md) | One cost centre picker | draft |
| [F/finance/budget/000139](requirements/functional/finance/budget/000139_close-fiscal-year.md) | A fiscal year closes and reopens | draft |
| [F/finance/budget/000140](requirements/functional/finance/budget/000140_default-fiscal-year.md) | The default fiscal year holds today | draft |
| [F/finance/budget/000141](requirements/functional/finance/budget/000141_fiscal-year-delete.md) | A fiscal year in use is not deleted | draft |
| [F/finance/budget/000142](requirements/functional/finance/budget/000142_duplicate-booking.md) | A booking can be duplicated | draft |
| [F/finance/budget/000143](requirements/functional/finance/budget/000143_transfer-kind.md) | A transfer is a kind in the Art filter | draft |
| [F/finance/budget/000144](requirements/functional/finance/budget/000144_cost-centre-items.md) | The cost centre card lists Anträge and bookings | draft |
| [F/finance/budget/000145](requirements/functional/finance/budget/000145_revert-keeps-invoice.md) | A reverted booking keeps the invoice status | draft |
| [F/finance/budget/000146](requirements/functional/finance/budget/000146_legend.md) | The budget legend matches the drawing | draft |
| [F/integrations/external/000176](requirements/functional/integrations/external/000176_optional.md) | Integrations are optional | draft |
| [F/integrations/external/000177](requirements/functional/integrations/external/000177_preview-access.md) | A link preview uses the access of the viewer | draft |
| [F/integrations/mcp/000174](requirements/functional/integrations/mcp/000174_acts-as-user.md) | The MCP server acts as the logged-in user | draft |
| [F/integrations/mcp/000175](requirements/functional/integrations/mcp/000175_prod-data.md) | Production data changes only on request | draft |
| [F/meetings/delegations/000110](requirements/functional/meetings/delegations/000110_per-gremium.md) | Vote delegation is a Gremium setting | draft |
| [F/meetings/delegations/000111](requirements/functional/meetings/delegations/000111_delegation-blocks-presence.md) | A member with an active delegation is not present | draft |
| [F/meetings/delegations/000112](requirements/functional/meetings/delegations/000112_one-pool.md) | The substitute pool is the only substitute rule | draft |
| [F/meetings/delegations/000113](requirements/functional/meetings/delegations/000113_pool-seats.md) | A pool substitute takes a free seat | draft |
| [F/meetings/delegations/000114](requirements/functional/meetings/delegations/000114_pool-read-scope.md) | Pool substitutes read like members | draft |
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
| [F/meetings/protocols/000115](requirements/functional/meetings/protocols/000115_keeper-permission.md) | The keeper holds protocol.write | draft |
| [F/meetings/protocols/000116](requirements/functional/meetings/protocols/000116_finalize.md) | Finalize needs a closed meeting and protocol.finalize | draft |
| [F/meetings/protocols/000117](requirements/functional/meetings/protocols/000117_delete-draft-only.md) | Only a draft protocol is deleted | draft |
| [F/meetings/protocols/000118](requirements/functional/meetings/protocols/000118_pdf-name.md) | The PDF is named after the meeting | draft |
| [F/meetings/protocols/000119](requirements/functional/meetings/protocols/000119_signatures-one-page.md) | The signature block stays on one page | draft |
| [F/meetings/protocols/000120](requirements/functional/meetings/protocols/000120_election-ranking.md) | An election shows a ranking | draft |
| [F/meetings/voting/000024](requirements/functional/meetings/voting/000024_every-vote-is-secret.md) | Every vote is secret | draft |
| [F/meetings/voting/000025](requirements/functional/meetings/voting/000025_ballot-does-not-change.md) | A cast ballot does not change | draft |
| [F/meetings/voting/000026](requirements/functional/meetings/voting/000026_tie-rejects-motion.md) | A tie rejects a motion | draft |
| [F/meetings/voting/000027](requirements/functional/meetings/voting/000027_election-tie-by-lot.md) | A tie in an election is decided by lot | draft |
| [F/meetings/voting/000028](requirements/functional/meetings/voting/000028_protokollant-opens-and-closes.md) | Only the protokollant opens and closes a meeting vote | draft |
| [F/meetings/voting/000029](requirements/functional/meetings/voting/000029_delete-only-draft-or-cancelled.md) | A vote can be deleted only as draft or cancelled | draft |
| [F/meetings/voting/000030](requirements/functional/meetings/voting/000030_vote-in-gremium-of-antrag.md) | A vote on an Antrag belongs to the Gremium of the Antrag | draft |
| [F/meetings/voting/000031](requirements/functional/meetings/voting/000031_poll-shows-only-counts.md) | A poll shows only counts | draft |
| [F/public/public-pages/000170](requirements/functional/public/public-pages/000170_no-public-meetings.md) | Meetings are never public | draft |
| [F/public/public-pages/000171](requirements/functional/public/public-pages/000171_public-protocols.md) | Only final protocols of public Gremien are public | draft |
| [F/public/public-pages/000172](requirements/functional/public/public-pages/000172_public-protocol-content.md) | A public protocol has no names and no internal TOPs | draft |
| [F/public/public-pages/000173](requirements/functional/public/public-pages/000173_noindex.md) | Public pages are not indexed | draft |
| [NF/accessibility/interaction/000217](requirements/non-functional/accessibility/interaction/000217_keyboard-and-labels.md) | Controls are reachable by keyboard and named | draft |
| [NF/accessibility/interaction/000218](requirements/non-functional/accessibility/interaction/000218_themes.md) | Light and dark themes are both supported | draft |
| [NF/accessibility/interaction/000219](requirements/non-functional/accessibility/interaction/000219_reduced-motion.md) | Motion follows the reduced motion setting | draft |
| [NF/accessibility/language/000216](requirements/non-functional/accessibility/language/000216_i18n-parity.md) | German and English texts are complete | draft |
| [NF/compatibility/pwa/000220](requirements/non-functional/compatibility/pwa/000220_zoom.md) | Zoom is blocked only in the installed app | draft |
| [NF/compatibility/pwa/000221](requirements/non-functional/compatibility/pwa/000221_android-nav-bar.md) | The Android navigation bar has the manifest colour | draft |
| [NF/compatibility/pwa/000222](requirements/non-functional/compatibility/pwa/000222_update-offline.md) | The app shows update and offline bars | draft |
| [NF/performance/loading/000189](requirements/non-functional/performance/loading/000189_load-bar.md) | The load bar shows only for slow foreground reads | draft |
| [NF/performance/loading/000190](requirements/non-functional/performance/loading/000190_batch-reads.md) | A list reads its rows in one request | draft |
| [NF/performance/loading/000191](requirements/non-functional/performance/loading/000191_search-as-you-type.md) | Search runs as you type | draft |
| [NF/privacy/personal-data/000185](requirements/non-functional/privacy/personal-data/000185_no-raw-ids.md) | The UI shows no raw IDs | draft |
| [NF/privacy/personal-data/000186](requirements/non-functional/privacy/personal-data/000186_no-plain-ip.md) | The login audit has no plain IP address | draft |
| [NF/privacy/personal-data/000187](requirements/non-functional/privacy/personal-data/000187_guest-pseudonyms.md) | Guests get pseudonyms | draft |
| [NF/privacy/personal-data/000188](requirements/non-functional/privacy/personal-data/000188_anonymize.md) | Personal data can be anonymized | draft |
| [NF/security/access/000179](requirements/non-functional/security/access/000179_public-allowlist.md) | A public route is on the allowlist | draft |
| [NF/security/access/000180](requirements/non-functional/security/access/000180_public-abuse-guard.md) | Public input is protected against abuse | draft |
| [NF/security/files/000178](requirements/non-functional/security/files/000178_stream-downloads.md) | Downloads stream through the API | draft |
| [NF/security/files/000181](requirements/non-functional/security/files/000181_scan-uploads.md) | Uploaded files are scanned | draft |
| [NF/security/integrity/000183](requirements/non-functional/security/integrity/000183_audit-chain.md) | The audit log is append-only | draft |
| [NF/security/integrity/000184](requirements/non-functional/security/integrity/000184_sandboxed-mail.md) | Mail templates run sandboxed | draft |
| [NF/security/network/000182](requirements/non-functional/security/network/000182_webhook-ssrf.md) | Webhooks cannot reach internal addresses | draft |
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
| [S/frontend/angular/000077](style/frontend/angular/000077_load-bar.md) | Only foreground reads show the load bar | draft |
| [S/frontend/angular/000078](style/frontend/angular/000078_after-next-render.md) | Wait for a render with afterNextRender | draft |
| [S/frontend/angular/000079](style/frontend/angular/000079_ui-kit-parts.md) | Shared UI parts live in the ui-kit | draft |
| [S/frontend/angular/000080](style/frontend/angular/000080_standalone-components.md) | Components are standalone with own files | draft |
| [S/frontend/functional/000091](style/frontend/functional/000091_signal-update.md) | A signal update returns a new value | draft |
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
| [S/shared/testing/000044](style/shared/testing/000044_test-first.md) | Tests come first | draft |
| [S/shared/testing/000045](style/shared/testing/000045_coverage-gates.md) | Coverage gates hold | draft |
| [S/shared/testing/000046](style/shared/testing/000046_critical-modules.md) | Critical modules have full branch coverage | draft |
| [S/shared/testing/000047](style/shared/testing/000047_own-test-keys.md) | An integration test uses its own keys | draft |
| [S/shared/testing/000048](style/shared/testing/000048_run-integration.md) | A plain pytest skips integration tests | draft |
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
