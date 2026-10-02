# Bundled fonts

Vendored so the GUI looks the same everywhere — on Windows, on Linux, and inside a
Wine bottle, none of which can be relied on to have a decent UI font. Dear PyGui's
built-in font is an ASCII-only bitmap face that renders `...` and `-` as `?`, so a
real font is not cosmetic here.

| File | Role | Size | License |
|------|------|------|---------|
| `Roboto-Regular.ttf` | UI (16 px) | 515 KB | Apache-2.0 — `LICENSE-Roboto.txt` |
| `JetBrainsMono-Regular.ttf` | Log console (14 px) | 270 KB | OFL-1.1 — `LICENSE-JetBrainsMono.txt` |

Both are redistributable. The license texts sit next to the fonts and are bundled
with them, which is what OFL-1.1 requires ("the above copyright notice and this
license ... shall be included in all copies").

## Provenance

```
Roboto-Regular.ttf
  https://raw.githubusercontent.com/googlefonts/roboto-2/main/src/hinted/Roboto-Regular.ttf
  https://github.com/googlefonts/roboto-2  (LICENSE)

JetBrainsMono-Regular.ttf
  https://raw.githubusercontent.com/JetBrains/JetBrainsMono/master/fonts/ttf/JetBrainsMono-Regular.ttf
  https://github.com/JetBrains/JetBrainsMono  (OFL.txt)
```

Both were verified after download: `sfnt` magic (`00 01 00 00`) and the family name
present in the TTF name table as UTF-16BE.

## How they are wired

`app/window.py` resolves these through `_bundled_font_dir()`, which uses
`sys._MEIPASS` when frozen and the repository otherwise. They are listed first in
`_UI_FONT_CANDIDATES` / `_MONO_FONT_CANDIDATES`; the system fonts after them are
fallbacks for a stripped bundle, and DPG's default font remains the last resort.

`app/umadump-gui.spec` ships the whole folder via
`datas=[(ROOT/"app"/"fonts", "app/fonts")]`, so the licenses travel with the fonts.
