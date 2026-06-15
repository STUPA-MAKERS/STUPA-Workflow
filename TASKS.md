# TASKS — PII legal compliance + non-public agenda TOPs

Branch: feat/PII-Re-Add. Plan: ~/.claude/plans/hashed-sauteeing-prism.md
Status: ☐ todo  ◐ in-progress  ☑ done

## Stream A — PII Tier-1 legal (DSGVO Art. 15/17/5(1)(e))
- ☐ A1 Migrations: re-add applicant.anonymized_at + form_field.is_pii; add application_type.retention_months, state.is_terminal, erasure_request table; settings.default_retention_months=24
- ☐ A2 is_pii flag: forms model/schema/normalize + form-editor checkbox; PDF redaction (pdf/markdown.py skips is_pii)
- ☐ A3 ApplicationsService.anonymize (+ _scrub_diff) — null applicant, scrub is_pii data + versions + diff, drop magic_links + attachments
- ☐ A3 PrincipalService.erase — null email/display_name/calendar_token/oidc_groups, active=false, keep sub, drop sessions
- ☐ A3 ErasureRequestService + /admin/privacy queue endpoints + applicant magic-link request endpoint
- ☐ A4 Retention cron: anonymize past-retention terminal apps; purge expired sessions + used/expired magic_links; NEVER touch budget
- ☐ A5 Auskunft: build_auskunft_workbook (by email, XLSX) + export endpoint + pii_export audit
- ☐ A6 permissions.privacy.manage; 9 audit actions + FE filter + DE/EN i18n; pii_access on raw-PII read; budget carve-out doc/comment
- ☐ A6 Notifications: erasure_requested/executed/rejected events + DE/EN templates + recipients
- ☐ A7 FE /admin/privacy page (queue, principal erase, export, retention settings)
- ☐ A7 FE form-editor is_pii checkbox; flow-editor is_terminal checkbox; magic-link view erase-request button
- ☐ A  Tests (unit + integration) + migration up/down + coverage ≥85%

## Stream B — non-public agenda TOPs / dual protocol PDF
- ☐ B1 Migration: meeting_agenda_item.non_public; protocol.public_pdf_storage_key
- ☐ B2 MeetingAgendaItem.non_public model + schema + agenda-editor checkbox (FE)
- ☐ B3 _assemble_from_agenda(public: bool) placeholder for non_public TOPs (numbering preserved)
- ☐ B3 finalize dual-render when has_non_public: internal→pdf_storage_key, public→public_pdf_storage_key; mail public only
- ☐ B  Tests: public/internal assembly, dual-render trigger, mail attaches public; manual finalize check

## Open / confirm with DSB
- ☐ Confirm retention months (Finanzordnung) — default 24 is a placeholder
- ☐ Confirm Keycloak user-deletion is done out-of-band on principal erasure (residual sub pseudonymity depends on it)
- ☐ Accepted limitation logged: free-text comments/notes not scrubbed on erasure
