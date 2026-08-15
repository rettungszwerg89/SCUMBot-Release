# Prueft periodisch die top-games.net Voting-API (players-ranking) und
# schreibt neuen Spielern, deren Stimmenzahl gestiegen ist, automatisch
# Coins gut. Erkennt "neue" Stimmen durch Vergleich mit dem letzten
# bekannten Stand (data/topgames_votes.json).

import json
import requests
import config
import account_links
from econ import economy


def _load_last_known() -> dict:
    try:
        with open(config.VOTE_TRACKING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_last_known(data: dict) -> None:
    with open(config.VOTE_TRACKING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_players_ranking() -> list:
    resp = requests.get(config.TOPGAMES_RANKING_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"top-games.net API meldete Fehler: {data}")
    return data.get("players", [])


def check_and_reward_votes() -> list:
    """Gibt eine Liste von (player_name, neue_stimmen, discord_id_or_None,
    gutgeschriebene_coins) fuer jeden Spieler zurueck, dessen Stimmenzahl seit
    der letzten Pruefung gestiegen ist."""
    last_known = _load_last_known()
    current = get_players_ranking()

    links = account_links._load_links()
    name_to_discord_id = {v.get("player_name"): k for k, v in links.items()}

    results = []
    for entry in current:
        name = entry.get("playername")
        votes = entry.get("votes", 0)
        if not name:
            continue
        previous = last_known.get(name, votes)  # beim allerersten Mal: nicht rueckwirkend belohnen
        if votes > previous:
            new_votes = votes - previous
            discord_id = name_to_discord_id.get(name)
            coins_awarded = 0
            if discord_id:
                coins_awarded = new_votes * config.VOTE_REWARD_COINS
                economy.add_coins(int(discord_id), coins_awarded, reason=f"{new_votes}x Vote auf top-games.net")
            results.append((name, new_votes, discord_id, coins_awarded))
        last_known[name] = votes

    _save_last_known(last_known)
    return results
