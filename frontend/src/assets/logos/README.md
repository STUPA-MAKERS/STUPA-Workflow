# Logo-Set

Offizielle **STUPA**-Assets aus dem Corporate Design (Nextcloud
`Corporate Design/Icons-und-Logos/`, requirements N1). 1:1 als Ersatz der
früheren CD-Stil-Platzhalter eingesetzt.

| Datei | Verwendung | Quelle (Nextcloud CD) |
|---|---|---|
| `stupa-mark.svg` | quadratische Marke (Favicon, App-Icon) | `Icon/STUPA/STUPA-Logo_icon-only.svg` |
| `stupa-wordmark-light.svg` | Header-/Footer-Logo im **Light**-Theme (schwarze Schrift + Marke) | `Logo/STUPA/STUPA-Logo_black-text.svg` |
| `stupa-wordmark-dark.svg` | Header-/Footer-Logo im **Dark**-Theme (weiße Schrift + Marke) | `Logo/STUPA/STUPA-Logo_white-text.svg` |
| `stupa-wordmark.svg` | _Alt-Asset (gray-text), nicht mehr eingebunden_ | `Logo/STUPA/STUPA-Logo_gray-text.svg` |

`favicon.ico` (`frontend/public/`) ist aus `stupa-mark.svg` gerendert
(16/32/48/64 px, ImageMagick).

**Theme/Hell-Dunkel (#43):** Die Wortmarke wird theme-abhängig umgeschaltet.
`ShellComponent.logoSrc` (computed) wählt anhand von `ThemeService.resolved()`
zwischen `stupa-wordmark-light.svg` (schwarze Schrift) und
`stupa-wordmark-dark.svg` (weiße Schrift); gebunden via `[src]` in Header **und**
Footer. So bleibt die Schrift in beiden Modi kontraststark — die mehrfarbige
Marke (CD-Signalfarben) liest ohnehin auf hell wie dunkel. Die frühere neutrale
`gray-text`-Variante (`stupa-wordmark.svg`) wirkte in beiden Modi verwaschen und
wird nicht mehr eingebunden.
