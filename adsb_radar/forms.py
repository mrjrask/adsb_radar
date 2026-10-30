"""Settings forms and visibility dome adapted from adsb-i75w.

HTTP handling and atomic storage live in web.py and config.py.
"""
import os
from pathlib import Path

SECTORS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
SECTIONS = (('Display settings',
  (('IDLE',
    'Idle boards',
    'idles',
    (('default', 'Use defaults'),
     ('clock', 'Clock'),
     ('radar', 'Radar'),
     ('message', 'Clear skies message'),
     ('blank', 'Dark')),
    'Tick one, or several to take turns. None ticked: the default radar.'),
   ('IDLE_SECONDS',
    'Seconds per idle board',
    'number',
    (5, 3600),
    'With several idle boards ticked, how long each shows.'),
   ('RADAR_RANGE',
    'Radar outer-ring range',
    'number',
    (1, 250),
    'In the configured distance unit. The outer ring is at least the flight radius. Blank uses the configured '
    'range, else 4 × radius.'),
   ('RADAR_SWEEP',
    'Radar sweep',
    'choice',
    (('on', 'On', True), ('off', 'Off', False)),
    'Turn the rotating beam on or off.'),
   ('RADAR_TRAIL',
    'Radar trail length',
    'number',
    (0, 16),
    'Trail length in steps of four pixels at 1080p; 0 for none.'),
   ('RADAR_MOTION',
    'Radar planes move',
    'choice',
    (('on', 'Move between checks', True), ('off', 'Only at each check', False)),
    'Planes glide along their track between checks. Unset in config.json: the default is on.'),
   ('RADAR_LIGHTS',
    'Radar plane lights',
    'choice',
    (('on', 'Blinking', True), ('off', 'Off', False)),
    'Red and green wingtip navigation lights, a white tail light, white double-flash strobes and a red beacon '
    'on each plane. Unset in config.json: the default is on.'),
   ('CLOCK_24H', 'Clock', 'choice', (('12', '12-hour', False), ('24', '24-hour', True)), ''))),
 ('Radar colors',
  (('RADAR_BACKGROUND',
    'Radar background',
    'hex',
    None,
    'Six hex digits, e.g. #00FF80. Blank restores the inherited color.'),
   ('RADAR_SWEEP_COLOR',
    'Sweep color',
    'hex',
    None,
    'Six hex digits, e.g. #00FF80. Blank restores the inherited color.'),
   ('RADAR_RING', 'Outer ring', 'hex', None, 'Six hex digits, e.g. #00FF80. Blank restores the inherited color.'),
   ('RADAR_RING_DIM',
    'Intermediate ring',
    'hex',
    None,
    'Six hex digits, e.g. #00FF80. Blank restores the inherited color.'),
   ('RADAR_HOME_RING',
    'Flight radius ring',
    'hex',
    None,
    'Six hex digits, e.g. #00FF80. Blank restores the inherited color.'),
   ('RADAR_NORTH',
    'North indicator',
    'hex',
    None,
    'Six hex digits, e.g. #00FF80. Blank restores the inherited color.'),
   ('RADAR_COUNT',
    'Aircraft count',
    'hex',
    None,
    'Six hex digits, e.g. #00FF80. Blank restores the inherited color.'),
   ('RADAR_RANGE_COLOR',
    'Outer-ring distance label',
    'hex',
    None,
    'Six hex digits, e.g. #00FF80. Blank restores the inherited color.'),
   ('RADAR_ALT_1',
    'Altitude: below 4,000 ft',
    'hex',
    None,
    'Six hex digits, e.g. #00FF80. Blank restores the inherited color.'),
   ('RADAR_ALT_2',
    'Altitude: 4,000–9,999 ft',
    'hex',
    None,
    'Six hex digits, e.g. #00FF80. Blank restores the inherited color.'),
   ('RADAR_ALT_3',
    'Altitude: 10,000–19,999 ft',
    'hex',
    None,
    'Six hex digits, e.g. #00FF80. Blank restores the inherited color.'),
   ('RADAR_ALT_4',
    'Altitude: 20,000–29,999 ft',
    'hex',
    None,
    'Six hex digits, e.g. #00FF80. Blank restores the inherited color.'),
   ('RADAR_ALT_5',
    'Altitude: 30,000 ft and above',
    'hex',
    None,
    'Six hex digits, e.g. #00FF80. Blank restores the inherited color.'))),
 ('Visibility cone',
  (('MIN_ELEVATION',
    'Elevation cutoff',
    'number',
    (0, 89),
    'Degrees above the horizon a plane must be. Setting it (or a direction below) turns the cone on.'),
   ('HORIZON',
    'Cutoff by direction',
    'horizon',
    None,
    'Degrees, for directions where the trees or roof are taller. Blank directions use the cutoff above.'),
   ('HOME_ELEVATION_FT', 'Home elevation (ft)', 'number', (-1500, 15000), 'Ground elevation above sea level.'),
   ('MAX_RANGE',
    'Max range',
    'number',
    (0.1, 100),
    'Farthest a plane can be, in a straight line, and still show (eyesight).'))),
 ('Range and location',
  (('RADIUS',
    'Radius',
    'number',
    (0.1, 100),
    "How near a plane must be, along the ground, to show (the radar's amber ring); the cone filters within it."),
   ('LATITUDE', 'Latitude', 'number', (-90, 90), 'Where overhead is. Set both, or neither.'),
   ('LONGITUDE', 'Longitude', 'number', (-180, 180), ''))),
 ('Brightness',
  (('BRIGHTNESS',
    'Brightness',
    'brightness',
    None,
    'Dims the rendered image; the monitor backlight stays unchanged.'),)),
 ('Polling', (('POLL_SECONDS', 'Seconds between checks', 'number', (2, 30), ''),)),
 ('HDMI output',
  (('RESOLUTION',
    'Output resolution',
    'choice',
    (('auto', 'Automatic (native HDMI mode)', 'auto'),
     ('4k', '4K — 3840 × 2160', '4k'),
     ('1080p', '1080p — 1920 × 1080', '1080p'),
     ('848x480', 'Projector — 848 × 480', '848x480')),
    'Renders at the selected native resolution. The connected display must advertise that HDMI mode.'),)))


