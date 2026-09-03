# QA sweep — findings

In-situ sweep of the platform against a local stack that mirrors production, driven
with Playwright as every role.

* Stack: `deploy/docker-compose.yml` + `docker-compose.e2e.yml` + `docker-compose.keycloak.yml`,
  project `antrag-qa`, web on `http://localhost:8080`.
* Code under test: `main` at `09d2c712`.
* Roles: `admin`, `manager`, `finance`, `protocol`, `member`, `nobody`, each with a
  minted session cookie (`deploy/e2e/qa_seed.py`).
* Date: 2026-09-03.

Severity is what the finding costs a user, not how hard it is to fix.

| # | Severity | Area | Summary | State |
| --- | --- | --- | --- | --- |
| 1 | **major** | apply wizard | Review step shows stale data — not what gets submitted | **fixed** |
| 2 | **major** | i18n | Applicant confirmation mail ignores the application language | **fixed** |
| 3 | **major** | i18n | Application type names always render in German | **fixed** |
| 4 | **major** | e2e harness | `deploy/e2e/seed.py` cannot run against current `main` | **fixed** |
| 5 | medium | apply wizard | Review shows raw, unformatted amounts and dates | **fixed** |
| 6 | minor | i18n | 12 hardcoded German strings in the formly field components | **fixed** |
| 7 | minor | apply wizard | Positions summary reads "1 × Position value" | **fixed** |
| 8 | *your call* | apply wizard | Raw UUID shown as the reference number | **fixed** — short prefix chosen |
| 9 | **major** | application detail | Date range renders as raw JSON on the committee's own screen | **fixed** |
| 10 | medium | apply wizard | A signed-in submitter is told to confirm an already-confirmed mail | **fixed** (screen only) |
| 11 | medium | deploy | nginx's CSP double-applies and breaks an external share-page logo | **fixed** |
| 12 | minor | a11y | Nested `<main>` landmark on `/budget` and `/admin/budget-pots` | **fixed** |
| 13 | minor | budget | Empty state blames missing cost centres when a fiscal year is missing | **fixed** |
| 14 | **major** | e2e harness | The Playwright helper posts the wrong field name, so every run 422s | **fixed** |
| 15 | minor | a11y | `app-time-input` renders a duplicate `id` on host and inner input | **fixed** |
| 16 | minor | meetings | Meeting time prints raw `18:00:00`, seconds and all | **fixed** |
| 17 | minor | application detail | Version-diff view still renders dates as raw JSON | **fixed** |
| 18 | *your call* | i18n | English UI uses US date order (`MM/DD/YYYY`) | **fixed** — en-GB chosen |
| 19 | **major** | i18n | Every status-update mail to an applicant ignores their language | **fixed** (applicant-only subset) |
| 20 | *your call* | attachments | Upload hint does not say which file types are allowed | open |
| 21 | minor | application detail | Version-diff row reads "Changedtermin" — badge touches the field name | **fixed** |

---

## 1 — Review step shows stale data, so the user confirms something else than they submit

**Severity:** major. The whole point of a review step is that it shows what will be sent.
**Reproduce:** `/apply` → pick a type → fill the form → **Next** to reach Review → **Back**
→ change any value → **Next**.

Measured:

```
model title in the draft : "GEAENDERTER TITEL XYZ"
review screen shows      : "Kulturfestival Sommer 2026"
```

Any field first filled *after* the initial visit to Review never appears at all. In my
run the draft held `zeitraum`, `termin` and `zielgruppen`, and the review listed none of
them.

**Cause:** `frontend/src/app/features/apply/apply-wizard.component.ts`

```ts
101:  model: Record<string, unknown> = {};                       // plain object
146:  readonly summary = computed<SummaryRow[]>(() => this.buildSummary());
```

`buildSummary()` reads `this.model`. `model` is a plain object that formly mutates in
place, not a signal, so the `computed` never takes a dependency on it. It recomputes only
when `effForm()` or `i18n.locale()` change — neither of which happens on Back/Next.

The submission itself posts `this.model`, so the *correct* data reaches the server. That
makes it worse, not better: the user approves one thing and sends another.

**Fix:** make the model reactive — hold it in a `signal` and write through a setter, or
drop `computed` for a plain method call from the template. A regression test should assert
that editing a value after visiting Review updates the summary.

---

## 2 — The applicant confirmation mail ignores the application language

**Severity:** major. It is the first mail a public applicant gets, and it decides whether
they can confirm at all.
**Reproduce:** switch the UI to EN, submit through `/apply`, read the mail.

The application is stored correctly as English:

```
id=1195a615-… | lang=en
```

The mail is German anyway:

```
Subject: Ihr Zugangslink zur Antragsplattform
Hallo,
über diesen Link gelangen Sie zu Ihrem Antrag: …
```

**Cause:** `backend/app/modules/notifications/service.py:577`

```python
async def send_magic_link(self, *, email: str, link: str) -> None:
    tpl = await self._get_template_by_key(MAGIC_LINK_TEMPLATE_KEY)
    if tpl is not None:
        rendered = self._render(tpl, context={"link": link}, lang=None)
    else:
        rendered = render_mail(..., lang=self.settings.mail_default_lang, ...)
```

The method takes no language at all, so it always renders the default. The seeded
`magic_link` template does carry `de` and `en` variants, so the content exists — only the
selection is missing.

The caller already holds what it needs: `_deliver_magic_link`
(`backend/app/modules/auth/router.py:270`) receives `body.application_id`, and
`application.lang` is right there.

**Fix:** give `send_magic_link` a `lang` argument, resolve it from the application (fall
back to the Gremium default, then `mail_default_lang`), and pass it into `_render`.

---

## 3 — Application type names always render in German

**Severity:** major. It is on the first screen a public applicant sees.
**Reproduce:** set the UI to EN, open `/apply`.

The type picker shows `Förderantrag` although the type carries the English name
`Funding application`. Measured in the browser:

```js
{ uiLang: "en", name: "Förderantrag" }
```

**Cause:** the public list endpoint resolves the i18n map server-side from a `lang`
**query parameter** that defaults to German:

* `backend/app/modules/application_types/schemas.py:36` — `lang: Lang = DEFAULT_LANG`
* `backend/app/modules/application_types/service.py:57` — `name=resolve_i18n(row.name_i18n, lang)`

