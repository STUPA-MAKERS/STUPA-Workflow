# Logo-Set (Platzhalter)

**Achtung:** Dies sind eigenständige Platzhalter im CD-Stil (British Racing Green,
`currentColor` → theme-adaptiv). Die **verbindlichen HSRT/STUPA-Assets liegen in
Nextcloud** (requirements N1) und ersetzen diese Dateien 1:1, sobald verfügbar.

| Datei | Verwendung |
|---|---|
| `stupa-mark.svg` | quadratische Marke (Favicon, App-Icon) |
| `stupa-wordmark.svg` | Header-Logo (Wort + Marke), `currentColor` |
| `hsrt-wordmark.svg` | Footer-Co-Branding, `currentColor` |

`currentColor` + `var(--color-bg)` machen die SVGs **theme-abhängig** (Light/Dark)
ohne separate Dateien (Q16): die Komponente setzt `color` aus dem Theme-Token.
