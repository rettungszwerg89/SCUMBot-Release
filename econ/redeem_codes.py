# Verwaltet Admin-generierte Redeem-Codes (Ersatz fuer "/createcode"). Ein
# Code ist an genau einen Shop-Artikel gebunden (siehe config.get_shop_item_by_key)
# und wird ueber denselben Auslieferungsweg wie ein Shop-Kauf verschickt, nur
# ohne Coins-Abzug.

import json
import os
import random
import string
from datetime import datetime
import config


def _load() -> list:
    if not os.path.exists(config.REDEEM_CODES_FILE):
        return []
    with open(config.REDEEM_CODES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: list) -> None:
    with open(config.REDEEM_CODES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _generate_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "-".join("".join(random.choices(alphabet, k=4)) for _ in range(2))


def create_code(
    item_key: str, amount: int = 1, max_uses: int = 1, expires_at: str | None = None, note: str = ""
) -> str:
    """Erstellt einen neuen, eindeutigen Redeem-Code fuer den gegebenen Shop-
    Artikel-Key (mit eigener Menge, unabhaengig vom Shop-Standardwert) und
    gibt ihn zurueck."""
    codes = _load()
    existing = {c["code"] for c in codes}
    code = _generate_code()
    while code in existing:
        code = _generate_code()
    codes.append({
        "code": code,
        "item_key": item_key,
        "amount": amount,
        "max_uses": max_uses,
        "uses": 0,
        "redeemed_by": [],
        "created_at": datetime.now().isoformat(),
        "expires_at": expires_at,
        "note": note,
    })
    _save(codes)
    return code


def list_codes() -> list:
    return _load()


def delete_code(code: str) -> bool:
    codes = _load()
    remaining = [c for c in codes if c["code"] != code]
    if len(remaining) == len(codes):
        return False
    _save(remaining)
    return True


def redeem(discord_id: int, code_text: str) -> tuple[bool, str, dict | None]:
    """Prueft und loest einen Code fuer discord_id ein. Gibt (erfolg, fehlermeldung,
    shop_item) zurueck - shop_item ist nur bei Erfolg gesetzt."""
    normalized = code_text.strip().upper()
    codes = _load()
    entry = next((c for c in codes if c["code"] == normalized), None)
    if entry is None:
        return False, "Dieser Code ist ungültig.", None

    if entry.get("expires_at") and datetime.now() > datetime.fromisoformat(entry["expires_at"]):
        return False, "Dieser Code ist abgelaufen.", None

    if entry["uses"] >= entry["max_uses"]:
        return False, "Dieser Code wurde bereits vollständig eingelöst.", None

    if discord_id in entry["redeemed_by"]:
        return False, "Du hast diesen Code bereits eingelöst.", None

    item = config.get_shop_item_by_key(entry["item_key"])
    if item is None:
        return False, "Der zu diesem Code gehörende Artikel existiert nicht mehr. Sag Bescheid an einen Admin.", None

    entry["uses"] += 1
    entry["redeemed_by"].append(discord_id)
    _save(codes)
    return True, "", {**item, "amount": entry.get("amount", 1)}
