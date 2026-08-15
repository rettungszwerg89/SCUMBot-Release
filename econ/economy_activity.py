# Verfolgt Spieleraktivitaet (Kills, Headshots, etc.) zwischen zwei Pruefungen
# und rechnet die Differenz in Coins um. Nutzt denselben Snapshot-Ansatz wie
# das woechentliche Leaderboard, nur mit kurzem Intervall (siehe config.ECONOMY_CHECK_SECONDS).

import json
import os
import config
from dbdata import leaderboard_stats


def _load_snapshot() -> dict:
    if not os.path.exists(config.ECONOMY_SNAPSHOT_FILE):
        return {}
    with open(config.ECONOMY_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_snapshot(data: dict) -> None:
    with open(config.ECONOMY_SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def calculate_activity_earnings() -> dict:
    """Vergleicht aktuelle Werte mit dem letzten Snapshot, gibt
    {user_profile_id: (verdiente_coins, {stat: delta, ...})} zurueck und
    aktualisiert den Snapshot fuer die naechste Pruefung."""
    current = leaderboard_stats.get_current_player_data()
    snapshot = _load_snapshot()

    earnings = {}
    new_snapshot = {}

    for uid, data in current.items():
        key = str(uid)
        prev = snapshot.get(key, {})
        total_coins = 0
        deltas = {}

        for stat, rate in config.ACTIVITY_COIN_RATES.items():
            cur_val = data.get(stat, 0)
            prev_val = prev.get(stat, cur_val)  # beim ersten Mal: kein Delta
            delta = cur_val - prev_val
            if delta > 0:
                deltas[stat] = delta
                total_coins += delta * rate

        if total_coins > 0:
            earnings[uid] = (total_coins, deltas, data["name"], data.get("user_id"))

        new_snapshot[key] = {stat: data.get(stat, 0) for stat in config.ACTIVITY_COIN_RATES}

    _save_snapshot(new_snapshot)
    return earnings
