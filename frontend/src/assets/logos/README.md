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

**App icons (PWA):** the icons in `frontend/public/icons/` and `frontend/public/apple-touch-icon.png`
are `stupa-mark.svg` on an opaque white square. The mark fills 80 % of the width in the `any`
icons and in the 180 px iOS icon, and 62 % in the `maskable` icons, so that it stays inside the
safe zone when Android crops the icon to a circle. The icons have no transparency, because iOS
fills a transparent area with black. `src/app/core/pwa/install-metadata.spec.ts` checks the
size and the opacity of each file. To render them again, use cairosvg and Pillow:

```python
import io, cairosvg
from PIL import Image

def icon(svg: bytes, size: int, scale: float) -> Image.Image:
    m = round(size * scale)
    png = cairosvg.svg2png(bytestring=svg, output_width=m * 4, output_height=m * 4)
    mark = Image.open(io.BytesIO(png)).convert('RGBA').resize((m, m), Image.LANCZOS)
    bg = Image.new('RGBA', (size, size), (255, 255, 255, 255))
    bg.alpha_composite(mark, ((size - m) // 2, (size - m) // 2))
    return bg.convert('RGB')
```

**Theme, light and dark:** the theme selects the wordmark. The computed
`PublicHeaderComponent.logoSrc` (the top bar of the public pages) reads
`ThemeService.resolved()` and picks either `stupa-wordmark-light.svg` (black text) or
`stupa-wordmark-dark.svg` (white text). The text keeps a strong contrast in both modes. The
navigation rail of the signed-in app and the public bar on a phone show `stupa-mark.svg`
alone: the multi-color mark (CD signal colors) reads well on a light and on a dark background.
The earlier neutral `gray-text` variant (`stupa-wordmark.svg`) looked washed out in both modes.
The app no longer loads it.
