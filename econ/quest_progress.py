# Speichert den Teilfortschritt jedes Spielers pro Quest (wie viele Exemplare
# jedes benoetigten Artikels bereits abgegeben wurden). Eine Quest gilt als
# abgeschlossen, wenn fuer alle Anforderungen genug abgegeben wurde.

import json
import os
import config


def _load() -> dict:
    if not os.path.exists(config.QUEST_PROGRESS_FILE):
        return {}
    with open(config.QUEST_PROGRESS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(config.QUEST_PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_progress(quest_key: str, discord_id: int) -> dict:
    """Gibt {item_key: abgegebene_menge} fuer diesen Spieler zurueck."""
    return _load().get(quest_key, {}).get(str(discord_id), {})


def add_progress(quest_key: str, discord_id: int, item_key: str, amount: int) -> dict:
    data = _load()
    quest_data = data.setdefault(quest_key, {})
    player_data = quest_data.setdefault(str(discord_id), {})
    player_data[item_key] = player_data.get(item_key, 0) + amount
    _save(data)
    return player_data


def reset_progress(quest_key: str, discord_id: int) -> None:
    data = _load()
    key = str(discord_id)
    if quest_key in data and key in data[quest_key]:
        del data[quest_key][key]
        if not data[quest_key]:
            del data[quest_key]
        _save(data)
