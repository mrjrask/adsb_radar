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

## Missing artwork

When the flight board or radar list shows a badge for lack of an airline logo,
or the flight board shows a drawn or stand-in aircraft for lack of an
illustration in that airline's livery, the display adds the file it wanted to
`/var/lib/adsb-radar/missing_imagery.log`. Open it from the admin page (the
link under the live preview, `http://<Pi-IP>:8080/missing-imagery.log`) or on
the Pi. It is tab-separated, so it also opens in a spreadsheet:

| Column | Meaning |
| --- | --- |
| `first_seen` | When the display first needed it (UTC) |
| `kind` | `airline_logo` or `aircraft_image` |
| `airline`, `airline_name` | ICAO airline code and name (`DAL`, Delta Air Lines); empty for an aircraft with no airline |
| `type`, `type_name` | ICAO type designator and name (`B738`, 737-800), for illustrations |
| `callsign` | The first flight seen with it |
| `missing_file` | The file to add, relative to `images/`: `air/<ICAO>.png`, `aircraft/<ICAO>/<TYPE>.png` or `aircraft/_generic/<TYPE>.png` |
| `showing_instead` | What was shown: `badge`, `drawn`, a stand-in file, or `nothing` |

Each file is listed once however often it is seen. Once you add files and
rerun the installer, the admin page's copy leaves them out straight away, and
the display drops their rows from the file when it restarts (the installer
restarts it), so the log stays a to-do list. Demo mode logs nothing.

