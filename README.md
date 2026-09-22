# winter-mode

A HomePod-style kitchen dashboard for the ER-TFTM070-4 (7.0" TFT,
800×480) on a Raspberry Pi Zero W — built on the
[`ertftm070`](https://github.com/DorneichI/er-tftm070-4-driver) driver.

Terminal aesthetics (IBM 3270, hard 1-bit pixels, no grays), tap-only
navigation, a persistent status bar, auto-generated settings, and a
tiny web companion. Ships with three modules — clock, boston, settings —
and a module contract that makes adding your own one `module.py` (boston
keeps its map data and its query helper in the same directory).

> # ⚠️ THIS PROJECT IS COMPLETELY VIBECODED ⚠️
>
> **No human sat down and wrote this codebase. It was written by
> DeepSeek (the AI model, running in the Claude Code CLI) in a
> vibe-coding session, with a human in the loop whose job was watching
> the screen, describing what was wrong, and demanding better.**
>
> **The good part:** it genuinely works. Every feature was eye-tested
> by the human in the browser simulator, the whole test suite passes,
> and the ugly hardware quirks are documented instead of hidden.
>
> **The honest part:** no one has audited every line. There may be bugs
> nobody has stepped on yet, design choices a real engineer would
> question, and comments that overestimate their own cleverness.
>
> MIT license, no warranty, no guarantees.

---

## Run it in the simulator (no hardware)

```bash
mise install                    # Python 3.11, the Pi's version
python -m venv .venv
.venv/bin/pip install -e ".[sim]"   # dev extras: .venv/bin/pip install -e ".[dev]"
ERTFTM070_DISPLAY=sim .venv/bin/python -m wintermode
```

The display opens in your browser at <http://localhost:8000> (mouse =
touch; phones can multi-touch), the web UI at <http://localhost:8080>.
Everything runs unchanged on the Pi — the simulator faithfully replays
hardware row-timing, so what feels fast in the browser feels fast on
the Zero.

## What it is

- **Boot splash** — WINTER MODE steps up the verified crisp font sizes
  (26 → 44 → 88 — the landing step is the largest clean-size multiple
  that fits the panel), holds, cuts to black for a beat, then in.
- **The bar** — always on top: clock, rotating status items published
  by modules, view title, `[‹ BACK]` `[⌂ HOME]`. Navigation is taps
  only. No gestures: lists and grids paginate, and a list can opt into
  vertical scrolling instead — `[▲] [▼]` buttons appear automatically
  whenever it overflows, grey and inert at the ends.
- **Modules** — CLOCK (big ticking time), BOSTON (the MBTA map + trip
  planning, below), and SETTINGS (the hub).
- **Settings** — a card grid into every configurable thing: DISPLAY
  (theme dark/light/auto with the light-window schedule, always-on vs
  wake-on-touch), STATUS BAR (a toggle per module that publishes status
  items, plus the rotation interval), UPDATES (the auto-update toggle,
  below), SYSTEM (info), and an
  auto-generated form page per module. These are the same groups the
  web UI shows under SETTINGS — one definition, two surfaces.
- **Themes** — design tokens only (`bg/fg/accent/dim/border`); every
  pixel comes from a theme. `auto` flips light/dark on the schedule.
- **Wake on touch** — after `idle_seconds` the panel really sleeps
  (display off + backlight off); any touch wakes it, and the waking
  tap never activates UI.
- **Web companion** — a REST server on :8080 plus one terminal-styled
  page: click into a module, edit its config (same schema as the touch
  form), trigger its actions. No live mirror, ~zero idle CPU.

## The Boston app

