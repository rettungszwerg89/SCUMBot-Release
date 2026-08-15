# Zustandsmaschine fuer Weltereignisse: Ort wechselt periodisch (zufaellig aus
# konfigurierter Liste), bei jedem Ortswechsel gibt es sofort einen Loot-Abwurf,
# danach in regelmaessigen Abstaenden weitere (bessere bei hoher Spielerzahl
# im Gebiet). Kill/Tod-Bonus im Eventgebiet wird direkt in bot.py's
# poll_killfeed angebunden (nutzt get_current_location()).

import json
import os
import random
from datetime import datetime, timedelta
import config


def _default_state() -> dict:
    return {
        "location_key": None,
        "started_at": None,
        "next_change_at": datetime.now().isoformat(),  # erzwingt sofortige Ortswahl beim ersten Check
        "last_loot_at": None,
    }


def _load() -> dict:
    if not os.path.exists(config.WORLD_EVENT_STATE_FILE):
        return _default_state()
    with open(config.WORLD_EVENT_STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    for key, value in _default_state().items():
        data.setdefault(key, value)
    return data


def _save(data: dict) -> None:
    with open(config.WORLD_EVENT_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_state() -> dict:
    return _load()


def get_current_location() -> dict | None:
    state = _load()
    if not state.get("location_key"):
        return None
    return next(
        (loc for loc in config.get_world_event_locations() if loc["key"] == state["location_key"]), None
    )


def is_location_change_due() -> bool:
    state = _load()
    return datetime.now() >= datetime.fromisoformat(state["next_change_at"])


def pick_new_location() -> dict | None:
    """Waehlt einen neuen (nach Moeglichkeit anderen) Ort, setzt Timer zurueck
    und erzwingt einen sofortigen Loot-Abwurf. Gibt None zurueck, wenn keine
    Orte konfiguriert sind."""
    locations = config.get_world_event_locations()
    if not locations:
        return None
    state = _load()
    candidates = [loc for loc in locations if loc["key"] != state.get("location_key")] or locations
    new_location = random.choice(candidates)

    interval_minutes = random.randint(config.WORLD_EVENT_MIN_INTERVAL_MINUTES, config.WORLD_EVENT_MAX_INTERVAL_MINUTES)
    now = datetime.now()
    state["location_key"] = new_location["key"]
    state["started_at"] = now.isoformat()
    state["next_change_at"] = (now + timedelta(minutes=interval_minutes)).isoformat()
    state["last_loot_at"] = None
    _save(state)
    return new_location


def is_loot_due() -> bool:
    state = _load()
    if not state.get("location_key"):
        return False
    if state.get("last_loot_at") is None:
        return True
    next_loot = datetime.fromisoformat(state["last_loot_at"]) + timedelta(minutes=config.WORLD_EVENT_LOOT_INTERVAL_MINUTES)
    return datetime.now() >= next_loot


def mark_loot_dropped() -> None:
    state = _load()
    state["last_loot_at"] = datetime.now().isoformat()
    _save(state)


def pick_loot_items(high_pop: bool) -> list:
    """Waehlt zufaellig Loot-Artikel aus dem konfigurierten Pool - mehr/bessere
    Auswahl bei hoher Spielerzahl im Gebiet. Jeder Pool-Eintrag hat seine eigene
    Menge, unabhaengig vom Shop-Standardwert."""
    entries = config.get_world_event_loot_entries()
    items = []
    for entry in entries:
        item = config.get_shop_item_by_key(entry["item_key"])
        if item is not None:
            items.append({**item, "amount": entry.get("amount", 1)})
    if not items:
        return []
    count = random.randint(2, 3) if high_pop else random.randint(1, 2)
    count = min(count, len(items))
    return random.sample(items, count)