RADAR_COLOR_DEFAULTS = {'RADAR_BACKGROUND': '#001400',
 'RADAR_SWEEP_COLOR': '#00FF00',
 'RADAR_RING': '#007800',
 'RADAR_RING_DIM': '#003C00',
 'RADAR_HOME_RING': '#FFA000',
 'RADAR_NORTH': '#00FFFF',
 'RADAR_COUNT': '#FFFFFF',
 'RADAR_RANGE_COLOR': '#007800',
 'RADAR_ALT_1': '#FF0000',
 'RADAR_ALT_2': '#FFA000',
 'RADAR_ALT_3': '#FFFF00',
 'RADAR_ALT_4': '#00FFFF',
 'RADAR_ALT_5': '#FF00FF'}


BUILTIN_PRESETS = {'Daytime': {'RADAR_BACKGROUND': '#001400',
             'RADAR_SWEEP_COLOR': '#00FF00',
             'RADAR_RING': '#007800',
             'RADAR_RING_DIM': '#003C00',
             'RADAR_HOME_RING': '#FFA000',
             'RADAR_NORTH': '#00FFFF',
             'RADAR_COUNT': '#FFFFFF',
             'RADAR_RANGE_COLOR': '#007800',
             'RADAR_ALT_1': '#FF0000',
             'RADAR_ALT_2': '#FFA000',
             'RADAR_ALT_3': '#FFFF00',
             'RADAR_ALT_4': '#00FFFF',
             'RADAR_ALT_5': '#FF00FF'},
 'Night': {'RADAR_BACKGROUND': '#000000',
           'RADAR_SWEEP_COLOR': '#FF0000',
           'RADAR_RING': '#780000',
           'RADAR_RING_DIM': '#3C0000',
           'RADAR_HOME_RING': '#FFA000',
           'RADAR_NORTH': '#00FFFF',
           'RADAR_COUNT': '#FFFFFF',
           'RADAR_RANGE_COLOR': '#780000',
           'RADAR_ALT_1': '#FF0000',
           'RADAR_ALT_2': '#FFA000',
           'RADAR_ALT_3': '#FFFF00',
           'RADAR_ALT_4': '#00FFFF',
           'RADAR_ALT_5': '#FF00FF'}}