The BOSTON module draws the MBTA rapid-transit network — red, green,
orange and blue lines — from a graph file, every station a circle
button. Tap a station and a trip alert opens: *calculate trip from
[address] to [station]?* with a mode picker (transit/walk/bike/car,
defaulting to the settings value). The query for the default mode
starts immediately in the background; confirming without changing the
mode waits for it, changing the mode re-queries, cancel/X abandons.
While the [Google Maps Directions
API](https://developers.google.com/maps/documentation/directions)
answers, the alert shows "computing…", then the itineraries: one at a
time with `[<] [done] [>]` (grey and inert at the ends), legs in a
scrollable list, trips always leaving now. Every failure — unreachable
network, rejected key, unknown address, no route — lands in the same
alert as a descriptive message.

**Setup** (web UI → BOSTON → settings):

1. Create a [Google Cloud](https://console.cloud.google.com) project,
   enable the **Directions API**, create an API key, and paste it into
   the `api_key` field. Billing must be enabled (Google requires it
   even for the free tier); the monthly free credit is far more than a
   wall panel making a few queries a day will ever use. The key is
   stored in plaintext in the gitignored `config.local.json` (see step
   2), is never rendered back to the browser, and never appears on the
   panel.
2. Enter your address in the `address` field — it is sent to Google as
   free text, which geocodes it. The address and the key are both
   `"local"` fields: they are stored in the gitignored
   `config.local.json` next to the config, never in the committed
   `config.json`.
3. Pick the default travel `mode` (transit is the one the app is tuned
   for).

**The graph** — `src/wintermode/modules/boston/graph.json`:

```json
{"vertices": [{"id": "park_street", "name": "Park Street", "x": 0.5,
               "y": 0.44, "lat": 42.356395, "lon": -71.062424}],
 "edges": [{"a": "haymarket", "b": "north_station",
            "colors": ["green", "orange"]}]}
```

Vertices carry a display name, a normalized `x`/`y` position, and the
real `lat`/`lon` the trip query targets. Edges connect *adjacent*
stations (shared track, not transfer pairs) and carry the line colors
of every line running on that segment; a multi-color edge is drawn
wider, alternating the colors, one straight shot — today exactly one
segment qualifies, Haymarket–North Station. All 118 stations and 119
segments of the four lines came from the MBTA's published data (GTFS +
the official line articles); the schematic positions are a first cut.
The graph is a static data file, committed like the fonts.

## Adding a module

Drop a directory into `src/wintermode/modules/<id>/` with a `module.py`
defining a module-level `MODULE`:

```python
class MyModule:
    id = "mymodule"          # must match the directory name
    title = "MY MODULE"      # bar title + home card label
    interval = 0             # seconds between auto re-renders
    config_schema = {        # generates the settings page AND the web form
        "label": {"type": "text", "title": "Label", "default": ""},
    }
    actions = []             # web action buttons

    def render(self, draw, ctx) -> bool: ...     # draw inside ctx.content;
                                                 # True only if pixels changed
    def on_tap(self, x, y, ctx) -> bool: ...     # True = consumed
    def status_items(self, ctx) -> list[BarItem]: ...
    def on_action(self, action_id, ctx) -> None: ...  # runs on the main loop
```

Draw text with `ctx.fonts.draw_text(...)` (the 1-bit path) and colors
from `ctx.theme`. Only the main loop thread ever draws; background
threads fetch data only.

The config DSL: `bool` (toggle), `choice` (cycle), `int` (stepper),
`text` (web-editable, read-only on the panel), `time` (hour/minute
steppers). Optional `"title"`, `"help"`, and
`"visible_if": {"field": "theme", "equals": "auto"}` to show a field
only when another field holds a value. Two markers change where a field
lives: `"local": true` keeps it in the gitignored
`config.local.json` overlay instead of the tracked file, and
`"write_only": true` is for secrets — the value is stored, is never
rendered back (`GET` and `PUT` answer with an empty string and a
`masked` list naming the fields that are set), and the panel does not
edit it at all. Editing happens on the web page, or by hand in
`config.local.json`.

## On the Pi Zero W

Raspberry Pi OS Lite (Bookworm), headless — the service *is* the UI:

```bash
git clone https://github.com/DorneichI/winter-mode /opt/winter-mode
cd /opt/winter-mode
sudo chown -R winter: /opt/winter-mode   # the updater runs as winter and
                                         # must own the checkout to pull
python3 -m venv .venv
# binary wheels where possible (Pillow on armv6); the ertftm070 sdist
# compiles its C fast path — gcc must be installed.  Editable: the
# checkout IS the install, so a git pull is live without a reinstall.
.venv/bin/pip install --only-binary :all: --no-binary ertftm070 -e .
sudo mkdir -p /etc/wintermode && sudo chown winter: /etc/wintermode
sudo cp deploy/wintermode.service deploy/wintermode-update.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wintermode-update wintermode
```

The display turns on at boot, the web UI comes up with the network, and
`Restart=always` brings it back if it crashes. Config lives at
`/etc/wintermode/config.json` (self-healing: missing keys are filled
with defaults on load; hand-edits never crash it). Values a module
marks `"local": true` — addresses, API keys — live in a gitignored
`/etc/wintermode/config.local.json` overlay, so the tracked config
never carries secrets.

`/opt/winter-mode` is a deployment mirror, not a workspace: the updater
discards any local edits there (it logs what it discards). Change
things in your own clone and push.

## Automatic updates

On every boot, `wintermode-update.service` fetches and resets to
`origin/main` before the dashboard starts, and stamps the deployed
version (`git describe --tags --always`) next to the config — the boot
splash, SYSTEM → VERSION, and `GET /api/device` all show it. The repo
has no tags yet, so expect a bare short sha until you `git tag`
releases.

**On by default.** SETTINGS → UPDATES (on the panel or in the web UI)
toggles `auto_update`; off means the updater leaves the checkout alone
— flipping it off is the way to freeze the panel at the version it is
running.

**A bad update rolls back by itself.** After boot, a health check
pings `GET /api/device`; if the new commit never answers, the panel
resets to the last-known-good commit (resyncing the venv if
`pyproject.toml` changed in between) and reboots on the old code. The
failed commit is remembered and never re-applied until `main` moves
past it — one failed boot per bad commit, then the panel quietly stays
on the version that works. If the last-known-good itself turns out
broken, the pins clear and it needs a human.

State lives in `/etc/wintermode/update-state.json`; logs are in
`journalctl -u wintermode-update -u wintermode`. To retry a previously
failed commit by hand, delete that state file (or set the toggle off,
push the fix, and set it back on).

A periodic re-check instead of boot-only updates is a future
extension: a `wintermode-update.timer` that runs the update unit and
restarts the dashboard when the pull changed something.

## The web API

```
GET  /api/modules                  modules + schemas + actions
GET  /api/modules/{id}/config      schema + current values (+ masked list)
PUT  /api/modules/{id}/config      validate -> save -> the same answer (400 on garbage)
POST /api/modules/{id}/actions/{action}   enqueued, runs on the main loop
GET  /api/device                   theme, tokens, form groups, network
PUT  /api/device/{theme|display|statusbar|updates}
GET  /                               the page
GET  /font/{3270-Regular|3270SemiCondensed-Regular}.ttf
```

Both config directions blank a stored `write_only` value and name it in
`masked`, so a secret never travels back to the browser — reading the
page after a save is the same answer as loading it fresh.

## Development

```bash
.venv/bin/ruff check src tests deploy
.venv/bin/pytest -q
```

Tests fake the display and touch at the seams — no hardware anywhere.

## License

MIT © 2026 Immanuel Dorneich. The bundled IBM 3270 fonts are
BSD 3-clause (see `src/wintermode/fonts/LICENSE.txt`).
