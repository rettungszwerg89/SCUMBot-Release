# Speichert einmal pro Woche einen "Startwert"-Snapshot der Spielerstatistiken
# lokal als JSON, damit wir spaeter (aktueller Wert - Snapshot) als
# Wochenleistung anzeigen koennen. Die SCUM.db selbst hat keine Wochenhistorie.

import json
import os
from datetime import datetime, timedelta
import config
from dbdata import leaderboard_stats


def _load() -> dict:
    if not os.path.exists(config.WEEKLY_SNAPSHOT_FILE):
        return {"reset_at": None, "players": {}, "squads": {}}
    with open(config.WEEKLY_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(config.WEEKLY_SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def take_snapshot() -> None:
    """Speichert die aktuellen Werte als neue Baseline fuer die kommende Woche."""
    players = leaderboard_stats.get_current_player_data()
    squads = leaderboard_stats.get_current_squad_data()
    data = {
        "reset_at": datetime.now().isoformat(),
        "players": {str(uid): p for uid, p in players.items()},
        "squads": {str(sid): s for sid, s in squads.items()},
    }
    _save(data)


def get_baseline() -> dict:
    return _load()


def is_reset_due() -> bool:
    """Prueft, ob der naechste woechentliche Reset-Zeitpunkt erreicht/ueberschritten wurde."""
    data = _load()
    if data["reset_at"] is None:
        return True  # noch nie ein Snapshot gemacht

    last_reset = datetime.fromisoformat(data["reset_at"])
    now = datetime.now()

    # Naechsten Reset-Zeitpunkt (Wochentag + Uhrzeit) nach dem letzten Reset berechnen
    days_ahead = (config.WEEKLY_RESET_WEEKDAY - last_reset.weekday()) % 7
    next_reset = (last_reset + timedelta(days=days_ahead)).replace(
        hour=config.WEEKLY_RESET_HOUR, minute=0, second=0, microsecond=0
    )
    if next_reset <= last_reset:
        next_reset += timedelta(days=7)

    return now >= next_reset


def get_weekly_value(current_value: float, baseline_value: float) -> float:
    """Differenz aktueller Wert minus Baseline, nie negativ (falls z.B. Geld ausgegeben wurde)."""
    delta = current_value - baseline_value
    return delta if delta > 0 else 0