The frontend never sends it:

* `frontend/src/app/core/api/api-client.service.ts:140` — `applicationTypes()` issues
  `GET /application-types` with no `lang` param.

Every other list call resolves client-side through `this.i18n.locale()`. This one cannot,
because the server already flattened the map to a single string. `Accept-Language` is not
a fallback: the endpoint ignores it and the frontend sends it nowhere.

**Fix:** `params.set('lang', this.i18n.locale())` in `applicationTypes()`. Check every
other endpoint that resolves i18n server-side for the same gap.

**Affects:** `/apply` type picker (`apply-wizard.component.html:26`, `{{ t.name }}`) and
every other consumer of `applicationTypes()`.

---

## 4 — `deploy/e2e/seed.py` cannot seed current `main`

**Severity:** major — the e2e suite cannot run at all.
**Reproduce:** bring up a fresh stack, run `deploy/e2e/seed.py`.

```
seed: kein ApplicationType vorhanden — lief 0018?
```

The seed is stale in four ways:

1. `_default_type` expects migration `0018` to seed the `foerderantrag` application type.
   `0018` is `notification_settings`, and **no migration inserts an `application_type`
   row**. The table is empty on a fresh database.
2. `_ensure_flow` builds `FlowVersion(application_type_id=…)`. The flow became a single
   global graph in `0019_drop_type_flows`; `FlowVersion` has no such column.
3. `_ensure_flow` passes `category=` to `State`. That column no longer exists.
4. It reads `ApplicationType.active_flow_version_id`, which the model no longer carries.

**Why it went unnoticed:** the `e2e` CI job is *skipped* on every recent run, so nothing
exercises this path.

**Fix:** create the application type in the seed, and build the flow as the global graph.
`deploy/e2e/qa_api_seed.py` (added during this sweep) shows a working shape for both.

---

## 5 — Review shows raw, unformatted amounts and dates

**Severity:** medium. Two money values on one screen, written two different ways.
**Reproduce:** fill a `currency` field and a cost position, go to Review.

```
Requested amount   4200
Cost positions     1 × Position value · Total amount: €2,400.00
```

**Cause:** `frontend/src/app/features/apply/apply-wizard.component.ts:370`

```ts
private formatValue(field: FormFieldDef, value: unknown): string {
  if (value === null || value === undefined || value === '') return '';
  if (field.type === 'positions') return this.formatPositions(value);
  if (Array.isArray(value)) return value.map((v) => this.optionLabel(field, v)).join(', ');
  if (typeof value === 'boolean') return this.i18n.translate(value ? 'common.yes' : 'common.no');
  return this.optionLabel(field, value);          // <- String(value)
}
```

There is no branch for `currency`, `date` or `daterange`, so each falls through to
`String(value)`. `formatPositions` right below it *does* use `Intl.NumberFormat`, which is
why the two amounts disagree.

`daterange` is the worst case: its value is `{from, to}`, so `String(value)` yields
**`[object Object]`**. I could not photograph it on screen only because finding 1 kept the
summary stale; the code path is unambiguous.

**Fix:** add branches for `currency` (`Intl.NumberFormat`, same as `formatPositions`),
`date` (locale date) and `daterange` (`from – to`). A unit test per field type would have
caught all three.

---

## 6 — 12 hardcoded German strings in the formly field components

**Severity:** minor on its own, but it breaks the i18n parity rule in `conventions`.
**Reproduce:** set the UI to EN and open any form. Leave a required field empty.

Observed in the English UI: **Ungültige Eingabe**, **Bitte eine Option wählen.**, **Von**,
**Bis**.

All sites are in `frontend/src/app/shared/formly/`:

| File | Line | Literal |
| --- | --- | --- |
| `formly-input.type.ts` | 29, 38, 48 | `'Ungültige Eingabe'` |
| `types/formly-textarea.type.ts` | 33 | `'Ungültige Eingabe'` |
| `types/formly-select.type.ts` | 31 | `'Bitte wählen …'` |
| `types/formly-select.type.ts` | 41 | `'Bitte eine Option wählen.'` |
| `types/formly-checkbox.type.ts` | 33 | `'Bitte bestätigen.'` |
| `types/formly-multicheckbox.type.ts` | 42 | `'Bitte auswählen.'` |
| `types/formly-daterange.type.ts` | 30, 39 | `'Von'`, `'Bis'` |
| `types/formly-daterange.type.ts` | 52 | `'Ungültiger Zeitraum.'` |
| `formly.providers.ts` | 39 | `'Bitte eine gültige E-Mail-Adresse eingeben.'` |

Each is a `??` fallback behind an optional `props` value that no caller sets, so the
fallback is what users always see.

**Fix:** fall back to translation keys, not literals, and add the missing keys in both
locales. Some already exist, e.g. `applications.list.filter.from` / `.to`
(`frontend/src/app/core/i18n/translations.ts:551`). Note the two affected specs assert the
German literal and will need updating with the fix.

---

## 7 — Positions summary reads "1 × Position value"

**Severity:** minor (wording).
**Reproduce:** add a cost position, go to Review.

```
Cost positions   1 × Position value · Total amount: €2,400.00
```

**Cause:** `frontend/src/app/features/apply/apply-wizard.component.ts:396`

```ts
return `${value.length} × ${this.i18n.translate('apply.positions.positionValue')} · …`;
```

`apply.positions.positionValue` is `"Position value"` / `"Positionswert"` — a field
caption, used here as a counted noun. "1 × Position value" is not a sentence.

**Fix:** use a pluralised "N positions" key, or list the position labels (the position in
my run was named `Bühne und Technik`, which the summary never mentions).

---

## 8 — Raw UUID shown as the reference number *(your call)*

**Severity:** you decide — it may be intended.
**Reproduce:** submit through `/apply`.

```
Reference number: 1195a615-3a71-4cfe-9ae0-3ba0c2c4b7e9
```

The project memory `no-uuids-in-ui` says "NEVER show a raw UUID, principal id or `sub`
anywhere in the UI". This is the application's own id rather than an actor id, so it is
not the case that memory describes, and an applicant does need something to quote.

