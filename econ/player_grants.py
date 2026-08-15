# Direkter Schreibzugriff auf fame_points (user_profile) und das Bankguthaben
# fuer die "Geld & Ruhm vergeben"-Funktion der Live-Karte sowie Toter-Briefkasten-
# /Quest-Belohnungen. SCUM.db laeuft im WAL-Modus (parallele Lese-/Schreib-
# zugriffe grundsaetzlich moeglich), analog zu elevation.py.
#
# WICHTIG: user_profile.money_balance ist in aktuellen SCUM-Versionen NICHT
# mehr das Feld, das am Bankautomaten/Telefon angezeigt wird - das echte
# Guthaben steckt in bank_account_registry_currencies.account_balance
# (verknuepft ueber bank_account_registry.account_owner_user_profile_id).
# currency_type=1 ist die normale Waehrung (Dollar).
#
# Der laufende SCUM-Server haelt Bankguthaben/Ruhm eines online Spielers im
# Arbeitsspeicher (ConZPlayerController) und liest die DB waehrend der Session
# nicht neu ein - ein reiner DB-Schreibzugriff kommt also nie live an (erst
# nach Server-Neustart, und riskiert dabei sogar von einem Auto-Save
# ueberschrieben zu werden). Deshalb wird zusaetzlich ein GRANT_CURRENCY-/
# GRANT_FAME-Kommando an den ScumBot-Mod geschickt, der - falls der
# Spieler online ist - SetCurrencyBalanceRep()/SetFamePoints() direkt auf
# dessen PlayerController aufruft (per UE4SS-Objekt-Dump ermittelt). Das ist
# best-effort: ist der Spieler offline, greift nur der DB-Schreibzugriff.
#
# VORSICHT: Schreibzugriff auf eine DB, die der laufende Server ebenfalls
# offen haelt - nur fuer kontrollierte Admin-Aktionen verwenden.

import sqlite3
import config

NORMAL_CURRENCY_TYPE = 1


def _connect_write():
    return sqlite3.connect(config.SCUM_DB_PATH, timeout=5)


def _queue_live_update(command: str):
    try:
        with open(config.TAXI_COMMANDS_FILE, "a", encoding="utf-8") as f:
            f.write(command + "\n")
    except OSError:
        pass


def grant_money_and_fame(
    steam_id: str, money_delta: int = 0, fame_delta: int = 0, player_name: str | None = None
) -> bool:
    """Erhoeht das Bankguthaben (echtes Feld: bank_account_registry_currencies)
    und fame_points um die angegebenen Deltas (negative Werte ziehen ab, nie
    unter 0), und stoesst - falls player_name angegeben ist - eine Live-
    Aktualisierung im laufenden Spiel an. Gibt False zurueck, wenn keine
    passende SteamID gefunden wurde oder (bei money_delta != 0) der Spieler
    noch kein Bankkonto hat."""
    conn = _connect_write()
    try:
        profile_row = conn.execute(
            "SELECT id, fame_points FROM user_profile WHERE user_id = ?", (steam_id,)
        ).fetchone()
        if profile_row is None:
            return False
        profile_id, current_fame = profile_row

        new_fame = None
        if fame_delta:
            new_fame = max(0, (current_fame or 0) + fame_delta)
            conn.execute("UPDATE user_profile SET fame_points = ? WHERE id = ?", (new_fame, profile_id))

        money_ok = True
        new_balance = None
        if money_delta:
            money_ok = False
            account_row = conn.execute(
                "SELECT id FROM bank_account_registry WHERE account_owner_user_profile_id = ?",
                (profile_id,),
            ).fetchone()
            if account_row:
                bank_account_id = account_row[0]
                current_row = conn.execute(
                    "SELECT account_balance FROM bank_account_registry_currencies "
                    "WHERE bank_account_id = ? AND currency_type = ?",
                    (bank_account_id, NORMAL_CURRENCY_TYPE),
                ).fetchone()
                current_balance = current_row[0] if current_row and current_row[0] is not None else 0
                new_balance = max(0, current_balance + money_delta)
                if current_row:
                    cur = conn.execute(
                        "UPDATE bank_account_registry_currencies SET account_balance = ? "
                        "WHERE bank_account_id = ? AND currency_type = ?",
                        (new_balance, bank_account_id, NORMAL_CURRENCY_TYPE),
                    )
                    money_ok = cur.rowcount > 0
                else:
                    conn.execute(
                        "INSERT INTO bank_account_registry_currencies "
                        "(map_id, bank_account_id, currency_type, account_balance) VALUES (1, ?, ?, ?)",
                        (bank_account_id, NORMAL_CURRENCY_TYPE, new_balance),
                    )
                    money_ok = True

        conn.commit()

        if player_name:
            if new_balance is not None:
                _queue_live_update(f"GRANT_CURRENCY|{player_name}|{NORMAL_CURRENCY_TYPE}|{new_balance}")
            if new_fame is not None:
                _queue_live_update(f"GRANT_FAME|{player_name}|{new_fame}")

        return money_ok
    finally:
        conn.close()