DISPLAY_DEFAULTS = {'RADIUS': 3,
 'HOME_ELEVATION_FT': 0,
 'MAX_RANGE': 10,
 'IDLE': 'radar',
 'IDLE_SECONDS': 30,
 'RADAR_TRAIL': 6,
 'RADAR_MOTION': True,
 'RADAR_LIGHTS': True,
 'RADAR_SWEEP': True,
 'CLOCK_24H': False,
 'BRIGHTNESS': 1.0,
 'POLL_SECONDS': 5}

FIELDS = {field[0]: field for _title, fields in SECTIONS for field in fields}


def _number(text, low, high):
    value = float(text)
    if value != value or value < low or value > high:  # NaN, or out of range
        raise ValueError
    return int(value) if value == int(value) and abs(value) < 1e9 else value


def validate(form, brightness_choices=()):
    """(overrides, errors) from a submitted settings form; a blank field means "use config.json"."""

    overrides = {}
    errors = {}
    for key, (_key, label, kind, spec, _help) in FIELDS.items():
        if kind == "horizon":
            cutoffs = {}
            for sector in SECTORS:
                text = form.get("H_" + sector, "").strip()
                if text:
                    try:
                        cutoffs[sector] = _number(text, 0, 89)
                    except ValueError:
                        errors["H_" + sector] = sector + ": a number from 0 to 89"
            if cutoffs:
                overrides[key] = cutoffs
            continue
        if kind == "idles":
            ticked = [name for name, _label in spec if form.get(key + "_" + name)]
            if "default" in ticked:
                overrides[key] = None  # inherit config.json
            elif ticked:
                overrides[key] = ",".join(ticked)
            continue
        text = (RADAR_COLOR_DEFAULTS[key] if kind == "hex" and form.get("radar_defaults") == "1"
                else form.get(key, "").strip())
        if kind == "hex" and form.get("radar_defaults") != "1" and text == form.get("inherit_" + key):
            continue  # prefilled inherited colors do not become overrides on an unrelated save
        if not text:
            continue
        if kind == "hex":
            color = text[1:] if text.startswith("#") else text
            if len(color) != 6 or any(c not in "0123456789abcdefABCDEF" for c in color):
                errors[key] = label + ": enter six hex digits (#RRGGBB)"
            else:
                overrides[key] = "#" + color.upper()
        elif kind == "number":
            try:
                overrides[key] = _number(text, spec[0], spec[1])
            except ValueError:
                errors[key] = "{}: a number from {:g} to {:g}".format(label, spec[0], spec[1])
        elif kind == "choice":
            for value, _label, stored in spec:
                if value == text:
                    overrides[key] = stored
                    break
            else:
                errors[key] = label + ": not one of the choices"
        elif kind == "brightness":
            try:
                overrides[key] = _number(text, 0.001, 1)
            except ValueError:
                errors[key] = label + ": not one of the choices"
    if ("LATITUDE" in overrides) != ("LONGITUDE" in overrides):
        errors["LATITUDE"] = "Set both latitude and longitude, or neither"
    return overrides, errors


# ── Effective display settings ─────────────────────────────────────────────



def horizon_dict(text):
    """"N45,NW40" as {"N": 45.0, "NW": 40.0}; entries it cannot read are left out."""

    cutoffs = {}
    for entry in str(text or "").replace(" ", "").upper().split(","):
        name = entry.rstrip("0123456789.")
        if name in SECTORS and name != entry:
            try:
                cutoffs[name] = float(entry[len(name):])
            except ValueError:
                pass
    return cutoffs


def in_effect(effective):
    """One line on the cone the renderer is drawing with, for the top of the cone section."""

    if not effective:
        return ("Values in effect are available after the renderer starts. "
                "Reload this page to refresh.")
    unit = effective.get("unit", "")
    parts = []
    if effective.get("MIN_ELEVATION") is None and not effective.get("HORIZON"):
        parts.append("cone off, radius {} {}".format(shown(effective.get("RADIUS")), unit))
    else:
        parts.append("cutoff {}\u00b0".format(shown(effective.get("MIN_ELEVATION") or 0)))
        horizon = effective.get("HORIZON") or {}
        parts.extend("{} {}\u00b0".format(name, shown(horizon[name])) for name in SECTORS if name in horizon)
        parts.append("home {} ft".format(shown(effective.get("HOME_ELEVATION_FT") or 0)))
        parts.append("max range {} {}".format(shown(effective.get("MAX_RANGE")), unit))
    return "In effect now (current display settings): " + ", ".join(parts) + "."


# ── Page ───────────────────────────────────────────────────────────────────


def escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def shown(value):
    """A setting as the page shows it."""

    if value is None:
        return "default"
    if value is True:
        return "on"
    if value is False:
        return "off"
    if isinstance(value, float):
        return "{:g}".format(value)
    if isinstance(value, dict):
        return ",".join("{}{}".format(k, shown(v)) for k, v in value.items())
    return str(value)


# The page's big fixed pieces, the CSS and the sky dome's JavaScript, live in
# admin.css and admin.js on the board and are read from flash a slice at a time
# as they are sent (Asset), so they never take up the heap. The heap is small
# and broken up: a page joined into one string (17 KB with the side view) failed
# with MemoryError. Keep every piece of a page small (tests check it). Without
# the two files the page still works, unstyled and without the pictures.


class Asset:
    """A body piece that send() streams from a board file instead of holding it in RAM."""

    def __init__(self, path):
        self.path = path

    def size(self):
        try:
            return os.stat(self.path)[6]
        except OSError:
            return 0

    def read(self):
        """The whole file: for tests (Response.body); send() never calls it."""

        try:
            with open(self.path, "rb") as f:
                return f.read()
        except OSError:
            return b""


STYLE = Asset(str(Path(__file__).parent / "static" / "admin.css"))
DOME_JS = Asset(str(Path(__file__).parent / "static" / "admin.js"))

# The sky dome and side view: the cone's cutoffs as pictures. They read and write
# the number fields, which stay the source of truth (and work without JavaScript).
DOME = (
    b"<div id=domebox hidden><svg id=dome viewBox='0 0 240 240' role=img aria-label='Sky dome'></svg>"
    b"<label for=minr>Cutoff for directions you have not dragged: <b id=minv></b></label>"
    b"<input type=range id=minr min=0 max=89 step=1>"
    b"<small>Looking straight up: the middle is overhead, the edge the horizon, north at the top. "
    b"Drag a dot toward the middle where trees or the roof hide the sky; planes inside the green show. "
    b"Grey dots follow the cutoff above.</small>"
    b"<button type=button class=plain id=clr>Clear directions</button>"
    b"<label>Side view</label><div class=grid id=axes></div>"
    b"<svg id=side viewBox='0 0 240 154' role=img aria-label='Side view'></svg><small id=sidet></small>"
    b"<label for=unit>Distance unit (the configured distance unit)</label><select id=unit>"
    b"<option value=6076.12>nm</option><option value=5280>mi</option><option value=3280.84>km</option></select>"
    b"<small>A slice through home along the line picked above (the dashed line on the dome), drawn to scale: "
    b"the ground at your home elevation, the dashed arc at max range. Planes in the green fan show. "
    b"Drag an end dot to change that direction's cutoff. Heights are feet above sea level.</small></div>"
)


