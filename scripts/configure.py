#!/usr/bin/env python3
"""Create or validate the installer's private config; never print its secrets."""

import argparse
import getpass
import json
import os
import secrets
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adsb_radar.config import DEFAULTS, load_config, read_json, tar1090_address, write_json  # noqa: E402


def prompt_feed():
    source = input("Feed source [tar1090/receivers] (tar1090): ").strip().lower() or "tar1090"
    if source == "tar1090":
        address = input("Combined tar1090 hostname or map address (e.g. cm5:8080): ")
        return [tar1090_address(address)]
    if source == "receivers":
        return [url.strip() for url in input(
            "Receiver URL(s), comma separated (e.g. http://192.168.1.50): ").split(",") if url.strip()]
    raise ValueError("Feed source must be tar1090 or receivers")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--seed", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--reset-password", action="store_true")
    parser.add_argument("--tar1090", metavar="ADDRESS", help="use one combined tar1090 host/map instead of individual receivers")
    args = parser.parse_args()
    if args.check:
        load_config(args.destination)
        print("Configuration is valid.")
        return
    if args.destination.exists() and not args.reset_password and args.tar1090 is None:
        load_config(args.destination)
        print("Keeping existing configuration and admin credentials.")
        return
    previous = args.destination.stat() if args.destination.exists() else None
    if previous:
        value = {**DEFAULTS, **read_json(args.destination)}
    elif args.seed:
        value = {**DEFAULTS, **read_json(args.seed)}
    else:
        value = dict(DEFAULTS)
    if args.tar1090 is not None:
        value["RECEIVER_URLS"] = [tar1090_address(args.tar1090)]
    if not previous and not args.seed:
        if not sys.stdin.isatty():
            parser.error("First install needs a terminal or --config FILE with preseeded settings")
        if args.tar1090 is None:
            value["RECEIVER_URLS"] = prompt_feed()
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
        if previous:
            os.chown(args.destination, previous.st_uid, previous.st_gid)
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
