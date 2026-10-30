# Source and asset provenance

This is a Raspberry Pi HDMI adaptation of projects owned by `mrjrask`:

- [adsb-i75w](https://github.com/mrjrask/adsb-i75w): admin settings schema,
  color presets, visibility-dome JavaScript, and page styling.
- [desk_display](https://github.com/mrjrask/desk_display), source snapshot
  `09a0c2cfc846265bc90829c2b191e4f498bf3daf`: high-resolution flight layout,
  aircraft-art lookup/procedural rendering, airline/type directory, visibility
  cone, and route parsing/geometry. These modules were adapted to the smaller
  standalone application and use local network receiver data.

No source image files, proprietary logos, font binaries, or private
configuration were copied into this repository. `images/` contains empty
placeholders and upload instructions. Artwork is supplied manually by the
repository owner and retains its applicable rights.

Fonts are installed as Debian packages, with their respective notices:

- Bebas Neue: `fonts-bebas-neue`; airport-style headings and split-flap tiles.
- JetBrains Mono: `fonts-jetbrains-mono`; clocks and numerical instruments.
- DejaVu Sans: `fonts-dejavu-core`; descriptive text and fallback glyphs.

Debian installs each package's license/copyright information under
`/usr/share/doc/<package>/copyright`. This project draws the split-flap tiles
itself; it does not bundle or require a proprietary font named Flipboard.

Optional aircraft type metadata comes from
[tar1090-db](https://github.com/wiedehopf/tar1090-db). Optional route data comes
from [adsbdb](https://www.adsbdb.com/). These services and their data have their
own terms and availability. Data is cached locally; neither source is needed
for basic receiver polling or HDMI output.