def _field(key, label, kind, spec, help_text, values, defaults, errors, brightness_choices, effective=None):
    """One setting's inputs. Blank inputs show, greyed, what applies instead:
    config.json's value, else what the renderer last reported drawing with
    (*effective*), so the fields and the dome show the values really in effect."""

    parts = []
    effective = effective or {}
    default = defaults.get(key)
    source = "config.json"
    if default is None and key in effective:
        default, source = effective[key], "in effect"
    elif default is None and key in DISPLAY_DEFAULTS:
        default, source = DISPLAY_DEFAULTS[key], "default"
    if key == "RADAR_RANGE" and default is None:
        radius = values.get("RADIUS", defaults.get("RADIUS"))
        if radius is None:
            radius = effective.get("RADIUS", DISPLAY_DEFAULTS["RADIUS"])
        default, source = 4 * radius, "default"
    if kind == "horizon":
        parts.append("<label>{}</label><div class=grid>".format(escape(label)))
        current = values.get(key) or {}
        default = defaults.get(key) or {}
        if isinstance(default, str):  # config.json may give "N45,NE40"
            default = horizon_dict(default)
        if not default:  # config.json sends none: the renderer's HORIZON applies
            default = effective.get(key) or {}
        if current:  # a saved HORIZON replaces the inherited one whole: blank directions use the cutoff
            default = {}
        for sector in SECTORS:
            text = current.get(sector, "") if isinstance(current, dict) else ""
            hint = default.get(sector, "") if isinstance(default, dict) else ""
            parts.append('<input name="H_{0}" value="{1}" placeholder="{0} {2}" inputmode=decimal '
                         'aria-label="{0}">'.format(sector, escape(shown(text) if text != "" else ""),
                                                    escape(shown(hint) if hint != "" else "")))
        parts.append("</div>")
        for sector in SECTORS:
            if "H_" + sector in errors:
                parts.append('<small class=err>{}</small>'.format(escape(errors["H_" + sector])))
    elif kind == "idles":
        current = values.get(key)
        if key in values and current is None:
            ticked = ["default"]
        else:
            ticked = [name.strip() for name in current.split(",")] if isinstance(current, str) else []
        parts.append("<label>{}</label>".format(escape(label)))
        for name, option_label in spec:
            parts.append('<label style="display:inline-block;margin-right:14px"><input type=checkbox '
                         'name="{}_{}" value=1 style="width:auto"{}> {}</label>'.format(
                             key, name, " checked" if name in ticked else "", escape(option_label)))
        parts.append("<small>{}: {}</small>".format(source, escape(shown(default))))
    elif kind in ("choice", "brightness"):
        options = spec if kind == "choice" else [
            (shown(choice), "{:g}%".format(choice * 100), choice)
            for choice in brightness_choices]
        default_label = shown(default)
        for _value, option_label, stored in options:
            if stored == default:
                default_label = option_label
        parts.append('<label for="{0}">{1}</label><select id="{0}" name="{0}">'.format(key, escape(label)))
        parts.append('<option value="">{} ({})</option>'.format(source, escape(default_label)))
        current = values.get(key, "unset")
        for value, option_label, stored in options:
            selected = " selected" if key in values and stored == current else ""
            parts.append('<option value="{}"{}>{}</option>'.format(escape(value), selected, escape(option_label)))
        parts.append("</select>")
    elif kind == "hex":
        default = defaults.get(key) or effective.get(key) or RADAR_COLOR_DEFAULTS[key]
        if key not in values:
            parts.append('<input type=hidden name="inherit_{}" value="{}">'.format(key, escape(default)))
        parts.append('<label for="{0}">{1}</label><div class=color-row><input id="{0}" name="{0}" '
                     'value="{2}" placeholder="{3}" pattern="#[0-9a-fA-F]{{6}}|[0-9a-fA-F]{{6}}" '
                     'maxlength=7 spellcheck=false aria-describedby="{0}_hint">'
                     '<button>Apply</button></div><small id="{0}_hint">Applies all changes on this page.</small>'
                     .format(
                         key, escape(label), escape(values.get(key, default)), escape(default)))
    else:
        text = values.get(key, "")
        hint = source + ": " + ("off" if source == "in effect" and default is None else shown(default))
        parts.append('<label for="{0}">{1}</label><input id="{0}" name="{0}" value="{2}" '
                     'placeholder="{3}" inputmode=decimal>'.format(
                         key, escape(label), escape(shown(text) if text != "" else ""), escape(hint)))
    if help_text:
        parts.append("<small>{}</small>".format(escape(help_text)))
    if key in errors:
        parts.append('<small class=err>{}</small>'.format(escape(errors[key])))
    return "".join(parts)


def table(rows):
    return "<table>" + "".join("<tr><td>{}</td><td>{}</td></tr>".format(escape(label), escape(value))
                               for label, value in rows) + "</table>"


