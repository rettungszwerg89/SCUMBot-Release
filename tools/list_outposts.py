import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import sqlite3
import config

conn = sqlite3.connect(f"file:{config.SCUM_DB_PATH}?mode=ro", uri=True)
cur = conn.cursor()

cur.execute("SELECT id, outpost_runtime_id, outpost_bank_funds, buying_capability FROM economy_outposts ORDER BY id")
print("Aussenposten (economy_outposts):")
for row in cur.fetchall():
    print("  id=%s  runtime_id=%s  bank_funds=%s  buying_capability=%s" % row)

print()
cur.execute("SELECT id, outpost_id, gold_buying_capability_funds, gold_selling_capability_funds FROM economy_outpost_gold ORDER BY id")
print("Gold je Aussenposten (economy_outpost_gold):")
for row in cur.fetchall():
    print("  id=%s  outpost_id=%s  gold_buy=%s  gold_sell=%s" % row)

conn.close()
