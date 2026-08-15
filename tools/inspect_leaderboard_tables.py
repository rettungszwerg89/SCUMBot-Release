# Inspektionsskript: zeigt Spalten UND eine Beispielzeile der Tabellen,
# die vermutlich die Leaderboard-Statistiken enthalten (Kills, Distanz, Geld etc.)
# Read-only, aendert nichts an der DB.

import sqlite3

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

DB_PATH = config.SCUM_DB_PATH

TABLES_TO_CHECK = [
    "survival_stats",
    "tracking_data",
    "tracking_data_set",
    "fishing_stats",
    "events_stats",
    "event_round_stats",
    "quest_lifetime_stats",
    "bank_general_data",
    "user_profile",
]

conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
cursor = conn.cursor()

for table in TABLES_TO_CHECK:
    print(f"\n=== {table} ===")
    try:
        cursor.execute(f"PRAGMA table_info('{table}')")
        cols = cursor.fetchall()
        if not cols:
            print("   (Tabelle existiert nicht)")
            continue
        for col in cols:
            print(f"   {col[1]} ({col[2]})")

        cursor.execute(f"SELECT * FROM '{table}' LIMIT 1")
        row = cursor.fetchone()
        col_names = [c[1] for c in cols]
        print("   --- Beispielzeile ---")
        if row:
            for name, value in zip(col_names, row):
                # BLOB-Felder kuerzen, die interessieren uns eh nicht
                if isinstance(value, bytes):
                    value = f"<BLOB, {len(value)} bytes>"
                print(f"   {name} = {value}")
        else:
            print("   (keine Zeilen vorhanden)")
    except Exception as e:
        print(f"   FEHLER: {e}")

conn.close()