Against it: a 36-character UUID is not something a person can read out on the phone or
copy from a printout, and the same id is already in the mail link.

`application` has no human-readable number column, so a short reference would be a new
feature, not a serializer fix. Flagging it rather than deciding it.

---

## Notes on coverage

* The OIDC **login screen** is not covered. Keycloak runs with a realm and one user per
  role, but the api container cannot reach any host address on this machine (the host
  firewall drops docker-bridge → host), so the only address it resolves for Keycloak is
  `keycloak:8080`, which the host browser cannot resolve. Aligning both needs a
  `/etc/hosts` entry, which needs root. Role coverage is unaffected: sessions are minted
  directly.
* Production config was **not** copied in. The instance was unreachable (502 on
  `/api/health`) at the start of the sweep, and the MCP browser login did not complete
  afterwards. Config here is therefore representative, not identical to production.

---

## 9 — Date range renders as raw JSON on the committee's own screen

**Severity:** major. It is the screen a committee member reads before deciding on money.
**Reproduce:** open any application whose form has a `daterange` or `date` field, at
`/applications/<id>`.

Observed, side by side with correctly formatted currency:

```
Requested amount   €4,200.00        <- correct
Event date         2026-07-01       <- raw ISO
Period             {"to":"2026-07-02","from":"2026-07-01"}   <- raw JSON
```

The **public share page** of the very same application renders both correctly:

```
Event date   01.07.2026
Period       01.07.2026 – 02.07.2026
```

So the read-only view for outsiders is better than the internal review view.

**Cause:** `frontend/src/app/pages/applications/applications-detail.component.ts:576`

`formatByField` branches on `positions`, `checkbox`, `select` / `gremium_select` /
`budget_select`, `multiselect` and `currency` — but not on `date` or `daterange`. Both
fall through to `formatFieldValue`
(`frontend/src/app/pages/applications/applications.util.ts:29`), whose last line is:

```ts
return JSON.stringify(value);
```

A `daterange` value is `{from, to}`, so the user sees the JSON. A `date` value is a
string, so it survives as a raw ISO date.

**Fix:** add `date` and `daterange` branches, matching what the backend share page already
does in `backend/app/modules/applications/share.py` (`%d.%m.%Y`, and `from – to` for a
span). Keep the two views consistent — they render the same data for the same people.

---

## 10 — A signed-in submitter is told to confirm an already-confirmed mail

**Severity:** medium. The instruction is simply false, and it sends a needless mail.
**Reproduce:** sign in, submit an application through `/apply`.

The confirmation screen says:

> Almost done – confirm your email · **Confirmation pending**
> … only then is your application submitted and visible.
> Without confirmation, your application is automatically discarded after 12 hours.

The application is already confirmed at that moment:

```
id=1195a615-… | created_by=qa-admin | confirmed=t
```

**Cause:** two places, neither of which branches on the session.

* `backend/app/modules/applications/service/create.py:94`

  ```python
  email_confirmed_at=None if actor == "applicant" else datetime.now(UTC),
  ```

  A signed-in submitter is auto-confirmed. Correct.

* `backend/app/modules/applications/router.py:188`

  ```python
  background.add_task(send_magic_link, settings, email, app.id, pool)
  ```

  Fires unconditionally, so the signed-in submitter also gets a magic-link mail.

* `frontend/src/app/features/apply/apply-confirmation.component.html` has no
  `@if (loggedIn())` anywhere. It always shows the pending copy.

The wizard itself *does* know: it skips the contact step and Altcha for a signed-in user
(`apply-wizard.component.ts:87,118,141`).

**Fix:** branch the confirmation screen on the session and show a "submitted" state with a
link to the record. Whether the magic-link mail should still go out to a signed-in
submitter is a product call — it doubles as a no-login edit link, so it may be wanted;
the false "pending" copy is the part that is clearly wrong.

---

## 11 — nginx's CSP double-applies and breaks an external share-page logo

**Severity:** medium. It silently defeats a feature that was deliberately built.
**Reproduce:** `curl -D - http://localhost:8080/s/<token>`

The response carries **two** `Content-Security-Policy` headers:

```
content-security-policy: default-src 'none'; style-src 'sha256-…'; img-src 'self'; …   <- the app
Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; …   <- nginx
```

`deploy/web/nginx.conf:52` sets the CSP at **server** level with `always`, so it also
lands on every proxied response, including `/s/` and `/api/`.

A browser given two CSP headers enforces **both**: a resource must satisfy each policy
independently. That makes the effective policy the intersection.

**The concrete breakage:** the share page builds `img-src` *per response* so a configured
branding logo can load — `share_csp(logo_url)` in
`backend/app/modules/applications/share_page.py` widens it to `data:` or the logo's own
HTTPS origin. nginx's policy allows only `'self' data:`. So an installation that
configures an external HTTPS wordmark gets `img-src` widened by the app and then clipped
by nginx, and **the logo silently fails to load**. A `data:` logo happens to survive; an
HTTPS one does not.

This directly defeats the `_logo_source` widening added in #192.

Two `Cache-Control` headers appear the same way (`private, no-store` from the app,
`no-cache` from nginx). Harmless — they merge and `no-store` still wins — but it is the
same root cause.

**Fix:** do not let nginx add a CSP to responses it proxies from the app. Move the
`add_header Content-Security-Policy` out of the `server` block into the static-file
`location /` (nginx `add_header` does not inherit into a `location` that sets its own
headers, so verify each location after the move), or clear it for the proxied locations.
The app already sets a complete policy for everything it serves, and
`SecurityHeadersMiddleware` fills one in where a route sets none.

---

## 12 — Nested `<main>` landmark on `/budget` and `/admin/budget-pots`

**Severity:** minor, but it is an HTML validity and landmark-navigation bug.
**Measured:** those two routes render `document.querySelectorAll('main').length === 2`,
with the second inside the first. Every other route renders exactly one.

The shell renders the page landmark at `frontend/src/app/layout/shell.component.html:205`:

```html
<main id="main" class="main page-shell" …>
```

and these templates nest another one inside it:

* `frontend/src/app/pages/budget/budget-dashboard.component.html:33` and `:69`
* `frontend/src/app/pages/budget/budget-tree.component.html:33`

