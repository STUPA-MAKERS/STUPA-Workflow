# Logo-Set

Offizielle **STUPA**-Assets aus dem Corporate Design (Nextcloud
`Corporate Design/Icons-und-Logos/`, requirements N1). 1:1 als Ersatz der
früheren CD-Stil-Platzhalter eingesetzt.

| Datei | Verwendung | Quelle (Nextcloud CD) |
|---|---|---|
| `stupa-mark.svg` | quadratische Marke (Favicon, App-Icon) | `Icon/STUPA/STUPA-Logo_icon-only.svg` |
| `stupa-wordmark.svg` | Header-Logo (Wort + Marke) | `Logo/STUPA/STUPA-Logo_gray-text.svg` |
| `hsrt-wordmark.svg` | Footer-Co-Branding | **Platzhalter** — kein HSRT-Asset im CD (STUPA-only) |

`favicon.ico` (`frontend/public/`) ist aus `stupa-mark.svg` gerendert
(16/32/48/64 px, ImageMagick).

**Theme/Hell-Dunkel:** Die Marke ist mehrfarbig (CD-Signalfarben) und liest auf
hellem wie dunklem Header. Für die Wortmarke wird die neutrale CD-Variante
`gray-text` (#706f6f) verwendet — kontraststabil in Light- **und** Dark-Theme,
da das Logo per `<img src>` eingebunden ist und so kein `currentColor`/Theme-Token
erbt. Eine echte Light/Dark-Umschaltung (black-text/white-text) würde
`shell.component` (Markup/SCSS) berühren → bewusst vermieden (Konflikt mit T-30/T-36).
