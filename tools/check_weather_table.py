import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import sqlite3
import config

conn = sqlite3.connect(f"file:{config.SCUM_DB_PATH}?mode=ro", uri=True)
cur = conn.cursor()

cur.execute("PRAGMA table_info(weather_parameters)")
print("Spalten in weather_parameters:")
for c in cur.fetchall():
    print("   ", c[1], c[2])

cur.execute("SELECT * FROM weather_parameters LIMIT 3")
print("\nBeispielzeilen:")
for row in cur.fetchall():
    print("   ", row)

conn.close()
