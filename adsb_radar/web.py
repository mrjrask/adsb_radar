"""Authenticated admin page, independent of the HDMI renderer."""

import fcntl
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, request, send_file, session
from werkzeug.security import check_password_hash

from . import __version__, forms, missing_imagery
from .config import CONFIG_PATH, STATE_PATH, check_settings, load_config, read_json, write_json


@contextmanager
def locked(state):
    state.mkdir(parents=True, exist_ok=True)
    with (state / ".admin.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def pieces(parts):
    return b"".join(part.read() if isinstance(part, forms.Asset) else part.encode() if isinstance(part, str)
                    else part for part in parts)


def load_presets(path):
    presets = {name: dict(colors) for name, colors in forms.BUILTIN_PRESETS.items()}
    for name, colors in read_json(path).items():
        if name in presets or not isinstance(name, str) or not 1 <= len(name) <= 40:
            continue
        if not isinstance(colors, dict) or set(colors) != set(forms.RADAR_COLOR_DEFAULTS):
            continue
        try:
            check_settings(colors)
        except ValueError:
            continue
        presets[name] = colors
        if len(presets) >= 22:
            break
    return presets


def create_app(config_path=CONFIG_PATH, state_path=STATE_PATH, config=None):
    config = config or load_config(config_path)
    state = Path(state_path)
    app = Flask(__name__)
    app.config.update(SECRET_KEY=config["SECRET_KEY"], MAX_CONTENT_LENGTH=16384,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=12))
    attempts = {}
    attempts_lock = threading.Lock()

    def csrf():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(24)
        return session["csrf"]

    @app.before_request
    def protect():
        if request.path == "/healthz" and request.method == "GET":
            return None
        if request.path != "/login" and not session.get("authenticated"):
            if request.path in ("/status.json", "/preview.png", "/missing-imagery.log"):
                abort(401)
            return redirect("/login", code=303)
        if request.method == "POST" and not secrets.compare_digest(request.form.get("csrf", "").encode(), csrf().encode()):
            abort(403)

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.get("/healthz")
    def health():
        return jsonify(service="adsb-radar-admin", version=__version__)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        if request.method == "POST":
            address, now = request.remote_addr, time.monotonic()
            with attempts_lock:
                for key in list(attempts):
                    attempts[key] = [t for t in attempts[key] if now - t < 60]
                    if not attempts[key]:
                        del attempts[key]
                times = attempts.setdefault(address, [])
                if len(times) >= 5 or len(attempts) > 1024:
                    abort(429)
                times.append(now)
            if (secrets.compare_digest(request.form.get("username", "").encode(), config["ADMIN_USERNAME"].encode())
                    and check_password_hash(config["ADMIN_PASSWORD_HASH"], request.form.get("password", ""))):
                session.clear()
                session["authenticated"] = True
                session.permanent = True
                csrf()
                return redirect("/", code=303)
            error = "Incorrect user name or password."
        body = pieces(forms.login_page(error)).replace(
            b'<form method=post action="/login">',
            ('<form method=post action="/login"><input type=hidden name=csrf value="' + csrf() + '">').encode())
        return Response(body, content_type="text/html; charset=utf-8")

    def status():
        result = read_json(state / "status.json")
        age = time.time() - result.get("heartbeat", 0)
        return {**result, "renderer_alive": 0 <= age < 10 and result.get("state") != "stopped",
                "heartbeat_age_seconds": round(age) if result else None}

    def page(message="", errors=None, values=None, code=200):
        saved = check_settings(read_json(state / "settings.json")) if values is None else values
        diagnostics = status()
        parts = forms.page(saved, config, [
            ("Version", __version__), ("Renderer", diagnostics.get("state", "not started")),
            ("Renderer alive", diagnostics["renderer_alive"]), ("Render size", str(diagnostics.get("render_size", "unknown"))),
            ("HDMI output", str(diagnostics.get("hdmi_size", "unknown"))),
            ("Aircraft feed(s)", ", ".join(config["RECEIVER_URLS"])),
        ], csrf(), message=message, errors=errors, brightness_choices=(1.0, 0.75, 0.5, 0.35, 0.1, 0.02),
            effective=diagnostics.get("effective", {}),
            diagnostics=[(key, str(value)) for key, value in diagnostics.items()],
            presets=load_presets(state / "presets.json"))
        body = pieces(parts).replace(b"<section id=board>",
                                    b'<section><h2>Live preview</h2><img src="/preview.png" '
                                    b'alt="Current display; reload to refresh" '
                                    b'style="width:100%;image-rendering:auto"><p><a href="/missing-imagery.log">'
                                    b'Missing airline logos and aircraft illustrations</a> (tab-separated)</p>'
                                    b'</section><section id=board>')
        return Response(body, status=code, content_type="text/html; charset=utf-8")

    @app.get("/")
    def index():
        return page(message=request.args.get("message", "")[:200])

    @app.post("/settings")
    def settings():
        values, errors = forms.validate(request.form)
        if not errors:
            try:
                check_settings({**{k: v for k, v in config.items() if k in forms.FIELDS}, **values})
            except ValueError as error:
                errors["LATITUDE"] = str(error)
        if errors:
            return page(errors=errors, values=values, code=400)
        with locked(state):
            write_json(state / "settings.json", values)
        return redirect("/?message=Settings+saved", code=303)

    @app.post("/reset")
    def reset():
        with locked(state):
            write_json(state / "settings.json", {})
        return redirect("/?message=Settings+reset;+config.json+applies", code=303)

    @app.post("/presets")
    def presets():
        with locked(state):
            palettes = load_presets(state / "presets.json")
            if "preset_apply" in request.form:
                name = request.form["preset_apply"]
                if name not in palettes:
                    abort(400, "Unknown palette")
                values = check_settings(read_json(state / "settings.json"))
                write_json(state / "settings.json", {**values, **palettes[name]})
            else:
                name = request.form.get("preset_name", "").strip()
                source = request.form.get("preset_source", "")
                action = request.form.get("preset_action", "")
                if not 1 <= len(name) <= 40 or name in palettes or any(ord(c) < 32 for c in name):
                    abort(400, "Choose a unique palette name (1-40 characters)")
                if len(palettes) >= 22 and action != "rename":
                    abort(400, "At most 20 custom palettes")
                if action == "save":
                    colors = {key: request.form.get(key, "") for key in forms.RADAR_COLOR_DEFAULTS}
                    values, errors = forms.validate(colors)
                    if errors or set(values) != set(colors):
                        abort(400, "Enter all 13 valid colors before saving a palette")
                    palettes[name] = values
                elif action in ("rename", "duplicate") and source in palettes:
                    if action == "rename" and source in forms.BUILTIN_PRESETS:
                        abort(400, "Built-in palettes are permanent; duplicate them instead")
                    palettes[name] = dict(palettes[source])
                    if action == "rename":
                        del palettes[source]
                else:
                    abort(400, "Unknown palette operation")
                write_json(state / "presets.json", {k: v for k, v in palettes.items() if k not in forms.BUILTIN_PRESETS})
        return redirect("/?message=Palette+updated", code=303)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect("/login", code=303)

    @app.get("/status.json")
    def status_json():
        return jsonify(status())

    @app.get("/preview.png")
    def preview():
        path = state / "preview.png"
        if not path.is_file():
            abort(404, "Renderer has not produced a preview yet; check its service logs")
        return send_file(path, mimetype="image/png", max_age=0)

    @app.get("/missing-imagery.log")
    def missing_imagery_log():
        path = state / missing_imagery.FILENAME
        if not path.is_file():
            return Response("Nothing missing yet: every flight shown had its logo and illustration.\n",
                            content_type="text/plain; charset=utf-8")
        return send_file(path, mimetype="text/plain", max_age=0, download_name=missing_imagery.FILENAME)

    return app