def page(values, defaults, status, csrf, message="", errors=None, brightness_choices=(),
         diagnostics=(), effective=None, presets=None):
    """The admin page as a list of pieces (str and bytes), never one string.

    *values*: the saved (or just submitted) overrides; *defaults*: config.json's;
    *effective*: the renderer's effective settings.
    """

    errors = errors or {}
    out = ["<!doctype html><html><head><meta charset=utf-8>",
           "<meta name=viewport content='width=device-width,initial-scale=1'>",
           "<title>Flight board</title><style>", STYLE, "</style></head><body><main>",
           "<header><p class=eyebrow>RASPBERRY PI · HDMI</p><h1>Flight board</h1>"
           "<p>Make the display your own.</p></header>"
           "<nav aria-label='Page sections'><a href='#settings'>Display settings</a>"
           "<a href='#colors'>Radar colors</a><a href='#visibility'>Visibility</a>"
           "<a href='#board'>Board &amp; status</a></nav>"]
    if message:
        out.append("<p class=note>{}</p>".format(escape(message)))
    if errors:
        out.append("<p class=err>Not saved: fix the fields marked below.</p>")
    out.append('<form method=post action="/settings"><input type=hidden name=csrf value="{}">'.format(csrf))
    for index, (title, fields) in enumerate(SECTIONS):
        anchor = ("settings", "colors", "visibility")[index] if index < 3 else "section" + str(index)
        out.append('<section id="{}"><h2>{}</h2>'.format(anchor, escape(title)))
        if title == "Radar colors":
            out.append('<p>Apply a saved palette with one button. Only radar colors change.</p>')
            for name in (presets or BUILTIN_PRESETS):
                out.append('<button formaction="/presets" formnovalidate name=preset_apply value="{}">{}</button>'
                           .format(escape(name), escape(name)))
            out.append('<label for=preset_source>Saved palette</label><select id=preset_source name=preset_source>')
            for name in (presets or BUILTIN_PRESETS):
                out.append('<option value="{}">{}</option>'.format(escape(name), escape(name)))
            out.append('</select><label for=preset_name>New palette name</label>'
                       '<input id=preset_name name=preset_name maxlength=40 placeholder="e.g. Nighttime">'
                       '<button formaction="/presets" formnovalidate name=preset_action value=save>'
                       'Save current colors</button>'
                       '<button formaction="/presets" formnovalidate name=preset_action value=rename>Rename</button>'
                       '<button formaction="/presets" formnovalidate name=preset_action value=duplicate>'
                       'Duplicate</button>'
                       '<small>Save captures the color fields below. Rename and Duplicate use the selected palette. '
                       'Daytime and Night are permanent. Up to 20 custom palettes.</small>'
                       '<button name=radar_defaults value=1>Default colors</button>'
                       '<small>Restore the original radar palette and apply all changes on this page.</small>')
        if index == 0:
            out.append("<p class=muted>Choose what appears when no aircraft is overhead. "
                       "Blank fields keep inherited settings.</p>")
            reach = (effective or {}).get("RADAR_RANGE")
            reach_text = (shown(reach) + " " + (effective or {}).get("unit", "")
                          if reach is not None else "not available yet")
            out.append("<p class=note>Effective outer-ring range: {}. "
                       "Values update after the next check.</p>".format(escape(reach_text)))
        if any(field[2] == "horizon" for field in fields):  # the cone: say what is in effect first
            out.append("<p class=note>{}</p><input type=hidden id=srvunit value=\"{}\">".format(
                escape(in_effect(effective)), escape((effective or {}).get("unit", ""))))
        for field in fields:
            if field[2] == "horizon":
                out.append(DOME)
            out.append('<div class=field>')
            out.append(_field(*field, values, defaults, errors, brightness_choices, effective))
            out.append('</div>')
        out.append('</section>')
    out.append("<div class=savebar><button>Save all settings</button>"
               "<small>Changes take effect on the next check.</small></div></form>")
    out.append("<section id=board><h2>Board &amp; status</h2>")
    out.append(table(status))
    for action, label, confirm in (
        ("reset", "Reset to config.json", "Clear every setting saved here?"),

        ("logout", "Log out", "Log out of this browser?"),
    ):
        out.append('<form class=inline method=post action="/{}" onsubmit="return confirm(\'{}\')">'
                   '<input type=hidden name=csrf value="{}"><button class=plain>{}</button></form>'
                   .format(action, escape(confirm), csrf, escape(label)))
    out.append("<small>Updates: pull the repository, then run sudo ./install.sh.</small>")
    if diagnostics:
        out.append("<h2>Diagnostics</h2>")
        out.append(table(diagnostics))
        out.append("<small>The same as JSON: <a style='color:#fc6' href='/status.json'>/status.json</a>. "
                   "Reload the page to refresh.</small>")
    out += ["</section></main><script>", DOME_JS, "</script></body></html>"]
    return out


def login_page(error=""):
    """The user name and password form a browser sees before it has logged in."""

    return ["<!doctype html><html><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'><title>Flight board</title>"
            "<style>", STYLE, "</style></head><body><main><h1>Flight board</h1>"
            + ("<p class=err>{}</p>".format(escape(error)) if error else "")
            + '<form method=post action="/login"><label for=username>User name</label>'
            '<input id=username name=username autocomplete=username autocapitalize=none autofocus>'
            '<label for=password>Password</label>'
            '<input id=password name=password type=password autocomplete=current-password>'
            "<button>Log in</button></form></main></body></html>"]
