# Sucht die SteamID eines Spielers anhand seines Ingame-Namens (aus der
# SCUM.db, unabhaengig vom Online-Status). Wird u.a. von world_event.py
# gebraucht, um Online-Spieler fuer die Loot-Verteilung aufzuloesen.

from dbdata import leaderboard_stats


def find_steam_id_by_name(name: str) -> str | None:
    """Sucht per case-insensitivem exaktem Namensvergleich unter allen jemals
    gesehenen Spielern."""
    name_lower = name.strip().lower()
    for record in leaderboard_stats.get_current_player_data().values():
        if (record.get("name") or "").strip().lower() == name_lower:
            return record.get("user_id")
    return None
