#!/usr/bin/env python3
"""Create or validate the installer's private config; never print its secrets."""

import argparse
import getpass
import json
import secrets
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adsb_radar.config import DEFAULTS, load_config, read_json, write_json  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--seed", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--reset-password", action="store_true")
    args = parser.parse_args()
    if args.check:
        load_config(args.destination)
        print("Configuration is valid.")
        return
    if args.destination.exists() and not args.reset_password:
        load_config(args.destination)
        print("Keeping existing configuration and admin credentials.")
        return
    value = {**DEFAULTS, **read_json(args.destination if args.reset_password else args.seed)} if (
        args.reset_password or args.seed) else dict(DEFAULTS)
    if not args.seed and not args.reset_password:
        if not sys.stdin.isatty():
            parser.error("First install needs a terminal or --config FILE with preseeded settings")
        value["RECEIVER_URLS"] = [url.strip() for url in input(
            "ADS-B receiver URL(s), comma separated (e.g. http://192.168.1.50): ").split(",") if url.strip()]
        value["LATITUDE"] = float(input("Display latitude: "))
        value["LONGITUDE"] = float(input("Display longitude: "))
        value["RESOLUTION"] = input("HDMI resolution [auto/4k/1080p/848x480] (auto): ").strip().lower() or "auto"
    password = value.pop("ADMIN_PASSWORD", None)
    generated = False
    if args.reset_password or not value.get("ADMIN_PASSWORD_HASH"):
        if password is None and sys.stdin.isatty():
            password = getpass.getpass("Admin password (12+ characters; blank to generate): ")
            if password and password != getpass.getpass("Repeat admin password: "):
                raise ValueError("Passwords do not match")
        if not password:
            password, generated = secrets.token_urlsafe(18), True
        if not isinstance(password, str) or len(password) < 12:
            raise ValueError("Admin password must contain at least 12 characters")
        value["ADMIN_PASSWORD_HASH"] = generate_password_hash(password)
    value["SECRET_KEY"] = secrets.token_hex(32) if args.reset_password else value.get("SECRET_KEY") or secrets.token_hex(32)
    # Validate before replacing an existing private config.
    temporary = args.destination.with_suffix(".check.json")
    try:
        write_json(temporary, value)
        load_config(temporary)
        write_json(args.destination, value)
    finally:
        temporary.unlink(missing_ok=True)
    print("Configuration saved. Admin user: " + value["ADMIN_USERNAME"])
    if generated:
        print("Generated admin password (save this now): " + password)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from None