`main` must not be a descendant of another `main`. A screen reader offered two "main"
landmarks cannot tell the user which is the page.

**Fix:** make the inner elements `<section>` or `<div>` and keep the `bd__main` / `bt__main`
class. No styling change is needed — the selectors are class-based.

Everything else measured clean across 12 routes: no duplicate ids, no `img` without
`alt`, no button without an accessible name, exactly one `h1` per page, no heading-level
jumps, and no unlabelled form control.

---

## 13 — Budget empty state blames the wrong thing

**Severity:** minor (misleading copy).
**Reproduce:** have budgets but no fiscal year, open `/budget`.

The page says **"No budgets / cost centres created yet."** while the database holds 46
budgets, seeded by migration. The real reason the tree is empty is that no fiscal year
exists — creating one made the page populate immediately.

The string itself comes from the **sidebar**, not from the page's own empty state:
`/budget` embeds `<app-budget-year-tree>` (`budget-dashboard.component.html:73`), whose
template renders `budget.tree.empty` at `budget-year-tree.component.html:31`. With no
fiscal year the page rendered its full layout around an empty nav carrying that sentence.
(The same key is also used by `budget-tree.component.html:19` on `/admin/budget-pots`,
where it is accurate.)

The page's own empty state at
`frontend/src/app/pages/budget/budget-dashboard.component.html:38` has the related defect:
it fires on `!tree().length`, which conflates "nothing configured" with "nothing for the
selected fiscal year". The neighbouring comment already makes exactly this distinction for
the loading case:

> "There are no cost centres" and "they have not arrived yet" are different claims

The same reasoning applies here to "there is no fiscal year".

**Fix:** distinguish the cases — if budgets exist but no fiscal year does, say so and
point at `/admin/budget-pots`, where a fiscal year is created.


---

## 14 — The Playwright helper posts the wrong field name

**Severity:** major — a second, independent reason the e2e suite cannot pass.
Found while verifying the fix for finding 4, and reproduced directly.

`frontend/e2e/helpers.ts::createApplication` posts its payload as:

```ts
data: { titel }
```

The server prepends a mandatory system field named `title` to every effective form
(`backend/app/modules/forms/validation.py:89`, `system_title_field`). The submission
therefore answers:

```
422  {"field":"title","msg":"required"}
```

so `02-magic-link-flow.spec.ts` cannot pass even once the seed works. It must send
`{ title: opts.title }`.

This is the same root cause as the duplicate "Title / Application title" pair I hit by
hand while seeding: anyone who defines their own `titel` field ends up with two title
inputs, because the system field is always there.

**Fix:** send `title`, not `titel`, in the helper. Then run the suite for real — with
findings 4 and 14 both fixed, the `e2e` job is worth un-skipping in CI, which is what let
all of this rot unnoticed.

### Addendum to finding 4

The seed carried a **fifth** staleness that the original triage missed: it called
`FormsService.create_form_version(type_id, payload)` without the required `actor`
argument, which is a `TypeError` at runtime.


---

## 15 — `app-time-input` renders a duplicate `id`

**Severity:** minor, but it is invalid HTML and breaks label association.
**Measured:** in the "Create meeting" dialog, `mtg-new-time` and `mtg-new-end-time` each
resolve to **two** elements — the `<app-time-input>` host and its inner `<input class="ti__text">`.

The component is correct. `frontend/vendor/ui-kit/src/lib/time-input/time-input.component.ts:32`
declares `@Input() id`, the template puts `[id]="id"` on the inner input and `[for]="id"`
on its label. The callers pass `id` as a **static attribute**:

```html
<app-time-input id="mtg-new-time" …>
```

Angular both binds a static attribute to a matching `@Input()` **and** leaves it on the
host element, so the id lands twice. `label[for]` then resolves to whichever comes first
in the document — the host, not the field.

Four call sites, all in `frontend/src/app/features/meetings/meetings.component.html`:
lines **499**, **508**, **585**, **586**.

**Fix:** bind instead of setting the attribute — `[id]="'mtg-new-time'"`. A property
binding to a component input does not reflect onto the host. Fixing it in the callers
keeps the change inside this repository; the alternative, `host: {'[attr.id]': 'null'}` in
the ui-kit component, fixes every future caller too but needs a submodule PR.

---

## 16 — Meeting time prints raw `18:00:00`

**Severity:** minor (cosmetic, and inconsistent with the rest of the app).
**Reproduce:** create a meeting, open it.

```
Oct 15, 2026, 18:00:00
```

Seconds are noise, and the same app writes a timestamp differently elsewhere — the
application detail header shows `Sep 3, 2026, 7:50 PM`. Two formats, one product.

**Cause:** `frontend/src/app/features/meetings/meetings.component.html:39`

```html
{{ m.date | ldate: 'mediumDate' }}{{ m.startTime ? ', ' + m.startTime : '' }}
```

The date goes through the localized pipe; the time is **string-concatenated raw**. The API
returns exactly what appears:

```json
{"date": "2026-10-15", "startTime": "18:00:00", "endTime": "20:30:00"}
```

**Fix:** format the time rather than concatenating it — trim to `HH:MM` and respect the
locale's clock convention, ideally through the same pipe family as `ldate`.

---

## 17 — Version-diff view still renders dates as raw JSON

**Severity:** minor. Same root cause as finding 9, different code path.

`applications-detail.component.ts:397` exposes `readonly fmt = formatFieldValue;` and the
template calls it at `applications-detail.component.html:267`, `:273` and `:279` for
`change.old`, `change.new`, `added.value` and `removed.value`. That path never sees a
`FormFieldDef`, so it cannot branch on the field type: a `daterange` change still prints
`{"to":"…","from":"…"}` in the history card.

Finding 9's fix does not reach it. Left open deliberately — the fix needs a field lookup
by key, i.e. passing `change.key` through from the template.

**Fix:** `fmt = (value: unknown, key?: string) => key ? this.formatByField(byKey.get(key), value) : formatFieldValue(value)`, and pass the key at the three call sites.

---

## 18 — English UI uses US date order *(your call)*

**Severity:** you decide.

The date picker in the meeting dialog shows the placeholder `MM/DD/YYYY`, and the
application detail header reads `Sep 3, 2026, 7:50 PM`. Both are correct for `en-US`.

