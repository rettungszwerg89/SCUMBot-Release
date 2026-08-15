# Zentrale Konfiguration fuer den SCUM Discord Bot
# Trag hier alle IDs/Einstellungen ein. Echte Zugangsdaten (Passwoerter, Tokens)
# stehen NICHT hier drin, sondern in secrets.ini (siehe unten) - so kannst du
# config.py z.B. jemandem zeigen/teilen, ohne Passwoerter preiszugeben, und
# musst nach einem "frischen" config.py-Update nie wieder Zugangsdaten neu eintippen.

import os


def _load_secrets() -> dict:
    """Liest einfache KEY=WERT-Zeilen aus secrets.ini (im selben Ordner wie
    config.py). Zeilen mit '#' am Anfang oder leere Zeilen werden ignoriert.
    Versehentliche Anfuehrungszeichen um den Wert werden automatisch entfernt
    (secrets.ini braucht KEINE Anfuehrungszeichen, anders als Python-Code)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secrets.ini")
    result = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                result[key] = value
    else:
        print(f"WARNUNG: {path} nicht gefunden - lege sie an (siehe secrets.ini.example)!")
    return result


_secrets = _load_secrets()


def _secret(key: str, default: str = "") -> str:
    value = _secrets.get(key, default)
    if value == default and default.startswith("TODO"):
        print(f"WARNUNG: '{key}' fehlt in secrets.ini - trag den echten Wert dort ein.")
    return value


# Alle Zustandsdateien (JSON/TXT, die der Bot selbst schreibt) liegen in data/,
# damit der Hauptordner nicht mehr zumuellt. Wird beim Start automatisch angelegt.
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)


def _data(filename: str) -> str:
    return os.path.join(DATA_DIR, filename)


ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _assets(*parts: str) -> str:
    return os.path.join(ASSETS_DIR, *parts)


def _load_settings() -> dict:
    """Liest data/server_settings.json: nicht-geheime, aber installationsspezifische
    Werte (Channel-IDs, Server-Pfade, AMP-Nutzung, ...). Wird ueber den
    Web-Setup-Assistenten (/setup) geschrieben, nicht von Hand editiert."""
    path = _data("server_settings.json")
    if os.path.exists(path):
        import json
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


_settings = _load_settings()


def _setting(key: str, default):
    return _settings.get(key, default)


# --- Discord ---
DISCORD_BOT_TOKEN = _secret("DISCORD_BOT_TOKEN", "TODO_DISCORD_BOT_TOKEN")
STATUS_CHANNEL_ID = _setting("STATUS_CHANNEL_ID", 0)   # Channel, in dem der Status-Embed gepostet/aktualisiert wird
CHAT_CHANNEL_ID = _setting("CHAT_CHANNEL_ID", 0)       # Channel, in den der Ingame-Chat gespiegelt wird

# --- AMP (optional - SCUM Instanz, NICHT der Controller!) ---
# Ohne AMP funktionieren alle Spielaktionen trotzdem (laufen ueber den Lua-Mod).
# Nur die Online/Spieleranzahl-Anzeige nutzt sonst eine Steam-A2S-Abfrage (s.u.).
AMP_ENABLED = _setting("AMP_ENABLED", False)
AMP_URL = _setting("AMP_URL", "http://localhost:8081")
AMP_USER = _secret("AMP_USER", "TODO_AMP_BENUTZERNAME")
AMP_PASSWORD = _secret("AMP_PASSWORD", "TODO_AMP_PASSWORT")

# --- Steam-A2S-Abfrage (Server-Status ohne AMP) ---
STEAM_QUERY_HOST = _setting("STEAM_QUERY_HOST", "")
STEAM_QUERY_PORT = _setting("STEAM_QUERY_PORT", 0)

# --- Aktualisierungsintervall ---
STATUS_UPDATE_SECONDS = 30

# --- Bild/GIF, das unter dem Status-Embed angezeigt wird ---
STATUS_GIF_PATH = _assets("gifs", "welt.gif")

# --- SCUM Save-Datenbank (fuer Spieler gesamt, Squads etc.) - im Setup-Assistenten eintragen ---
SCUM_DB_PATH = _setting("SCUM_DB_PATH", "")

# --- Max. Dateigroesse fuer Discord-Anhaenge (Standard-Limit ohne Server-Boost: 8 MB) ---
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024

# --- SCUM Logs-Ordner (fuer Chat-Reader) - im Setup-Assistenten eintragen ---
SCUM_LOGS_PATH = _setting("SCUM_LOGS_PATH", "")

# --- Feste, taegliche Neustart-Zeiten (24h-Format, Stunde) ---
RESTART_HOURS = [0, 6, 12, 18]
RESTART_WARNING_MINUTES = [30, 15, 5, 3, 2, 1]   # Wann ingame gewarnt wird
RESTART_WARNING_CHECK_SECONDS = 20
# Ordner des ScumBot UE4SS-Mods auf dem SCUM-Server (im Setup-Assistenten eintragen,
# z.B. ...\SCUM\Binaries\Win64\ue4ss\Mods\ScumBot) - alle Dateien darin abgeleitet.
SCUM_MOD_DIR = _setting("SCUM_MOD_DIR", "")
TAXI_MOD_COMMANDS_FILE = os.path.join(SCUM_MOD_DIR, "commands.txt") if SCUM_MOD_DIR else ""
TAXI_COMMANDS_FILE = TAXI_MOD_COMMANDS_FILE
LIVE_POSITIONS_FILE = os.path.join(SCUM_MOD_DIR, "live_positions.txt") if SCUM_MOD_DIR else ""
VEHICLE_POSITIONS_FILE = os.path.join(SCUM_MOD_DIR, "vehicle_positions.txt") if SCUM_MOD_DIR else ""
ITEM_CHECK_RESULTS_FILE = os.path.join(SCUM_MOD_DIR, "item_check_results.txt") if SCUM_MOD_DIR else ""

# --- Bunker-Status-Feature ---
BUNKER_CHANNEL_ID = _setting("BUNKER_CHANNEL_ID", 0)
BUNKER_GIF_PATH = _assets("gifs", "bunker.gif")
BUNKER_ACTIVE_DURATION_HOURS = 24   # Wie lange ein Bunker aktiv/offen bleibt (SCUM-Standard)
BUNKER_CHECK_SECONDS = 60           # Wie oft die Logs auf Bunker-Aenderungen geprueft werden
BUNKER_MAP_BASE_URL = "https://scum-map.com/en/map/bunkers_and_killboxes"
# Feste, bestaetigte Kartenlinks je Bunker (ueberschreiben die berechneten Koordinaten)
BUNKER_MAP_LINKS = {
    "A1": "https://scum-map.com/en/map/bunkers_and_killboxes/layer/1CQE2beUNZ6FzcrBbL2bER",
    "A3": "https://scum-map.com/en/map/bunkers_and_killboxes/layer/1CQE2beUrVpGM18wCgvaBs",
    "C4": "https://scum-map.com/en/map/bunkers_and_killboxes/layer/1CQE2beTjcGWNoEKLYobM6",
    "D1": "https://scum-map.com/en/map/bunkers_and_killboxes/layer/1CQE2beMZ1aCRrjWnJSqeF",
}
BUNKER_IMAGES_DIR = _assets("bunker")
# Dateiname je Bunker (klein geschrieben, wie im Ordner)
BUNKER_IMAGE_FILES = {
    "A1": "bunker_a1.jpg",
    "A3": "bunker_a3.jpg",
    "C4": "bunker_c4.jpg",
    "D1": "bunker_d1.jpg",
}

# Zuordnung economy_outposts.id -> echter Aussenposten-Name (durch Vorher/
# Nachher-Vergleich beim echten Einkaufen bestaetigt, siehe list_outposts.py)
OUTPOST_NAMES = {
    1: "C2",
    2: "B4",
    3: "A0",
    4: "Z3",
}
OUTPOST_IMAGES_DIR = _assets("aussenposten")
OUTPOST_IMAGE_FILES = {
    "A0": "outpost_a0.jpg",
    "B4": "outpost_b4.jpg",
    "C2": "outpost_c2.jpg",
    "Z3": "outpost_z3.jpg",
}
BUNKER_MAP_ZOOM = "1.5"             # Dritter Wert in der URL, scheint eine feste Zoomstufe zu sein
BUNKER_MESSAGE_STORE = _data("bunker_message_id.txt")
BUNKER_STATUS_JSON = _data("bunker_status.json")   # fuer die Webseite

# --- Leaderboard-Feature ---
LEADERBOARD_ALLTIME_CHANNEL_ID = _setting("LEADERBOARD_ALLTIME_CHANNEL_ID", 0)
LEADERBOARD_WEEKLY_CHANNEL_ID = _setting("LEADERBOARD_WEEKLY_CHANNEL_ID", 0)
LEADERBOARD_ALLTIME_GIF_PATH = _assets("gifs", "allzeit.gif")
LEADERBOARD_WEEKLY_GIF_PATH = _assets("gifs", "wöchentlich.gif")
LEADERBOARD_TOP_N = 3                       # Wie viele Plaetze pro Kategorie angezeigt werden
LEADERBOARD_ALLTIME_UPDATE_SECONDS = 6 * 3600   # Alle 6h aktualisieren
LEADERBOARD_WEEKLY_UPDATE_SECONDS = 3600        # Stuendlich aktualisieren
WEEKLY_RESET_WEEKDAY = 0    # 0 = Montag (Python weekday())
WEEKLY_RESET_HOUR = 0       # Uhrzeit des woechentlichen Resets
WEEKLY_SNAPSHOT_FILE = _data("weekly_snapshot.json")
ALLTIME_MESSAGE_STORE = _data("alltime_message_id.txt")
WEEKLY_MESSAGE_STORE = _data("weekly_message_id.txt")

# --- Konto-Panel ---
BALANCE_PANEL_CHANNEL_ID = _setting("BALANCE_PANEL_CHANNEL_ID", 0)
BALANCE_PANEL_MESSAGE_STORE = _data("balance_panel_message_id.txt")

# --- Shop ---
SHOP_CHANNEL_ID = _setting("SHOP_CHANNEL_ID", 0)
SHOP_PANEL_MESSAGE_STORE = _data("shop_panel_message_id.txt")
SHOP_ITEMS_FILE = _data("shop_items.json")
SHOP_CATEGORIES = ["Fahrzeuge", "Waffen", "Ausrüstung", "Kleidung", "Medizin", "Verbrauchsgüter", "Sonstiges"]


def get_shop_items() -> list:
    """Liest den Shop-Katalog live aus data/shop_items.json (vom Admin-Webbereich
    bearbeitbar). Wird bei jedem Panel-Update neu gelesen, kein Neustart noetig."""
    import json
    try:
        with open(SHOP_ITEMS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def get_shop_item_by_key(key: str) -> dict | None:
    """Sucht einen einzelnen Artikel im Katalog anhand seines Keys (unabhaengig
    davon, ob er gerade im Shop sichtbar ist). Wird von Tagespaket/Redeem-
    Codes/Paketen/Quests/Toten-Briefkaesten genutzt, damit die dort verwendeten
    Items dieselben (bereits getesteten) type/id-Werte wie der Shop haben."""
    return next((i for i in get_shop_items() if i.get("key") == key), None)


def get_purchasable_shop_items() -> list:
    """Wie get_shop_items(), aber nur Artikel, die aktuell im Shop sichtbar/
    kaeuflich sind (shop_visible=True, Standard fuer bestehende Artikel ohne
    das Feld). Quests/Briefkaesten/Pakete/Weltereignisse duerfen weiterhin auf
    den vollen Katalog zugreifen, auch wenn ein Artikel gerade nicht im Shop
    steht - nur die tatsaechliche Kauf-Ansicht wird gefiltert."""
    return [i for i in get_shop_items() if i.get("shop_visible", True)]


def get_shop_subcategories(category: str) -> list:
    """Sortierte Liste der Unterkategorien einer Kategorie (z.B. 'Pistolen',
    'Schrotflinten' innerhalb 'Waffen') - nur wenn dort ueberhaupt welche
    gepflegt sind, sonst leere Liste (Kategorie bleibt dann flach wie bisher)."""
    items = [i for i in get_purchasable_shop_items() if i.get("category", "Sonstiges") == category]
    if not any(i.get("subcategory") for i in items):
        return []
    return sorted({i.get("subcategory") or "Sonstiges" for i in items})


def get_shop_base_items(category: str, subcategory: str | None = None) -> list:
    """Artikel einer Kategorie (optional nach Unterkategorie gefiltert), OHNE
    Zubehoer-Artikel (die haben ein parent_key und erscheinen nur in der
    Detailansicht ihres Basis-Artikels, z.B. Magazin/Munition bei einer Waffe)."""
    items = [i for i in get_purchasable_shop_items() if i.get("category", "Sonstiges") == category]
    if subcategory is not None:
        items = [i for i in items if (i.get("subcategory") or "Sonstiges") == subcategory]
    return [i for i in items if not i.get("parent_key")]


def get_shop_item_accessories(item_key: str) -> list:
    """Artikel, die als Zubehoer zu diesem Basis-Artikel gehoeren (parent_key
    == item_key), z.B. Magazin/Munition zu einer bestimmten Waffe."""
    return [i for i in get_purchasable_shop_items() if i.get("parent_key") == item_key]


# --- Tagespaket (daily) ---
DAILY_PACKAGE_COOLDOWN_HOURS = 24
DAILY_PACKAGE_FILE = _data("daily_package.json")


def get_daily_package_entries() -> list:
    """Liest die Artikel (Key + eigene Menge, unabhaengig vom Shop-Standardwert),
    aus denen sich das Tagespaket zusammensetzt, aus data/daily_package.json
    (im Admin-Webbereich unter 'Tagespaket' editierbar)."""
    import json
    try:
        with open(DAILY_PACKAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# --- Redeem-Codes (createcode) ---
REDEEM_CODES_FILE = _data("redeem_codes.json")

# --- Taxi (Discord-Seite) ---
TAXI_PANEL_CHANNEL_ID = _setting("TAXI_PANEL_CHANNEL_ID", 0)
TAXI_PANEL_MESSAGE_STORE = _data("taxi_panel_message_id.txt")
# Muss mit der DESTINATIONS-Tabelle in ScumBot main.lua uebereinstimmen (Koordinaten)!
# Format: Name -> (X, Y, Z, Preis in Coins)
# Z=5000 als Sicherheitshoehe gesetzt (Original-Werte waren alle Z=0) - bei
# Bedarf pro Ziel einzeln nachjustieren, falls jemand feststeckt/faellt.
TAXI_DESTINATIONS = {
    "Händler Z3":  (24345.7298, -674956.6459, 5000, 750),
    "Händler A0":  (-615444.9001, -555564.8473, 5000, 750),
    "Händler C2":  (-152610.9187, 290780.4085, 5000, 750),
    "Händler B4":  (568791.2967, -225382.5923, 5000, 750),
    "Bunker B3":   (148367.9779, 553321.3426, 5000, 750),
    "Bunker D0":   (-885484.008, 597205.3267, 5000, 750),
    "Bunker C1":   (-396972.1067, 207721.8126, 5000, 750),
    "Bunker B4":   (434801.9531, -6324.6462, 5000, 750),
    "Bunker B0":   (-816553.5265, -98097.9908, 5000, 750),
    "Bunker A2":   (-27830.2734, -330695.5314, 5000, 750),
    "Bunker Z2":   (-212385.7485, -640491.4066, 5000, 750),
    "Bunker Z0":   (-715118.5547, -789904.6922, 5000, 750),
}
ECONOMY_FILE = _data("economy.json")
ECONOMY_SNAPSHOT_FILE = _data("economy_snapshot.json")
ECONOMY_CHECK_SECONDS = 300   # Alle 5 Minuten pruefen/gutschreiben
COINS_PER_ONLINE_MINUTE = 1   # Wie viele Coins pro Online-Minute
ONLINE_PLAYERS_FILE = os.path.join(SCUM_MOD_DIR, "online_players.txt") if SCUM_MOD_DIR else ""

# Coins pro Aktivitaets-Einheit (Differenz seit letzter Pruefung * Wert)
ACTIVITY_COIN_RATES = {
    "kills": 3,
    "headshots": 5,
    "puppets_killed": 1,
    "animals_killed": 1,
    "fish_caught": 2,
    "locks_picked": 2,
}

# --- Lotterie ---
LOTTERY_CHANNEL_ID = _setting("LOTTERY_CHANNEL_ID", 0)
LOTTERY_PANEL_MESSAGE_STORE = _data("lottery_panel_message_id.txt")
LOTTERY_FILE = _data("lottery.json")
LOTTERY_TICKET_PRICE = 100
LOTTERY_DRAW_INTERVAL_HOURS = 24
LOTTERY_WIN_CHANCE = 0.5   # Wahrscheinlichkeit, dass eine Ziehung ueberhaupt einen Gewinner hat (0.0-1.0)
LOTTERY_CHECK_SECONDS = 300   # wie oft geprueft wird, ob die Ziehung faellig ist
LOTTERY_REFRESH_MINUTES = 5   # wie oft das Panel (Pot/Timer) aktualisiert wird

# --- Voting-Belohnung (top-games.net) ---
TOPGAMES_TOKEN = _secret("TOPGAMES_TOKEN", "TODO_TOPGAMES_TOKEN")
TOPGAMES_RANKING_URL = f"https://api.top-games.net/v1/servers/{TOPGAMES_TOKEN}/players-ranking"
VOTE_REWARD_COINS = 200   # pro Abstimmung
VOTE_CHECK_SECONDS = 600  # alle 10 Minuten pruefen
VOTE_TRACKING_FILE = _data("topgames_votes.json")
KILLFEED_CHANNEL_ID = _setting("KILLFEED_CHANNEL_ID", 0)
KILLFEED_CHECK_SECONDS = 10
KILL_MAP_IMAGE_PATH = _assets("karte", "map.png")
KILL_MAP_CROP_SIZE = 220   # Breite/Hoehe des Kartenausschnitts in Original-Pixeln um den Marker
KILLFEED_LOG_JSON = _data("killfeed_log.json")   # fuer die Webseite (letzte N Kills)
KILLFEED_LOG_MAX_ENTRIES = 50
KILL_HEATMAP_POINTS_FILE = _data("kill_heatmap_points.json")   # separat & hoeher limitiert, fuer die Heatmap
KILL_HEATMAP_MAX_POINTS = 5000


def get_kill_heatmap_points() -> list:
    """Liest die gespeicherten Kill-Koordinaten fuer die Heatmap."""
    import json
    try:
        with open(KILL_HEATMAP_POINTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
CHAT_LOG_JSON = _data("chat_log.json")           # fuer die Webseite (letzte N Chat-Nachrichten)
CHAT_LOG_MAX_ENTRIES = 100

# --- Admin-Aktivitätsprotokoll (wer hat wann was ueber Bot/Webapp ausgeloest) ---
ACTIVITY_LOG_FILE = _data("activity_log.json")
ACTIVITY_LOG_MAX_ENTRIES = 1000

# --- Account-Verknuepfung ---
ACCOUNT_PANEL_CHANNEL_ID = _setting("ACCOUNT_PANEL_CHANNEL_ID", 0)
ACCOUNT_LINKS_FILE = _data("account_links.json")
REGISTRATION_CODE_TIMEOUT_MINUTES = 10
ACCOUNT_PANEL_MESSAGE_STORE = _data("account_panel_message_id.txt")
ACCOUNT_PANEL_GIF_PATH = _assets("gifs", "Accountverknüpfung.gif")

# --- Tote Briefkaesten & Quests: gemeinsamer Panel-Channel ---
DEAD_DROPS_QUESTS_CHANNEL_ID = _setting("DEAD_DROPS_QUESTS_CHANNEL_ID", 0)
DEAD_DROPS_QUESTS_PANEL_MESSAGE_STORE = _data("dead_drops_quests_panel_message_id.txt")

# --- Freund werben (Erweiterung des Onboardings) ---
REFERRAL_BONUS_COINS = 300   # Bonus fuer Werber UND Geworbenen, je einmalig

# --- Item-Erkennung (Tote Briefkaesten/Quests) ---
ITEM_CHECK_TIMEOUT_SECONDS = 12   # wie lange auf die Lua-Antwort gewartet wird
ITEM_CHECK_POLL_SECONDS = 1

# --- Tote Briefkaesten ---
DEAD_DROPS_FILE = _data("dead_drops.json")


def get_dead_drops() -> list:
    import json
    try:
        with open(DEAD_DROPS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def get_dead_drop_by_key(key: str) -> dict | None:
    return next((d for d in get_dead_drops() if d.get("key") == key), None)

# --- Quests ---
QUESTS_FILE = _data("quests.json")
QUEST_PROGRESS_FILE = _data("quest_progress.json")


def get_quests() -> list:
    import json
    try:
        with open(QUESTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def get_quest_by_key(key: str) -> dict | None:
    return next((q for q in get_quests() if q.get("key") == key), None)

# --- Weltereignisse ---
WORLD_EVENT_CHANNEL_ID = _setting("WORLD_EVENT_CHANNEL_ID", 0)
WORLD_EVENT_LOCATIONS_FILE = _data("world_event_locations.json")
WORLD_EVENT_STATE_FILE = _data("world_event_state.json")
WORLD_EVENT_CHECK_SECONDS = 60
WORLD_EVENT_MIN_INTERVAL_MINUTES = 45     # Mindestzeit, bevor der Ort erneut wechselt
WORLD_EVENT_MAX_INTERVAL_MINUTES = 90
WORLD_EVENT_LOOT_INTERVAL_MINUTES = 15    # wie oft (max) ein Loot-Abwurf stattfindet
WORLD_EVENT_HIGH_POP_PLAYER_COUNT = 6     # ab wie vielen Spielern im Gebiet "hohe Spielerzahl" gilt
WORLD_EVENT_KILL_BONUS_COINS = 50
WORLD_EVENT_DEATH_BONUS_COINS = 10


def get_world_event_locations() -> list:
    import json
    try:
        with open(WORLD_EVENT_LOCATIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


WORLD_EVENT_LOOT_FILE = _data("world_event_loot.json")


def get_world_event_loot_entries() -> list:
    """Artikel (Key + eigene Menge, unabhaengig vom Shop-Standardwert), aus
    denen Weltereignis-Loot zufaellig gezogen wird."""
    import json
    try:
        with open(WORLD_EVENT_LOOT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

# --- Datei, in der die Message-ID des Status-Embeds gespeichert wird,
#     damit der Bot nach einem Neustart dieselbe Nachricht weiter bearbeitet
#     statt eine neue zu posten. ---
STATUS_MESSAGE_STORE = _data("status_message_id.txt")

# --- Mech/Sentry-Zeitplan (Sonntags aus, unter der Woche an) - Pfade im Setup-Assistenten eintragen ---
SERVER_SETTINGS_PATH = _setting("SERVER_SETTINGS_PATH", "")
ADMIN_USERS_PATH = _setting("ADMIN_USERS_PATH", "")
MECH_OFF_WEEKDAY = 6         # Python weekday(): Montag=0 ... Sonntag=6
MECH_SCHEDULE_HOUR = 23      # Kurz vor dem 00:00-Neustart pruefen/umstellen
MECH_SCHEDULE_MINUTE = 55
MECH_SCHEDULE_STATE_FILE = _data("mech_schedule_last_run.txt")

# --- Webseite (Flask) ---
SERVER_NAME = _setting("SERVER_NAME", "Mein SCUM-Server")   # Anzeigename auf der Webseite
DEFAULT_SUPPORT_URL = "https://www.paypal.com/paypalme/rettungszwerg"
SUPPORT_URL = _setting("SUPPORT_URL", DEFAULT_SUPPORT_URL)   # Spenden-Link, im Setup-Assistenten aenderbar/entfernbar
WEBAPP_PORT = 5000
WEBAPP_SECRET_KEY = _secret("WEBAPP_SECRET_KEY", "TODO_ZUFAELLIGER_LANGER_STRING")
WEBAPP_PUBLIC_URL = _setting("WEBAPP_PUBLIC_URL", "http://localhost:5000")

# Discord OAuth2 (Developer Portal -> deine App -> OAuth2 -> Client ID / Client Secret)
DISCORD_CLIENT_ID = _secret("DISCORD_CLIENT_ID", "TODO_CLIENT_ID")
DISCORD_CLIENT_SECRET = _secret("DISCORD_CLIENT_SECRET", "TODO_CLIENT_SECRET")
DISCORD_OAUTH_REDIRECT_URI = WEBAPP_PUBLIC_URL + "/callback"

# Admin-Bereich
ADMIN_PASSWORD = _secret("ADMIN_PASSWORD", "TODO_SICHERES_PASSWORT")   # TODO: aendern!
ADMIN_PLAYER_NAME = _setting("ADMIN_PLAYER_NAME", "")   # dein Ingame-Admin-Charaktername (fuer die Admin-Konsole)
ADMIN_LIST_LOCK_FILE = _data("admin_list.lock")   # verhindert Race Conditions bei gleichzeitigen Kaeufen
