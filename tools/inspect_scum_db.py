# Inspektionsskript: zeigt alle Tabellen und deren Spalten in SCUM.db.
# Oeffnet die Datenbank read-only, damit nichts veraendert/kaputt gemacht werden kann,
# auch wenn der SCUM-Server parallel laeuft.

import sqlite3

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

DB_PATH = config.SCUM_DB_PATH

# Read-only Verbindung ueber URI-Modus
conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
tables = [row[0] for row in cursor.fetchall()]

print(f"Gefundene Tabellen ({len(tables)}):\n")

# Tabellen, die vermutlich relevant sind, zuerst genauer anzeigen
keywords = ["squad", "player", "prisoner", "user", "time", "world", "server", "character"]
interesting = [t for t in tables if any(k in t.lower() for k in keywords)]
other = [t for t in tables if t not in interesting]

def show_table(name):
    print(f"=== {name} ===")
    cursor.execute(f"PRAGMA table_info('{name}')")
    for col in cursor.fetchall():
        print(f"   {col[1]} ({col[2]})")
    cursor.execute(f"SELECT COUNT(*) FROM '{name}'")
    count = cursor.fetchone()[0]
    print(f"   -> {count} Zeilen\n")

print("--- Vermutlich relevante Tabellen ---\n")
for t in interesting:
    show_table(t)

print("--- Weitere Tabellen (nur Namen) ---")
print(", ".join(other))

conn.close()
