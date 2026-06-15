# TASKS — PII legal compliance + non-public agenda TOPs

Branch: feat/PII-Re-Add. Plan: ~/.claude/plans/hashed-sauteeing-prism.md
Status: ☐ todo  ◐ in-progress  ☑ done

## Stream A — PII Tier-1 legal (DSGVO Art. 15/17/5(1)(e))
- ☑ A1 Migration 0030_pii_compliance (+ORM cols); up/down round-trip verified
- ☑ A2 is_pii flag: forms model/schema/normalize + form-editor checkbox (FE ◐fork); PDF redaction
- ☑ A3 ApplicationsService.anonymize (+ _scrub_diff) — null applicant, scrub is_pii data+versions+diff, drop magic_links + attachments (FilesService.delete_for_application)
- ☑ A3 PrincipalService.erase — null PII, active=false, keep sub, drop sessions
- ☑ A3 ErasureRequestService + /admin/privacy queue endpoints + applicant erasure-request endpoint
- ☑ A4 Retention cron worker/retention.py + main.py cron(hour=3,min=30); budget carve-out comment
- ☑ A5 Auskunft: build_auskunft_workbook + /admin/privacy/auskunft + pii_export audit (no raw PII in audit)
- ☑ A6 BE: permissions.privacy.manage; 9 audit actions; notifications events/kinds/templates/recipients(permission)+anonymized filter
- ◐ A6 FE audit filter + DE/EN i18n (fork)
- ◐ A7 FE /admin/privacy page + flow-editor is_terminal + erase button (fork); BE: StateDef.is_terminal round-trip + ApplicationType.retentionMonths done
- ◐ A  Tests: unit re-adds ☑ (76 pass) + anonymize integration ☑; privacy/retention/auskunft integration ◐agent; FE specs ◐fork; coverage pending

## Stream B — non-public agenda TOPs / dual protocol PDF
- ☑ B1 Migration 0031_non_public_tops (+ORM cols)
- ☑ B2 MeetingAgendaItem.non_public model + schema + agenda round-trip; agenda-editor checkbox (FE ◐fork)
- ☑ B3 _assemble_from_agenda(public: bool) placeholder, numbering preserved + _has_non_public
- ☑ B3 finalize dual-render when has_non_public; mail public only; publicPdfUrl + /pdf/public
- ◐ B  Tests: assembly/dual-render/mail (◐agent)

## Open / confirm with DSB
- ☐ Confirm retention months (Finanzordnung) — default 24 is a placeholder
- ☐ Confirm Keycloak user-deletion is done out-of-band on principal erasure (residual sub pseudonymity depends on it)
- ☐ Accepted limitation logged: free-text comments/notes not scrubbed on erasure
