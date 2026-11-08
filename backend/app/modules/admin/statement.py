"""The built-in accessibility statement (spec 000495).

The statement is a free text of the site config (``freetexts.accessibilityStatement``),
Markdown per language, so the admin edits it on ``/admin/texts``. A config without the
field reads as this draft. The admin fills the brackets: the date of the last check, a
contact address and the Schlichtungsstelle. The page ``/barrierefreiheit`` adds the
button "Barriere melden" below the text, so the text needs no link to the form.

The draft names the parts that are not accessible: the zoom block of the installed app
(NF/compatibility/pwa/000220, the exception of spec 000490) and the files that users
upload.
"""

from __future__ import annotations

DEFAULT_STATEMENT_DE = """\
Die Verfasste Studierendenschaft ist bemüht, diese Plattform barrierefrei zugänglich zu \
machen. Rechtsgrundlage ist § 10 des Landes-Behindertengleichstellungsgesetzes \
Baden-Württemberg (L-BGG).

## Stand der Vereinbarkeit

Diese Plattform ist mit den Anforderungen der WCAG 2.2, Stufe AA (EN 301 549), \
**teilweise vereinbar**. Die unten genannten Inhalte sind nicht barrierefrei.

## Nicht barrierefreie Inhalte

- In der installierten App (PWA) lässt sich die Ansicht nicht mit zwei Fingern \
vergrößern, damit Gesten wie in einer nativen App funktionieren. Im Browser lässt sich \
jede Seite vergrößern.
- Dateien, die Nutzende hochladen (zum Beispiel PDF-Anhänge), prüfen wir nicht auf \
Barrierefreiheit.

## Erstellung dieser Erklärung

Diese Erklärung beruht auf einer Selbstbewertung mit automatischen Prüfungen. \
Letzte Prüfung: [Datum eintragen].

## Feedback und Kontakt

Melden Sie uns eine Barriere über die Schaltfläche unten. Sie erreichen uns auch per \
E-Mail: [Kontaktadresse eintragen].

## Schlichtungsverfahren

Wenn Sie auf Ihre Meldung keine zufriedenstellende Antwort erhalten, können Sie sich an \
die Schlichtungsstelle wenden: [Name, Anschrift und Kontakt der Schlichtungsstelle \
eintragen].
"""

DEFAULT_STATEMENT_EN = """\
The student body strives to make this platform accessible. The legal basis is § 10 of \
the Disability Equality Act of Baden-Württemberg (L-BGG).

## Compliance status

This platform is **partially compliant** with WCAG 2.2, level AA (EN 301 549). The \
content listed below is not accessible.

## Content that is not accessible

- In the installed app (PWA), the view cannot be zoomed with two fingers, so gestures \
work as in a native app. In the browser, every page can be zoomed.
- We do not check files that users upload (for example PDF attachments) for \
accessibility.

## Preparation of this statement

This statement is based on a self-assessment with automated checks. Last check: [enter \
the date].

## Feedback and contact

Report a barrier with the button below. You can also write to us: [enter the contact \
address].

## Enforcement procedure

If you do not get a satisfactory answer to your report, you can contact the \
conciliation body: [enter the name, address and contact of the conciliation body].
"""


def default_statement() -> dict[str, str]:
    """Return the built-in statement per language (a fresh dict each call)."""
    return {"de": DEFAULT_STATEMENT_DE, "en": DEFAULT_STATEMENT_EN}
