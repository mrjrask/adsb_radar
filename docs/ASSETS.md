# Artwork

Airline logos and aircraft illustrations live in `images/` and are installed to
`/var/lib/adsb-radar/images/`. Every file is optional: a missing logo is drawn
as an airline badge, and a missing aircraft is drawn procedurally.

| Path | Contents |
| --- | --- |
| `images/air/<ICAO>.png` | Airline logo, named by the airline's ICAO code (`DAL.png`, not `DL.png`). PNG preferred; JPG/JPEG also work. |
| `images/aircraft/<ICAO>/<TYPE>.png` | Side view in that airline's livery, named by ICAO type designator (`B738.png`). |
| `images/aircraft/_generic/<TYPE>.png` | Unbranded fallback for a type. |

Aircraft lookup order: exact airline/type, a sibling type in the same family
(for example `B739` for a `B738`), exact `_generic` type, sibling `_generic`
type, then the procedural illustration. Nothing is downloaded at install or
run time.

Use transparent PNGs. The renderer trims transparent margins and scales to the
layout, so keep the original aspect ratio. For a sharp 4K board, prefer aircraft
artwork at least 1500 pixels wide.

## Adding or replacing artwork

Commit the files at the paths above, then on the Pi:

```sh
cd ~/adsb_radar
git pull --ff-only
sudo ./install.sh
```

Installation adds or replaces the supplied files and keeps installed files that
are not in the checkout. To remove an installed image, delete that file from
`/var/lib/adsb-radar/images/` and restart the display service. The `--purge`
uninstaller removes all installed artwork.