The concern is that this is a German university platform whose second language is
English, and where an English UI is likelier to be read by an international student in
Europe than by an American. `01/07/2026` means 1 July to that reader and 7 January to the
formatter. A date typed into that field can be wrong by five months without anyone
noticing.

Switching the English locale to `en-GB` gives `DD/MM/YYYY` and 24-hour time, which matches
the German side and removes the ambiguity. That is a product decision about who the
English UI is for, so I am flagging it rather than changing it.


---

## 19 — Every status-update mail to an applicant ignores their language

**Severity:** major. Wider blast radius than finding 2, which was only the first mail.
Found while fixing finding 2; **not fixed**, because the clean fix needs a product decision.

`_dispatch_notify` (`backend/app/modules/flow/action_dispatcher.py:75`) takes the mail
language only from `action.params["lang"]`. Nothing under `backend/app/modules/flow/`
ever writes that param — a grep for `lang` in that package comes back empty. So every
`notify` action, including the implicit auto-mail built at
`backend/app/modules/flow/dispatch.py:99-113` with `recipients=[{"kind":"applicant"}]`,
renders in `settings.mail_default_lang`.

In other words: an applicant who filed in English is told in German that their
application was approved or rejected.

**Why it is not simply fixed:** when a `notify` action carries an explicit `templateKey`,
applicant and team recipients are collected into **one** `MailMessage`. One language has
to serve both, so splitting that send into two languages is a design change, not a bug
fix.

**The unambiguous subset**, if you want it done without the wider decision: in
`_dispatch_notify`, when no `lang` param is set *and* every recipient spec is
`{"kind": "applicant"}`, resolve the application language before the state-label lookup at
`action_dispatcher.py:80-87` — otherwise the body turns English while `{{ status }}` stays
German. That covers the implicit auto-mail and the applicant half of the no-`templateKey`
path in `notifications/service.py:500`.

A related, smaller gap: `notify_erasure_executed` / `notify_erasure_rejected`
(`backend/app/modules/notifications/privacy.py:81,110`) also never pass a language. An
erasure request can be keyed on a principal rather than an application, and `principal`
has no language column, so there is not always a language to resolve. Genuinely ambiguous.

---

## 20 — Upload hint does not say which file types are allowed *(your call)*

**Severity:** you decide. Not a defect — a question of how much the hint should say.

The attachment hint reads:

> Max 10 MB per file. Drag files here or pick them — scanned for malware after upload.

It states the size limit but not the type limit. Uploading a `.txt` answers **415** and
the reader only then learns the file was never going to be accepted.

To be clear about what is **not** wrong here: the rejection is handled properly. The
server enforces an allowlist and cross-checks the sniffed type against the extension
(`backend/app/modules/files/mime.py:20,168`), and the UI does show a toast, *"File type
not allowed."*, within 300 ms. I first reported this as silent because my initial probe
waited four seconds and missed the toast; a per-300 ms re-test found it every time.

So the only open question is whether the hint should name the accepted types up front, or
whether learning by rejection is good enough.


---

## 21 — Version-diff row reads "Changedtermin"

**Severity:** minor (visual).
**Found** while verifying the fix for finding 17.

A changed field in the version history rendered as:

```
Changedtermin: 07/01/2026 → 08/01/2026
```

The template does separate the two:

```html
<app-badge variant="warning">{{ 'applications.history.diff.changed' | t }}</app-badge>
<code>{{ change.key }}</code>:
```

but Angular compiles with `preserveWhitespaces: false`, so the newline between the two
elements is removed and the boxes end up flush. Measured with
`getBoundingClientRect()`: the gap between the badge and the `<code>` was **0 px**, on the
same line — so this is what a reader actually sees, not an `innerText` artefact.

**Fix:** `.det__diff app-badge { margin-right: var(--space-1); }` in
`applications-detail.component.scss`. A CSS margin rather than an `&nbsp;`, so the rule
holds for the added/removed rows too.


---

## Decisions taken on the three open items

All three were put to the maintainer rather than guessed.

* **#18 — en-GB.** The English UI now formats through `en-GB`: `01/07/2026` and a 24-hour
  clock, matching the German side. One mapping point (`FORMAT_LOCALES` /
  `toFormatLocale` / `I18nService.formatLocale`) sits between the UI locale and `Intl`;
  `locale()` still returns the bare `de`/`en` the translation catalogue is keyed on.
  Fixing this also caught several call sites that were passing a bare locale to `Intl`
  already — `deadlines.component.ts` rendered `toLocaleDateString('en')`, i.e. `7/1/2026`
  for 1 July.

  **Open follow-up:** the ui-kit datepicker hardcodes its placeholder, `format()` and
  `parse()` on `lang === 'de'`, so English *entry* is still MM/DD/YYYY while display is
  now DD/MM/YYYY. The kit is a git submodule and needs its own PR. The mismatch is
  visible to the user, where the previous all-US behaviour was silently wrong, so this is
  an improvement rather than a regression — but it is not finished until that PR lands.

* **#8 — short prefix.** The confirmation screen shows the first eight characters,
  uppercased (`1195A615`). The full id still reaches the record link, the URL and the
  mailed link. A tooltip carrying the full id was considered and rejected: it is not
  selectable, `aria-label` would read 36 characters aloud in place of the short text, and
  it would put the raw UUID back on screen.

* **#19 — applicant-only subset.** Implemented exactly the unambiguous part: when a
  `notify` action names no language and every recipient is the applicant, the language
  comes from the application, resolved before the status label so body and label agree.
  A recipient list containing a team member keeps the default, because applicant and team
  share one `MailMessage` there and choosing a language for both is a product decision.

---

# Round two — sweep of the merged code

A second, deeper pass over `main` at `7a8bd323`, on the areas the first sweep never
reached: the meeting lifecycle and live voting, the protocol render, backups, the webhook
SSRF guard, search, and both colour schemes. Same local stack, same six roles.

