"""QA data seed, driven through the REST API from the host.

`qa_seed.py` writes identities straight into the database, because only the server can
mint a session cookie. Everything else goes through the public API instead, so the QA
data passes the same validation as real data and a schema drift shows up here rather
than as a mystery in the UI.

Run it against the local QA stack, after `qa_seed.py`:

    python3 deploy/e2e/qa_api_seed.py

It is idempotent in the sense that it tolerates a re-run: every step reports its own
failure and the script keeps going, so a partial stack still ends up with data.

CSRF: the middleware only guards a cookie-authenticated unsafe request, and it issues
`XSRF-TOKEN` on any response that lacks it. So one GET first, then echo the cookie back
in `X-XSRF-TOKEN`.
"""

from __future__ import annotations

import json
import pathlib
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from typing import Any

BASE = "http://127.0.0.1:8080"
ART = pathlib.Path(__file__).resolve().parent / ".artifacts" / "qa.json"


def _i18n(de: str, en: str) -> dict[str, str]:
    return {"de": de, "en": en}


class Client:
    """A cookie-carrying API client for one seeded role."""

    def __init__(self, role: str) -> None:
        art = json.loads(ART.read_text())
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.session_cookie = f"{art['sessionCookieName']}={art['cookies'][role]}"
        self.role = role
        # Prime the CSRF cookie.
        self.get("/api/auth/me")

    def _csrf(self) -> str | None:
        for c in self.jar:
            if c.name == "XSRF-TOKEN":
                return c.value
        return None

    def _cookie_header(self) -> str:
        """Session cookie plus everything the jar holds.

        Setting `Cookie` by hand replaces whatever the cookie processor would add, so
        the CSRF cookie has to be folded in here or it never travels back and every
        write answers 403.
        """
        parts = [self.session_cookie]
        parts += [f"{c.name}={c.value}" for c in self.jar]
        return "; ".join(parts)

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = None
        headers = {"Cookie": self._cookie_header(), "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        token = self._csrf()
        if token and method not in ("GET", "HEAD"):
            headers["X-XSRF-TOKEN"] = token
        req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=30) as resp:
                raw = resp.read().decode()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, raw

    def get(self, path: str) -> tuple[int, Any]:
        return self.request("GET", path)

    def post(self, path: str, body: Any) -> tuple[int, Any]:
        return self.request("POST", path, body)

    def patch(self, path: str, body: Any) -> tuple[int, Any]:
        return self.request("PATCH", path, body)


def step(label: str, result: tuple[int, Any]) -> Any:
    code, payload = result
    ok = 200 <= code < 300
    mark = "ok " if ok else "FAIL"
    detail = "" if ok else f"  {json.dumps(payload)[:300]}"
    print(f"[{mark}] {code} {label}{detail}")
    return payload if ok else None


# --------------------------------------------------------------------------- fields

