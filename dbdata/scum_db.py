# Liest Spieler- und Squad-Zahlen direkt aus der SCUM.db (read-only, sicher
# auch bei laufendem Server dank SQLite WAL-Modus).

import sqlite3
import config


def _connect():
    # Read-only Verbindung, damit nichts an der Live-DB veraendert werden kann.
    return sqlite3.connect(f"file:{config.SCUM_DB_PATH}?mode=ro", uri=True)


def get_total_players() -> int:
    """Anzahl aller Spieler, die sich jemals mit dem Server verbunden haben."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM user")
        return cur.fetchone()[0]
    finally:
        conn.close()


def get_active_squads() -> int:
    """Anzahl aktuell existierender Squads."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM squad")
        return cur.fetchone()[0]
    finally:
        conn.close()


def get_vehicle_count() -> int:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM vehicle_entity")
        return cur.fetchone()[0]
    finally:
        conn.close()


def get_base_count() -> int:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM base")
        return cur.fetchone()[0]
    finally:
        conn.close()


def get_weather() -> dict | None:
    """Inselzeit (time_of_day, als Stunden mit Nachkommastellen) sowie Luft-/
    Wassertemperatur, live aus der SCUM.db."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT time_of_day, base_air_temperature, water_temperature "
            "FROM weather_parameters LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return None
        time_of_day, air_temp, water_temp = row
        hours = int(time_of_day)
        minutes = int(round((time_of_day - hours) * 60))
        if minutes == 60:
            minutes = 0
            hours = (hours + 1) % 24
        return {
            "island_time": f"{hours:02d}:{minutes:02d}",
            "air_temp": round(air_temp, 1),
            "water_temp": round(water_temp, 1),
        }
    finally:
        conn.close()


def get_outposts_detail() -> list:
    """Detaillierte Aussenposten-Daten mit echten Namen (siehe config.OUTPOST_NAMES,
    durch Vorher/Nachher-Kauftest bestaetigt)."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT o.id, o.outpost_bank_funds, o.buying_capability, "
            "g.gold_buying_capability_funds, g.gold_selling_capability_funds "
            "FROM economy_outposts o "
            "LEFT JOIN economy_outpost_gold g ON g.outpost_id = o.id "
            "ORDER BY o.id"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    result = []
    for outpost_id, bank_funds, buying_capability, gold_buy, gold_sell in rows:
        result.append({
            "name": config.OUTPOST_NAMES.get(outpost_id, f"Außenposten {outpost_id}"),
            "bank_funds": int(bank_funds or 0),
            "buying_capability": int(buying_capability or 0),
            "gold_buy": int(gold_buy or 0),
            "gold_sell": int(gold_sell or 0),
            "image_file": config.OUTPOST_IMAGE_FILES.get(config.OUTPOST_NAMES.get(outpost_id)),
        })
    result.sort(key=lambda o: o["name"])
    return result


def get_economy_summary() -> dict:
    """Aggregierte Haendler-/Aussenposten-Wirtschaftszahlen. Einzelne Haendler
    haben in der SCUM.db nur kryptische Hash-IDs, keine lesbaren Namen - daher
    nur Summen, keine Aufschluesselung nach 'Aussenposten A0' o.ae."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), COALESCE(SUM(available_funds), 0) FROM economy_traders")
        trader_count, trader_funds = cur.fetchone()

        cur.execute("SELECT COUNT(*), COALESCE(SUM(outpost_bank_funds), 0) FROM economy_outposts")
        outpost_count, outpost_bank_funds = cur.fetchone()

        cur.execute(
            "SELECT COALESCE(SUM(gold_buying_capability_funds), 0), "
            "COALESCE(SUM(gold_selling_capability_funds), 0) FROM economy_outpost_gold"
        )
        gold_buy, gold_sell = cur.fetchone()

        return {
            "trader_count": trader_count,
            "trader_funds": int(trader_funds),
            "outpost_count": outpost_count,
            "outpost_bank_funds": int(outpost_bank_funds),
            "gold_buy_capacity": int(gold_buy),
            "gold_sell_available": int(gold_sell),
        }
    finally:
        conn.close()


def _readable_asset_name(path: str) -> str:
    """'/Game/.../Weapons/New_Melee/1H_Little_Spade.1H_Little_Spade_C' -> '1H Little Spade'"""
    if not path:
        return "?"
    last = path.rsplit("/", 1)[-1]
    name = last.split(".", 1)[0]
    return name.replace("_", " ").strip()


def _readable_trader_type(path: str) -> str:
    """'.../Vendors/Mechanic/Mechanic_01/BP_Mechanic.BP_Mechanic_C' -> 'Mechanic'"""
    if not path:
        return "?"
    parts = path.split("/")
    if "Vendors" in parts:
        idx = parts.index("Vendors")
        if idx + 1 < len(parts):
            return parts[idx + 1].replace("_", " ")
    return "?"


def get_special_deals(limit_per_sector: int = 8) -> dict:
    """Aktuelle Sonderangebote je Sektor (z.B. 'A0'), mit lesbarem Item- und
    Haendlertyp-Namen. Gruppiert als {sector: [ {trader, item, price, amount} ]}."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT sector, tradeable_asset, base_purchase_price, amount_in_store, trader "
            "FROM economy_special_deals WHERE can_be_purchased_by_player = 1 "
            "ORDER BY sector, base_purchase_price DESC"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    grouped: dict[str, list] = {}
    for sector, asset, price, amount, trader in rows:
        grouped.setdefault(sector, [])
        if len(grouped[sector]) >= limit_per_sector:
            continue
        grouped[sector].append({
            "item": _readable_asset_name(asset),
            "trader": _readable_trader_type(trader),
            "price": price,
            "amount": amount,
        })
    return grouped


if __name__ == "__main__":
    print("Spieler gesamt:", get_total_players())
    print("Aktive Squads:", get_active_squads())
    print("Wirtschaft:", get_economy_summary())
    print("Sonderangebote:", get_special_deals())