| # | Severity | Area | Summary | State |
| --- | --- | --- | --- | --- |
| 22 | **major** | meetings | A meeting manager is locked out once a minute-taker is assigned | **fixed** |
| 23 | **major** | voting | The quorum counts members who cannot cast | **fixed** |
| 31 | **major** | voting | The minute-taker can open a vote but cannot close it | **fixed** |
| 32 | medium | meetings | "Finalized automatically on close" is true only in the browser | open |
| 24 | medium | voting | Vote buttons enabled for members the server rejects | **fixed** |
| 27 | medium | audit | The audit log prints a raw UUID for a form config change | **fixed** |
| 29 | medium | deploy | The documented webhook allowlist variable does nothing | **fixed** |
| 25 | minor | meetings | Toast reads "Action failed.: ..." | open |
| 26 | minor | meetings | The vote counter does not follow an attendance change | open |
| 28 | minor | audit | German quotation marks in the English UI | **fixed** |
| 30 | minor | voting | The vote progress counter can read "2 of 1" | open |
| 33 | **major** | deploy | Eight more documented env keys are read by nothing | partly fixed |

---

## 22 — A meeting manager is locked out once a minute-taker is assigned

**Severity:** major. An unavailable minute-taker cannot be replaced.

`frontend/src/app/features/meetings/meeting-session.service.ts:121`

```ts
if (m.protokollantId) return !this.isProtokollant();
```

`isFollower()` therefore becomes true for everyone except the minute-taker as soon as one
is set. `meetings.component.html:95` then wraps the **whole** management surface in
`@if (!beamerMode() && !isFollower())` — the control toolbar (open session, close, edit
meeting, delete meeting), the agenda editor and vote creation.

Measured on one meeting, same server state, two sessions:

| role | canControl | canManage | canWrite | isProtokollant | UI shows |
| --- | --- | --- | --- | --- | --- |
| admin | true | true | true | false | Beamer view, attendance only |
| manager | true | true | true | false | (same) |
| protocol | true | true | true | **true** | Open session, Close, Edit meeting, Delete meeting, agenda editor, vote creation |

The exclusivity itself is deliberate and documented at `meeting-session.service.ts:108-113`
— two people must not edit one protocol at once. The defect is that it is applied to the
whole management surface rather than to protocol editing. The template's own inner guard
`@if (m.canControl || canWrite() || m.canManage)` (line 97) is unreachable dead code for a
non-minute-taker, which is good evidence the coupling was not intended.

**The bite:** the minute-taker is changed in the settings dialog
(`meetings.component.html:565`), opened from the toolbar button that this hides. If the
assigned minute-taker is unavailable, nobody can reassign them, start the meeting, or
delete it — the API is the only way out.

**Fix:** gate the protocol EDITOR on the protokollant exclusivity, and gate the toolbar,
agenda editor and vote creation on `canControl` / `canManage` / `canWrite` as the inner
guard already intends.

---

## 23 — The quorum counts members who cannot cast

**Severity:** major, and `voting` is a critical module (100% branch coverage required).

Two different definitions of "eligible":

* **Quorum denominator** — `backend/app/modules/livevote/service/votes.py:255`
  `vote_eligible_count` counts members whose **Gremium role** carries `vote.cast`.
* **Cast gate** — `backend/app/modules/voting/service.py:420`
  ```python
  if not principal.has("vote.cast") or not self._eligible_group_member(principal, vote.eligible_group):
      raise ForbiddenError("Not eligible to vote in this ballot.")
  ```
  requires the **global** `vote.cast` permission as well.

So the denominator counts people the gate rejects. Measured against one open vote whose
`tally.eligible` was **4**, all four holding the same group `vote:…60e1`:

| role | global vote.cast | POST /votes/{id}/ballot |
| --- | --- | --- |
| admin | yes | **200** |
| member | yes | **200** |
| manager | no | **403** Not eligible to vote in this ballot. |
| protocol | no | **403** Not eligible to vote in this ballot. |

`manager` and `protocol` are counted in the quorum and cannot vote. A vote with a 75 %
quorum would need 3 of those 4 and could never reach it. "Sachbearbeitung" and "Protokoll"
are plausible real roles for people who also sit in the committee.

This also contradicts the design note in `backend/app/modules/auth/rbac.py:96-101`, which
says an active Gremium role with `vote.cast` is what grants voting eligibility.

**Fix:** pick ONE definition. Either drop the global-permission half of the cast gate and
let the namespaced group decide (which is what `vote_group_key` was built for), or count
the quorum with the same rule the gate enforces. Whichever is chosen, the two must agree.

---

## 24 — Vote buttons are enabled for members the server will reject

**Severity:** medium. Follows from 23 but is worth fixing separately.

Yes / No / Abstain render enabled for a member who cannot cast. The failure only appears
after the click, as a toast. The client already knows the answer — it has the principal's
permissions and the vote's `eligibleGroup` — so it can disable the buttons and say why.

---

## 25 — Toast reads "Action failed.: …"

**Severity:** minor (copy).

The rejected cast surfaces as:

```
Action failed.: Not eligible to vote in this ballot.
```

A full stop immediately followed by a colon — a prefix that already ends in punctuation
being concatenated with `": "`. Either drop the stop from the prefix or drop the colon.

---

## 26 — The vote counter does not follow an attendance change

**Severity:** minor.

With the vote open, marking a member present left the counter at `0 of 0 present have
voted`. The attendance write reached the server (`GET .../attendance` showed
`status: present`), and after a reload the counter read `0 of 1`. So the value is right
and only the live view is stale — the attendance mutation does not refresh the tally.

---

## Verified working in this round

* Meeting lifecycle as the minute-taker: add free-text agenda item, open session
  (planned -> live), protocol draft auto-created, live presence ("Viewing live (1)").
* Vote creation with options, secret-ballot flag and majority rule; the vote opens and
  appears under its agenda item.
* Casting works for a principal holding both the group and the global permission (200).
* The rejection is surfaced to the user rather than failing silently.

---

## 27 — The audit log prints a raw UUID for a form config change

**Severity:** medium. It breaks the project's own `no-uuids-in-ui` rule.
**Reproduce:** edit a form, open `/admin/audit`.

```
Alina Admin changed the configuration (form:a257b8e0-0c78-43cb-938f-a4924f68443f).
```

The actor resolves correctly — that half was fixed before. The TARGET does not. The
neighbouring flow entry reads `(flow:global)`, which is legible only because its id is
literally the word `global`.