# No `titel` field: the server already injects a mandatory `title` into every effective
# form, so adding one duplicates it in the UI.
FIELDS: list[dict[str, Any]] = [
    {
        "key": "beschreibung",
        "type": "textarea",
        "label": _i18n("Beschreibung", "Description"),
        "help": _i18n("Worum geht es?", "What is this about?"),
        "required": True,
    },
    {
        "key": "kategorie",
        "type": "select",
        "label": _i18n("Kategorie", "Category"),
        "required": True,
        "options": [
            {"value": "kultur", "label": _i18n("Kultur", "Culture")},
            {"value": "sport", "label": _i18n("Sport", "Sports")},
            {"value": "bildung", "label": _i18n("Bildung", "Education")},
            {"value": "sonstiges", "label": _i18n("Sonstiges", "Other")},
        ],
    },
    {
        "key": "zielgruppen",
        "type": "multiselect",
        "label": _i18n("Zielgruppen", "Target groups"),
        "options": [
            {"value": "studierende", "label": _i18n("Studierende", "Students")},
            {"value": "beschaeftigte", "label": _i18n("Beschäftigte", "Staff")},
            {"value": "oeffentlichkeit", "label": _i18n("Öffentlichkeit", "Public")},
        ],
    },
    {
        "key": "betrag",
        "type": "currency",
        "label": _i18n("Beantragter Betrag", "Requested amount"),
        "required": True,
    },
    {
        "key": "termin",
        "type": "date",
        "label": _i18n("Datum der Veranstaltung", "Event date"),
    },
    {
        "key": "zeitraum",
        "type": "daterange",
        "label": _i18n("Zeitraum", "Period"),
    },
    {
        "key": "kontakt",
        "type": "email",
        "label": _i18n("Kontakt-E-Mail", "Contact email"),
        "required": True,
        "isPII": True,
    },
    {
        "key": "iban",
        "type": "iban",
        "label": _i18n("IBAN für die Auszahlung", "IBAN for payout"),
        "isPII": True,
    },
    {
        "key": "oeffentlich",
        "type": "checkbox",
        "label": _i18n("Veranstaltung ist öffentlich", "Event is public"),
    },
    {
        "key": "hinweis",
        "type": "markdown",
        "label": _i18n("Hinweise zur Förderung", "Funding notes"),
    },
    {
        "key": "positionen",
        "type": "positions",
        "label": _i18n("Kostenpositionen", "Cost positions"),
    },
    {
        "key": "anhang",
        "type": "file",
        "label": _i18n("Anhang", "Attachment"),
    },
]

# --------------------------------------------------------------------------- flow

STATES = [
    {
        "key": "entwurf",
        "label": _i18n("Entwurf", "Draft"),
        "editAllowed": True,
        "isInitial": True,
        "color": "#94a3b8",
    },
    {
        "key": "eingereicht",
        "label": _i18n("Eingereicht", "Submitted"),
        "editAllowed": False,
        "color": "#0ea5e9",
    },
    {
        "key": "pruefung",
        "label": _i18n("In Prüfung", "Under review"),
        "editAllowed": False,
        "color": "#f59e0b",
    },
    {
        "key": "angenommen",
        "label": _i18n("Angenommen", "Approved"),
        "editAllowed": False,
        "isTerminal": True,
        "color": "#16a34a",
    },
    {
        "key": "abgelehnt",
        "label": _i18n("Abgelehnt", "Rejected"),
        "editAllowed": False,
        "isTerminal": True,
        "color": "#dc2626",
    },
]

TRANSITIONS = [
    {"from": "entwurf", "to": "eingereicht", "label": _i18n("Einreichen", "Submit")},
    {"from": "eingereicht", "to": "pruefung", "label": _i18n("Prüfung starten", "Start review")},
    {"from": "pruefung", "to": "angenommen", "label": _i18n("Annehmen", "Approve"), "color": "#16a34a"},
    {"from": "pruefung", "to": "abgelehnt", "label": _i18n("Ablehnen", "Reject"), "color": "#dc2626"},
    {"from": "eingereicht", "to": "entwurf", "label": _i18n("Zurückgeben", "Return to draft")},
]


def main() -> None:
    admin = Client("admin")

    code, me = admin.get("/api/auth/me")
    print(f"seeding as {me.get('display_name')} ({code})")

    code, types = admin.get("/api/admin/application-types")
    if code != 200:
        code, types = admin.get("/api/application-types")
    if not types:
        raise SystemExit(f"no application types readable ({code}): {types}")
    type_id = types[0]["id"] if isinstance(types, list) else types["items"][0]["id"]
    print("application type:", type_id)

    step(
        "form version",
        admin.post(
            f"/api/admin/application-types/{type_id}/form-versions",
            {"fields": FIELDS, "activate": True},
        ),
    )

    step(
        "global flow",
        admin.post(
            "/api/admin/flow-versions/global",
            {"graph": {"states": STATES, "transitions": TRANSITIONS}, "activate": True},
        ),
    )

    print("\n--- verify ---")
    step("effective form", admin.get(f"/api/application-types/{type_id}/form"))
    step("active flow", admin.get("/api/admin/flow-versions/global"))


if __name__ == "__main__":
    main()
