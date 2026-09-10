# winter-mode

A HomePod-style kitchen dashboard for the ER-TFTM070-4 (7.0" TFT,
800×480) on a Raspberry Pi Zero W — built on the
[`ertftm070`](https://github.com/DorneichI/er-tftm070-4-driver) driver.

Terminal aesthetics (IBM 3270, hard 1-bit pixels, no grays), tap-only
navigation, a persistent status bar, auto-generated settings, and a
tiny web companion. Ships with three modules — clock, dummy, settings —
and a module contract that makes adding your own a one-file job.

> # ⚠️ THIS PROJECT IS COMPLETELY VIBECODED ⚠️
>
> **No human sat down and wrote this codebase. It was written by
> DeepSeek (the AI model, running in the Claude Code CLI) in a
> vibe-coding session, with a human in the loop whose job was watching
> the screen, describing what was wrong, and demanding better.**
>
> **The good part:** it genuinely works. Every feature was eye-tested
> by the human in the browser simulator, the 114-test suite passes,
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
  only. No gestures, no scrolling: lists and grids paginate.
- **Modules** — CLOCK (big ticking time), DUMMY (tap-to-bump counter,
  a web "Reset" action, a config schema demoing every DSL type), and
  SETTINGS (the hub).
- **Settings** — a card grid into every configurable thing: DISPLAY
  (theme dark/light/auto with the light-window schedule, always-on vs
  wake-on-touch), STATUS BAR (a toggle per module that publishes status
  items, plus the rotation interval), SYSTEM (info), and an
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
only when another field holds a value.

## On the Pi Zero W

Raspberry Pi OS Lite (Bookworm), headless — the service *is* the UI:

```bash
git clone https://github.com/DorneichI/winter-mode /opt/winter-mode
cd /opt/winter-mode
python3 -m venv .venv
# binary wheels where possible (Pillow on armv6); the ertftm070 sdist
# compiles its C fast path — gcc must be installed
.venv/bin/pip install --only-binary :all: --no-binary ertftm070 .
sudo mkdir -p /etc/wintermode && sudo chown winter: /etc/wintermode
sudo cp deploy/wintermode.service /etc/systemd/system/
sudo systemctl enable --now wintermode
```

The display turns on at boot, the web UI comes up with the network, and
`Restart=always` brings it back if it crashes. Config lives at
`/etc/wintermode/config.json` (self-healing: missing keys are filled
with defaults on load; hand-edits never crash it).

## The web API

```
GET  /api/modules                  modules + schemas + actions
GET  /api/modules/{id}/config      schema + current values
PUT  /api/modules/{id}/config      validate -> save -> values (400 on garbage)
POST /api/modules/{id}/actions/{action}   enqueued, runs on the main loop
GET  /api/device                   theme, tokens, form groups, network
PUT  /api/device/{theme|display|statusbar}
GET  /                               the page
GET  /font/{3270-Regular|3270SemiCondensed-Regular}.ttf
```

## Development

```bash
.venv/bin/ruff check src tests
.venv/bin/pytest -q
```

Tests fake the display and touch at the seams — no hardware anywhere.

## License

MIT © 2026 Immanuel Dorneich. The bundled IBM 3270 fonts are
BSD 3-clause (see `src/wintermode/fonts/LICENSE.txt`).