**Cause:** the frontend falls back to `type:id` when the server sends no label —
`frontend/src/app/pages/admin/audit/audit-log.component.ts:502`

```ts
private targetLabel(e: AuditEntry): string {
  if (e.targetLabel) return `„${e.targetLabel}“`;
  if (e.targetType && e.targetId) return `${e.targetType}:${e.targetId}`;
```

and the server does not send one for this type. `resolve_target_labels`
(`backend/app/modules/audit/service.py:332`) resolves `application`, `gremium`,
`application_type`, `role`, `principal`, `webhook` and `vote` — but **not `form`**, which
is the target type a form config change writes.

The id is resolvable: `a257b8e0-…` is the application type's own id, and
`application_type` is already handled a few lines below. Only the mapping is missing.

**Fix:** resolve `form` (and check `flow` and `site_config` while there) through the
application-type name in `resolve_target_labels`. The memory `no-uuids-in-ui` states the
rule: resolve ids to names SERVER-SIDE in the serializer, and "if you see a UUID on
screen, a serializer skipped the name resolution."

---

## 28 — German quotation marks in the English UI

**Severity:** minor.

`audit-log.component.ts:503` wraps a resolved target in `„…“` — German low-9 quotes —
whatever the active locale. English uses `“…”`. The character pair is hardcoded rather
than taken from the locale.

**Fix:** either drop the decoration and let CSS or the surrounding copy carry it, or take
the pair from the translation catalogue so each locale supplies its own.

---

## 29 — The documented webhook allowlist variable does nothing

**Severity:** medium — a security control an operator believes is on, and is not.
**Reproduce:** set the variable exactly as `deploy/.env.example` shows, then read it back.

`deploy/.env.example:118` ships:

```
WEBHOOK_ALLOWLIST=host1,host2     # optional zusätzlich zu IP-Block
```

The setting is `webhook_host_allowlist` (`backend/app/settings.py:205`). `Settings` uses a
plain `SettingsConfigDict` with no `env_prefix` and no alias, so the variable it reads is
**`WEBHOOK_HOST_ALLOWLIST`**. `extra="ignore"` means the documented name is dropped in
silence.

Measured on the running stack, with `WEBHOOK_ALLOWLIST=localhost` set in `deploy/.env`:

```
webhook_host_allowlist = []
```

and a webhook to `http://example.com/hook` — a host that is NOT in the configured
allowlist — was accepted with **201**.

**Why it matters beyond the typo:** `_strict_security_warnings`
(`backend/app/settings.py:327`) warns loudly whenever the allowlist is empty under
hardening. An operator who follows the shipped example gets that warning and has no way to
silence it, because the name they were told to use is not the name that is read.

**Fix:** rename the key in `.env.example` to `WEBHOOK_HOST_ALLOWLIST`, or add
`validation_alias=AliasChoices("WEBHOOK_HOST_ALLOWLIST", "WEBHOOK_ALLOWLIST")` to the
field so both work. Renaming the example is the smaller change; the alias is kinder to
anyone who already copied the old name into a running deployment.

**Not a finding, checked and deliberate:** the guard accepts plain `http` as well as
`https` — `webhooks/ssrf.py:3-4` states that explicitly, so an unencrypted target is a
documented choice rather than an oversight.

---

## Also verified working in round two

* **Backups, end to end.** Create → 202 → `done` in under 5 s → 194 842 B archive with a
  sha256 and the schema revision `a7c3f1e59d84` recorded. The export is a real
  `age-encryption.org/v1` file, and it decrypts with the private key to `db.dump` plus
  `manifest.json`. RBAC is right: `manager`, `member` and `nobody` all get 403 on list and
  on create.
* **The webhook SSRF guard.** Every one of these was refused with 400: loopback v4, the
  name `localhost`, the metadata IP `169.254.169.254`, `10/8`, `192.168/16`, `172.20/16`,
  IPv6 `::1`, and the internal service name `minio:9000`. `file://` and `gopher://` are
  refused at validation with 422. Only public http/https targets are accepted.
* **Contrast.** No WCAG AA failure on 12 routes in BOTH light and dark, measured with
  alpha compositing over the real ancestor chain and the large-text threshold applied.
  (An earlier run of my own checker reported three failures; those were a parser bug of
  mine — it read `color(srgb 0.12 0.36 0.22 / 0.22)` floats as 0-255 values. Fixed and
  re-run before reporting anything.)
* **Nothing else flagged across 26 routes**: no `[object Object]`, no raw JSON, no ISO
  date, no `NaN`, no leaked `HH:MM:SS`, no untranslated key, no console error. The single
  hit was the audit UUID in finding 27.

---

## 30 — The vote progress counter can read "2 of 1"

**Severity:** minor on its own, but it exposes the model split behind finding 23.
**Observed live**, verbatim:

```
2 of 1 present have voted
```

Two ballots had been cast (by `admin` and `member`, neither marked present) while exactly
one member (`protocol`) was marked present. The numerator counts ballots; the denominator
counts *present* members — but casting never required being present, so the numerator can
exceed the denominator.

Either casting should require attendance, or the progress line should be denominated in
the set that may actually cast. Right now the sentence can be arithmetically impossible,
which is the visible symptom of the same "two definitions of eligible" problem as
finding 23.

---

## 31 — The minute-taker can open a vote but cannot close it

**Severity:** major. It strands an open vote in a live session.

The two ends of a vote's lifecycle are gated on different rules.

* **Create / open** — `backend/app/modules/livevote/router.py:415` and `:483` gate on the
  meeting's `can_manage_votes` flag, which `permissions.py:56` grants to the protokollant
  by design: *"Check who opens and closes votes: manager, protokollant, or `vote.manage`."*
* **Close** — `backend/app/modules/voting/router.py:112` calls
  `service.assert_can_manage_vote(...)`, a gremium-scoped `vote.manage` check that admits
  an admin, a global `vote.manage` holder or a per-gremium `vote.manage` role. It does
  **not** admit the protokollant.

So the flag promises what the close gate refuses. Measured on one open vote:

| role | `canManageVotes` | POST /votes/{id}/close |
| --- | --- | --- |
| protocol (the minute-taker) | **true** | **403** "not allowed to manage this vote" |
| manager | true | 200 |
| admin | true | 409 (already closed by manager) |

