"""Regional flights sold under a major airline's flight number (codeshares).

A SkyWest jet flying United Express 5432 calls itself ``SKW5432`` on ADS-B:
regional operators broadcast the marketing airline's flight number behind
their own ICAO prefix. Route databases often know the marketed flight
(``UAL5432``) when they miss the operating callsign, so route lookups
(``metadata.py``) fall back to asking about these.
"""
from __future__ import annotations

from typing import Optional

# Operating airline (ICAO): the airlines whose flight numbers it flies, most likely first.
MARKETING_CARRIERS: dict[str, tuple[str, ...]] = {
    "SKW": ("UAL", "DAL", "AAL", "ASA"),  # SkyWest
    "RPA": ("AAL", "UAL", "DAL"),  # Republic
    "EDV": ("DAL",),  # Endeavor (Delta Connection)
    "ENY": ("AAL",),  # Envoy (American Eagle)
    "PDT": ("AAL",),  # Piedmont
    "JIA": ("AAL",),  # PSA
    "AWI": ("UAL", "AAL"),  # Air Wisconsin
    "ASH": ("UAL",),  # Mesa
    "GJS": ("UAL",),  # GoJet
    "UCA": ("UAL",),  # CommutAir
    "QXE": ("ASA",),  # Horizon
    "JZA": ("ACA",),  # Jazz (Air Canada Express)
    "ROU": ("ACA",),  # Air Canada Rouge
    "WEN": ("WJA",),  # WestJet Encore
    "SLI": ("AMX",),  # Aeroméxico Connect
    "CLH": ("DLH",),  # Lufthansa CityLine
    "KLC": ("KLM",),  # KLM Cityhopper
}


def codeshare_callsigns(callsign: Optional[str]) -> tuple[str, ...]:
    """``"SKW5432"`` -> ``("UAL5432", "DAL5432", "AAL5432", "ASA5432")``; empty for other callsigns."""

    callsign = (callsign or "").strip().upper()
    number = callsign[3:]
    if not number[:1].isdigit():
        return ()
    return tuple(partner + number for partner in MARKETING_CARRIERS.get(callsign[:3], ()))
