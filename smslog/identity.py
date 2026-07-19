#!/usr/bin/env python3
"""
Unified identity layer for SMS Logger.

Maps any transport-specific key (SMS phone, tg:USER_ID, signal:+PHONE)
to a canonical key — the sender's primary phone number, digits only, no country code.

To add a new platform: extend the maps below and write a thin {platform}_bot.py.
No changes to server.py, telegram_bot.py, or signal_bot.py needed.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


def _digits(s: str) -> str:
    """Normalize a phone string to digits only, stripping leading US country code."""
    d = "".join(c for c in s if c.isdigit())
    # Strip leading 1 only when it would produce a 10-digit US number
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d


def _parse_numbers(env_val: str) -> list[str]:
    return [d for n in env_val.split(",") if (d := _digits(n.strip()))]


# ── Canonical keys (primary phone, digits only, no country code) ──────────────

_owner_numbers   = _parse_numbers(os.getenv("OWNER_NUMBERS", ""))
_trusted_numbers = _parse_numbers(os.getenv("TRUSTED_NUMBERS", ""))

OWNER_CANONICAL   = _owner_numbers[0]   if _owner_numbers   else ""
TRUSTED_CANONICAL = _trusted_numbers[0] if _trusted_numbers else ""

# ── Transport ID sets ─────────────────────────────────────────────────────────

_tg_owner_ids   = set(filter(None, os.getenv("TELEGRAM_OWNER_IDS",   "").split(",")))
_tg_trusted_ids = set(filter(None, os.getenv("TELEGRAM_TRUSTED_IDS", "").split(",")))

# Signal phone numbers for each identity (separate from the service's own Signal number)
_sig_owner_phones   = {_digits(os.getenv("SIGNAL_OWNER_NUMBER",   ""))} - {""}
_sig_trusted_phones = {_digits(os.getenv("SIGNAL_TRUSTED_NUMBER", ""))} - {""}

# ── Build lookup table: transport_key → canonical ────────────────────────────

_MAP: dict[str, str] = {}

# SMS: all owner/trusted numbers → canonical
for _n in _owner_numbers:
    _MAP[_n] = OWNER_CANONICAL
for _n in _trusted_numbers:
    _MAP[_n] = TRUSTED_CANONICAL

# Telegram → canonical
for _id in _tg_owner_ids:
    _MAP[f"tg:{_id}"] = OWNER_CANONICAL
for _id in _tg_trusted_ids:
    _MAP[f"tg:{_id}"] = TRUSTED_CANONICAL

# Signal → canonical  (stored normalized: signal:DIGITS)
for _sp in _sig_owner_phones:
    _MAP[f"signal:{_sp}"] = OWNER_CANONICAL
for _sp in _sig_trusted_phones:
    _MAP[f"signal:{_sp}"] = TRUSTED_CANONICAL


# ── Public API ────────────────────────────────────────────────────────────────

def resolve_key(transport_key: str) -> str:
    """Map any transport key to the canonical identity key.

    Returns the canonical phone (digits, no country code) when the sender is
    known.  For unknown senders the transport key is returned unchanged (or,
    for plain phone strings, digit-normalized).

    Examples:
        resolve_key("5551234567")       → "5551234567"  (already canonical)
        resolve_key("+15551234567")     → "5551234567"  (normalized)
        resolve_key("tg:12345678")      → "5551234567"  (owner's canonical)
        resolve_key("signal:+15551234567") → "5551234567"
        resolve_key("tg:9999999")       → "tg:9999999"  (unknown — unchanged)
    """
    # Direct lookup
    if transport_key in _MAP:
        return _MAP[transport_key]

    # Prefixed keys (tg: / signal:) — normalize phone part for signal and retry
    for prefix in ("tg:", "signal:"):
        if transport_key.startswith(prefix):
            if prefix == "signal:":
                norm = f"signal:{_digits(transport_key[len(prefix):])}"
                if norm in _MAP:
                    return _MAP[norm]
            return transport_key  # unknown prefixed user

    # Plain phone number — normalize digits and look up
    norm = _digits(transport_key)
    if norm and norm in _MAP:
        return _MAP[norm]
    return norm or transport_key  # unknown phone: return normalized form


def is_owner(key: str) -> bool:
    """True if key (transport or canonical) belongs to the owner."""
    return bool(OWNER_CANONICAL) and resolve_key(key) == OWNER_CANONICAL


def is_trusted(key: str) -> bool:
    """True if key (transport or canonical) belongs to a trusted contact."""
    return bool(TRUSTED_CANONICAL) and resolve_key(key) == TRUSTED_CANONICAL
