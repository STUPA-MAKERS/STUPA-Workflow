# Logo set

Official **STUPA** assets from the corporate design (Nextcloud
`Corporate Design/Icons-und-Logos/`, requirements N1). These assets replace the earlier
CD-style placeholders 1:1.

| File | Use | Source (Nextcloud CD) |
|---|---|---|
| `stupa-mark.svg` | square mark (favicon, app icon) | `Icon/STUPA/STUPA-Logo_icon-only.svg` |
| `stupa-wordmark-light.svg` | header and footer logo in the **light** theme (black text plus mark) | `Logo/STUPA/STUPA-Logo_black-text.svg` |
| `stupa-wordmark-dark.svg` | header and footer logo in the **dark** theme (white text plus mark) | `Logo/STUPA/STUPA-Logo_white-text.svg` |
| `stupa-wordmark.svg` | _old asset (gray-text), no longer in use_ | `Logo/STUPA/STUPA-Logo_gray-text.svg` |

ImageMagick renders `favicon.ico` (`frontend/public/`) from `stupa-mark.svg` at 16, 32, 48
and 64 px.

**Theme, light and dark (#43):** the theme selects the wordmark. The computed
`ShellComponent.logoSrc` reads `ThemeService.resolved()` and picks either
`stupa-wordmark-light.svg` (black text) or `stupa-wordmark-dark.svg` (white text). The header
**and** the footer bind it through `[src]`. The text keeps a strong contrast in both modes.
The multi-color mark (CD signal colors) reads well on a light and on a dark background. The
earlier neutral `gray-text` variant (`stupa-wordmark.svg`) looked washed out in both modes.
The shell no longer loads it.
