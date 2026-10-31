# Flight route enrichment

Both projects use the same dependency-free `RouteEnricher` engine and contract
suite, vendored in `adsb_radar/route_enrichment.py` (adsb_radar) and
`services/route_enrichment.py` (desk_display). Update both copies and
`tests/test_route_enrichment.py` together. The application adapters retain their
existing SQLite schemas, route models, HTTP configuration, and renderers.

## What caused missing or misleading routes

- adsb_radar only queried adsbdb. desk_display already used adsb.lol, but the
  independently maintained pipelines had different fallback/cache behavior.
- A miss suppressed retries for an hour. A geometrically rejected radar route
  suppressed refresh for an entire day, even though the renderer hid it.
- Both pipelines tried major-airline prefixes with a regional flight's digits.
  Matching digits and a plausible route do not establish a codeshare. Those
  guesses could show a different flight's airports, name, and logo.
- A successful batch response could omit a callsign or contain malformed data;
  treating that as an explicit miss hid useful static-file fallback results.
- desk_display performed slow route requests inside the position polling loop.

## Lookup and cache policy

1. Read the local SQLite route cache. No display or web request contacts a route
   provider. Each route keeps its provider name in its JSON `source` field.
2. Request due ICAO callsigns in one adsb.lol routeset batch (maximum 100).
3. If a callsign has no valid batch answer, try the adsb.lol static VRS route file
   (maximum 10 callsigns per round).
4. Ask adsbdb about remaining misses, partial routes, or routes that do not fit
   the aircraft's position (maximum 3 callsigns per round, nearest first).

Callsigns are uppercased, ASCII whitespace is removed, and purely numeric flight
numbers are unpadded. Alphanumeric ATC suffixes are preserved, never guessed or
stripped. Registrations, malformed identifiers, and IATA prefixes are excluded.
IATA designators can be shared between airlines, so converting them without an
explicit operator identity would create false matches. Provider replies must
match the requested ICAO identity. No marketed flight number is synthesized.
Old cached routes carrying guessed codeshares without a source are invalidated.

Found routes refresh daily. Confirmed misses, partial results, and routes that
fail the existing geographic checks retry after five minutes. Invalid cache
JSON and future timestamps trigger refresh. Timeouts, 403s, 429s, invalid JSON,
and server errors are failures, not negative cache entries; each provider backs
off for two minutes without blocking other providers. Negative entries are only
written after the configured fallback sources have answered. Successful existing
routes survive provider failures without extending their age; displays stop
using them after seven days. Every displayed route still passes the same
position/altitude check. Multi-stop VRS routes and adsbdb midpoints retain their
legs for local leg selection. Invalid airport coordinates and broken stops are
rejected rather than joined into an invented leg.

The radar metadata thread processes the nearest ten aircraft used by its flight
board/list. desk_display's route worker uses its own SQLite connection and a
one-item latest-locations queue, so provider timeouts cannot delay live position
polling. `adsb_collector.py --once` remains synchronous for manual diagnostics.
The desk LED board and web/remote frames consume the same cached `OverheadFlight`.
The radar HDMI output and web preview consume the same cached scene.

## Diagnostics and limits

Coverage is a point-in-time snapshot of **eligible ICAO flight callsigns in the
current lookup scope**, not a claim about all commercial traffic. It reports
complete matches, partial routes, rejected geography, unknown routes, pending
lookups, request/failure counts per provider, and per-callsign outcomes. Zero
eligible callsigns produces a null percentage. A timestamp makes an old snapshot
recognizable. Counters cover the current resolver process lifetime.

- adsb_radar: sign in to the admin page and inspect route diagnostics, or read
  its authenticated `/status.json` `routes` object.
- desk_display: the Stats page shows route coverage and last-check age;
  `/api/stats` includes the full `routes` snapshot. The server command
  `python scripts/adsb_route_check.py` prints the same persisted snapshot and
  explains each cached route/source. `--live` makes explicit diagnostic requests.

Free sources have incomplete or stale schedules. These routes are schedule
metadata, not a live dispatch feed; diversions, charters, reused callsigns,
ambiguous multi-leg flights, and codeshares without an explicit identity mapping
can remain unknown. No paid API, new account, receiver change, or inferred
origin/destination is introduced. Live coverage improvement must be measured
against the actual receiver feed after deployment; unit fixtures are not a
coverage benchmark.

Provider references:
- [adsb.lol routeset implementation](https://github.com/adsblol/api/blob/main/src/adsb_api/utils/api_routes.py)
- [VRS standing data](https://github.com/vradarserver/standing-data)
- [adsbdb API documentation](https://www.adsbdb.com/)
