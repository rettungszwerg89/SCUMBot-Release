import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import sqlite3
import config

conn = sqlite3.connect(f"file:{config.SCUM_DB_PATH}?mode=ro", uri=True)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
all_tables = [r[0] for r in cur.fetchall()]
print(f"Alle {len(all_tables)} Tabellen:")
for t in all_tables:
    print(" -", t)

print("\n--- Tabellen mit 'trader', 'econom', 'fund', 'shop', 'outpost' im Namen ---")
keywords = ["trader", "econom", "fund", "shop", "outpost", "market", "prisoner_"]
matches = [t for t in all_tables if any(k in t.lower() for k in keywords)]
for t in matches:
    print(f"\n=== {t} ===")
    cur.execute(f"PRAGMA table_info({t})")
    cols = cur.fetchall()
    for c in cols:
        print("   ", c[1], c[2])
    cur.execute(f"SELECT * FROM {t} LIMIT 5")
    rows = cur.fetchall()
    print("   Beispielzeilen:", rows)

conn.close()