The minute-taker had created and opened that very vote through the UI minutes earlier, so
this is not a read-only role stumbling into a write — it is the person running the session
being unable to finish what the same application let them start. The UI shows them a
"Close vote" button, because it renders from `canManageVotes`.

**Fix — one of two, and it is a decision:** either admit the protokollant in
`assert_can_manage_vote` (which matches the documented intent of `can_manage_votes` and
the fact that the minute-taker runs the session), or stop granting `can_manage_votes` on
protokollant alone (which would also remove their ability to open a vote, and would need
the UI to stop offering it). The first looks right, but it widens who may close a vote and
fire the resulting flow branch, so it belongs in the critical-module review rather than in
a quick patch.

---

## 32 — "Finalized automatically when the session is closed" is true only in the browser

**Severity:** medium-to-major, and partly a product call. The protocol is the record of the
meeting.

The meeting page promises, on screen:

> The minutes are finalized and sent automatically when the session is closed.

That orchestration lives entirely in the **client**.
`frontend/src/app/features/meetings/meeting-session.service.ts:206`:

```ts
closeMeeting(): void {
  this.api.patchMeeting(m.id, { status: 'closed' }).subscribe({
    next: (updated) => {
      const proto = this.protocol();
      // The finalize step is implicit: render the PDF and mail it to the list.
      if (proto && !proto.isLocked) this.finalize();
    },
```

The server does not do it. `backend/app/modules/livevote/service/lifecycle.py:138` sets
`closed_at`, sets the status, commits and emits — and enqueues nothing.

**Measured:** closing the meeting with `PATCH /api/meetings/{id} {"status":"closed"}` left
`status: closed` with a protocol still `draft` for 150 s. The worker log over that whole
window shows only `cron:process_deadlines` — no render job was ever enqueued. An explicit
`POST /api/protocols/{id}/finalize` then produced everything correctly.

So the minutes are silently not produced whenever the close does not come from a browser
that survives long enough to fire the second request: any API or MCP client, a closed tab,
a lost connection between the two calls, or a failure of the second call.

The codebase already knows this can happen — `meetings.component.html:115` carries a retry
button gated on `status === 'closed' && !proto.isFinal`, commented "Meeting closed but the
protocol is a draft again: the render failed and rolled back. The explicit retry is the
only path to a final protocol." That covers a failed render; it does not cover a close that
never asked for one.

**Fix:** enqueue the finalize server-side on the transition to `closed`, and let the client
call stay as an optimistic fast path. Then the promise on screen is true for every client.

**Verified working, once finalize is actually called:** the protocol reached `status:
final`, `GET /api/protocols/{id}/pdf` returned 32 623 bytes of real PDF (`%PDF-1.5` …
`%%EOF`), and the mail went to the gremium list as "Sitzungsprotokoll StuPa —
15.10.2026". The pytex render path and the mail dispatch are both sound; only the trigger
is missing.


---

## 33 — Eight more documented env keys are read by nothing

**Severity:** major in aggregate. Found by auditing the whole template after finding 29,
rather than stopping at the one key that was reported.

There is exactly one `BaseSettings` in the repository (`backend/app/settings.py:25`); the
worker imports it and pytex uses bare `os.environ`. Cross-checking all 76 keys of
`deploy/.env.example` against its 94 env names turns up these, all silently ignored
because `extra="ignore"`:

| Key | Status | What actually happens |
| --- | --- | --- |
| `WEBHOOK_ALLOWLIST` | **fixed** | finding 29 — renamed, with an alias so existing deployments keep working |
| `SMTP_FROM` | open | **Dead.** The sender address is `MAIL_FROM` (`settings.py:136`). An operator who fills in `SMTP_FROM` sends from the fallback `noreply@antragsplattform.local` and nothing says so. `scripts/e2e.sh:80` sets it just as uselessly. |
| `WEBHOOK_HMAC_KEY` | open | **Dead**, and misleading about security: signing uses the per-webhook `hook.secret` from the database (`webhooks/service.py:240,267`). The template implies a global signing key that does not exist. |
| `AUDIT_DB_ROLE` | open | **Dead.** The role name is hardcoded in `migrations/versions/0001_baseline.py:40`, `0034_config_revision.py:25` and `deploy/db/roles.sql:32`. Changing the value does nothing. |
| `NEXTCLOUD_WEBDAV_URL`, `NEXTCLOUD_USER`, `NEXTCLOUD_APP_PASSWORD`, `NEXTCLOUD_BASE_PATH`, `NEXTCLOUD_TIMEOUT_SECONDS` | open | **Dead — the whole Nextcloud/WebDAV export does not exist in the code.** The only occurrences are the template and some memory files. The template asks the operator for a real app password for a feature that is not there. |

### A second trap, found while fixing the first

The plain rename would not have been enough. `webhook_host_allowlist` is `list[str]`, and
pydantic-settings JSON-decodes complex fields, so the documented comma format aborts the
start:

```
WEBHOOK_HOST_ALLOWLIST=host1,host2  ->  SettingsError: error parsing value for field …
WEBHOOK_HOST_ALLOWLIST=["a","b"]    ->  ['a', 'b']
WEBHOOK_ALLOWLIST=host1,host2       ->  []
```

So the "obvious" fix turns a silent no-op into a hard boot failure. The change therefore
adds `NoDecode` plus a validator that accepts both the comma format and the JSON list.
**`CORS_ALLOW_ORIGINS` had the identical trap** and got the same treatment — it also gates
the live-vote WebSocket origin check (`livevote/connection.py:84`), so
`CORS_ALLOW_ORIGINS=https://a.example` would have crashed the API at boot. It is
undocumented in the template as well.

### The durable guard

`backend/tests/unit/test_env_example_settings_parity.py` now parses every key in the
template and asserts each is either read by a `Settings` field or alias, or listed in an
annotated exception list (compose/postgres/altcha/pytex keys, plus the dead ones above
with a one-line reason each). A newly invented key fails CI, and the dead ones are
inventoried rather than invisible.

**Also undocumented and worth adding to the template:** `DELEGATION_VOTING_ENABLED` — a
bylaws-level feature switch that defaults to OFF, which an operator has no way to discover.
