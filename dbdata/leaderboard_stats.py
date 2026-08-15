# Definiert alle Leaderboard-Kategorien und liest die aktuellen Werte
# aus der SCUM.db (read-only).

import sqlite3
import config

# Jede Kategorie beschreibt, woher der Wert kommt und wie er angezeigt wird.
#   kind: "counter" (kumulativer Wert, wochendelta = aktuell - baseline)
#         "ratio"   (Verhaeltnis zweier Counter, z.B. Kills/Deaths)
#         "record"  (persoenlicher Rekordwert, nicht sinnvoll "pro Woche" isolierbar
#                     -> erscheint nur im Allzeit-Board)
STAT_DEFS = [
    {"id": "kills", "emoji": "⚔️", "label": "Top Kills", "kind": "counter",
     "column": "kills", "fmt": "int", "compact": True},
    {"id": "pvp_kills", "emoji": "🔫", "label": "Top PvP-Kills", "kind": "counter",
     "column": "prisoner_kills", "fmt": "int", "compact": True},
    {"id": "kd", "emoji": "📊", "label": "Top K/D-Verhältnis", "kind": "ratio",
     "num_column": "kills", "den_column": "deaths", "fmt": "float2", "compact": True},
    {"id": "headshots", "emoji": "🎯", "label": "Top Kopfschüsse", "kind": "counter",
     "column": "headshots", "fmt": "int", "compact": True},
    {"id": "accuracy", "emoji": "📈", "label": "Top Treffsicherheit", "kind": "ratio",
     "num_column": "shots_hit", "den_column": "shots_fired", "fmt": "percent", "compact": False},
    {"id": "sniper_distance", "emoji": "🏹", "label": "Top Scharfschützen-Distanz", "kind": "record",
     "column": "longest_kill_distance", "fmt": "meters", "compact": False},
    {"id": "puppet_kills", "emoji": "🧟", "label": "Top Puppet-Kills", "kind": "counter",
     "column": "puppets_killed", "fmt": "int", "compact": True},
    {"id": "animal_kills", "emoji": "🐾", "label": "Top Tier-Kills", "kind": "counter",
     "column": "animals_killed", "fmt": "int", "compact": False},
    {"id": "bear_kills", "emoji": "🐻", "label": "Top Bärenjäger", "kind": "counter",
     "column": "bears_killed", "fmt": "int", "compact": False},
    {"id": "fame", "emoji": "⭐", "label": "Top Ruhm", "kind": "counter",
     "column": "fame_points", "fmt": "int", "compact": True},
    {"id": "money", "emoji": "💰", "label": "Top Geld", "kind": "counter",
     "column": "money_balance", "fmt": "money", "compact": True},
    {"id": "survived", "emoji": "⏳", "label": "Top Überlebende", "kind": "counter",
     "column": "minutes_survived", "fmt": "hours", "compact": True},
    {"id": "distance", "emoji": "🏃", "label": "Top zurückgelegte Distanz", "kind": "counter",
     "column": "distance_travelled_by_foot", "fmt": "km", "compact": True},
    {"id": "fish", "emoji": "🎣", "label": "Meiste Fische gefangen", "kind": "counter",
     "column": "fish_caught", "fmt": "int", "compact": False},
    {"id": "locks", "emoji": "🔓", "label": "Top Schlossknacker", "kind": "counter",
     "column": "locks_picked", "fmt": "int", "compact": True},
]

# Alle Rohspalten, die fuer obige Kategorien aus der DB gebraucht werden
# (fuer Wochen-Snapshot und aktuelle Werte gleichermassen).
_RAW_COLUMNS = sorted({
    c for d in STAT_DEFS
    for c in [d.get("column"), d.get("num_column"), d.get("den_column")]
    if c
})

_PROFILE_COLUMNS = {"fame_points", "money_balance", "play_time"}


def _connect():
    return sqlite3.connect(f"file:{config.SCUM_DB_PATH}?mode=ro", uri=True)


def get_current_player_data() -> dict:
    """Liefert {user_profile_id: {"name": ..., <spalten>: wert, ...}} fuer alle Spieler."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT up.id, up.user_id, up.name, up.fame_points, up.money_balance, up.play_time,
                   ss.kills, ss.deaths, ss.prisoner_kills, ss.headshots, ss.puppets_killed,
                   ss.animals_killed, ss.bears_killed, ss.locks_picked,
                   ss.distance_travelled_by_foot, ss.shots_fired, ss.shots_hit,
                   ss.minutes_survived, ss.longest_kill_distance,
                   fs.fish_caught
            FROM user_profile up
            LEFT JOIN survival_stats ss ON ss.user_profile_id = up.id
            LEFT JOIN fishing_stats fs ON fs.user_profile_id = up.id
            WHERE up.name IS NOT NULL
            """
        )
        cols = [d[0] for d in cur.description]
        result = {}
        for row in cur.fetchall():
            record = dict(zip(cols, row))
            uid = record.pop("id")
            for k, v in record.items():
                if v is None:
                    record[k] = 0
            result[uid] = record
        return result
    finally:
        conn.close()


def get_player_data_by_steam_id(steam_id: str) -> dict | None:
    """Liefert dieselben Felder wie get_current_player_data(), aber nur fuer
    einen einzelnen Spieler anhand seiner SteamID (fuer /meine-statistiken)."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT up.name, up.fame_points, up.money_balance, up.play_time,
                   ss.kills, ss.deaths, ss.prisoner_kills, ss.headshots, ss.puppets_killed,
                   ss.animals_killed, ss.bears_killed, ss.locks_picked,
                   ss.distance_travelled_by_foot, ss.shots_fired, ss.shots_hit,
                   ss.minutes_survived, ss.longest_kill_distance,
                   fs.fish_caught
            FROM user_profile up
            LEFT JOIN survival_stats ss ON ss.user_profile_id = up.id
            LEFT JOIN fishing_stats fs ON fs.user_profile_id = up.id
            WHERE up.user_id = ?
            """,
            (steam_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        record = dict(zip(cols, row))
        for k, v in record.items():
            if v is None:
                record[k] = 0
        return record
    finally:
        conn.close()


def get_current_squad_data() -> dict:
    """Liefert {squad_id: {"name":..., "score":...}}."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, score FROM squad")
        return {row[0]: {"name": row[1], "score": row[2] or 0} for row in cur.fetchall()}
    finally:
        conn.close()
