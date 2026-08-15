# Einfaches Coins-Ledger fuer das Economy-System.
# Konten werden per Discord-ID gefuehrt (verknuepfte Accounts, siehe account_links.py).

import json
import os
import config


def _load() -> dict:
    if not os.path.exists(config.ECONOMY_FILE):
        return {}
    with open(config.ECONOMY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(config.ECONOMY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_balance(discord_id: int) -> int:
    return _load().get(str(discord_id), {}).get("balance", 0)


def add_coins(discord_id: int, amount: int, reason: str = "") -> int:
    """Schreibt Coins gut, gibt den neuen Kontostand zurueck."""
    data = _load()
    key = str(discord_id)
    if key not in data:
        data[key] = {"balance": 0, "history": []}
    data[key]["balance"] += amount
    data[key].setdefault("history", []).append({"amount": amount, "reason": reason})
    # Historie nicht endlos wachsen lassen
    data[key]["history"] = data[key]["history"][-50:]
    _save(data)
    return data[key]["balance"]


def spend_coins(discord_id: int, amount: int) -> bool:
    """Zieht Coins ab, falls genug vorhanden. Gibt True bei Erfolg zurueck."""
    data = _load()
    key = str(discord_id)
    balance = data.get(key, {}).get("balance", 0)
    if balance < amount:
        return False
    data[key]["balance"] -= amount
    _save(data)
    return True
