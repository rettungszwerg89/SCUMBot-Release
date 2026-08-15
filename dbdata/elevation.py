# Verwaltet TEMPORAERE Eintraege in der elevated_users-Tabelle der SCUM.db,
# damit nicht-Admin-Spieler kurzzeitig Items/Fahrzeuge per Admin-Befehl
# bekommen koennen (Chat_Server_ProcessAdminCommand prueft offenbar Admin-
# bzw. Elevated-Status). Schreibt NUR kurzfristig, entfernt den Eintrag danach
# wieder automatisch (siehe bot.py: _grant_temp_elevation_and_schedule_revoke).
#
# VORSICHT: Nur bei ausdruecklichem, kontrolliertem Test verwenden - Schreibzugriff
# auf eine DB, die der laufende Server ebenfalls offen haelt.

import sqlite3
import config


def _connect_write():
    # KEIN read-only Modus - wir schreiben hier bewusst.
    return sqlite3.connect(config.SCUM_DB_PATH, timeout=5)


def is_elevated(steam_id: str) -> bool:
    conn = sqlite3.connect(f"file:{config.SCUM_DB_PATH}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM elevated_users WHERE user_id = ?", (steam_id,))
        return cur.fetchone() is not None
    finally:
        conn.close()


def add_elevated_user(steam_id: str) -> None:
    conn = _connect_write()
    try:
        conn.execute("INSERT OR IGNORE INTO elevated_users (user_id) VALUES (?)", (steam_id,))
        conn.commit()
    finally:
        conn.close()


def remove_elevated_user(steam_id: str) -> None:
    conn = _connect_write()
    try:
        conn.execute("DELETE FROM elevated_users WHERE user_id = ?", (steam_id,))
        conn.commit()
    finally:
        conn.close()
