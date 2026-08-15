# SCUM Bot Webseite - oeffentliche Spieler-Seiten + Admin-Bereich.
# Laeuft als eigener Prozess neben bot.py, liest dieselben Datenquellen
# (SCUM.db read-only, data/*.json), schreibt nur in shop_items.json (Admin-Shop).

import os
import sys
import glob
import json
import re
import time
import threading
import secrets
from functools import wraps
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
SECRETS_INI_PATH = os.path.join(PROJECT_ROOT, "secrets.ini")

from flask import Flask, render_template, redirect, url_for, session, request, abort, send_from_directory, jsonify
from werkzeug.utils import secure_filename
import requests

import config
from dbdata import leaderboard_stats
from dbdata import leaderboard_snapshot
import account_links
from econ import redeem_codes
from econ import economy
from services import admin_file
from services import map_image
from econ import economy_online
from econ import player_grants
from econ import world_event
from services.amp_client import AMPClient
from services import steam_query
from dbdata import scum_db
from services import activity_log

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
SHOP_IMAGES_DIR = os.path.join(STATIC_DIR, "shop_images")
os.makedirs(SHOP_IMAGES_DIR, exist_ok=True)
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

app = Flask(__name__)
app.secret_key = config.WEBAPP_SECRET_KEY


@app.context_processor
def inject_asset_version():
    """Haengt an Static-Dateien (style.css) einen ?v=<mtime>-Parameter an, damit
    Browser (v.a. mobil) nach Aenderungen nicht die alte, gecachte Version
    weiterverwenden."""
    def asset_version(filename):
        try:
            return int(os.path.getmtime(os.path.join(STATIC_DIR, filename)))
        except OSError:
            return 0
    return {"asset_version": asset_version}


DISCORD_API = "https://discord.com/api"

_amp_status_cache = {"data": None, "at": 0}


def _get_server_status():
    """Serverstatus mit 15s-Cache, damit nicht jeder Seitenaufruf eine neue
    Abfrage ausloest. Nutzt AMP wenn konfiguriert, sonst eine generische
    Steam-A2S-Abfrage (ohne 'fps', das liefert nur AMP). Gibt None zurueck,
    wenn nichts erreichbar ist."""
    now = time.time()
    if _amp_status_cache["data"] and now - _amp_status_cache["at"] < 15:
        return _amp_status_cache["data"]

    if not config.AMP_ENABLED:
        info = steam_query.query(config.STEAM_QUERY_HOST, config.STEAM_QUERY_PORT)
        if info is None:
            return _amp_status_cache["data"]
        result = {
            "online": info["online"],
            "players": info["players"],
            "max_players": info["max_players"],
            "fps": None,
            "uptime": None,
        }
        _amp_status_cache["data"] = result
        _amp_status_cache["at"] = now
        return result

    try:
        amp = AMPClient(config.AMP_URL, config.AMP_USER, config.AMP_PASSWORD)
        if not amp.login():
            return _amp_status_cache["data"]
        status = amp.get_status()
        metrics = status.get("Metrics", {})
        result = {
            "online": status.get("State") == 20,
            "players": metrics.get("Active Users", {}).get("RawValue", 0),
            "max_players": metrics.get("Active Users", {}).get("MaxValue", 0),
            "fps": metrics.get("FPS", {}).get("RawValue", 0),
            "uptime": status.get("Uptime"),
        }
        _amp_status_cache["data"] = result
        _amp_status_cache["at"] = now
        return result
    except Exception as e:
        print(f"[webapp] AMP-Status Fehler: {e}")
        return _amp_status_cache["data"]


@app.context_processor
def inject_server_status():
    return {
        "server_status": _get_server_status(),
        "server_name": config.SERVER_NAME,
        "support_url": config.SUPPORT_URL,
    }


# ===================== Hilfsfunktionen (Ranking, wiederverwendet aus dem Bot-Konzept) =====================

def _format_stat_value(fmt: str, value: float) -> str:
    if fmt == "int":
        return f"{int(round(value))}"
    if fmt == "float2":
        return f"{value:.2f}"
    if fmt == "percent":
        return f"{value * 100:.1f}%"
    if fmt == "meters":
        return f"{value:.1f}m"
    if fmt == "km":
        return f"{value / 1000:.1f} km"
    if fmt == "hours":
        return f"{value / 60:.1f}h"
    if fmt == "money":
        return f"{int(round(value))} credits"
    return str(value)


def _rank_stat(stat_def, current, baseline=None, top_n=5):
    scored = []
    for uid, p in current.items():
        base = (baseline or {}).get(uid, {})
        if stat_def["kind"] == "ratio":
            if baseline is None:
                num, den = p.get(stat_def["num_column"], 0), p.get(stat_def["den_column"], 0)
            else:
                num = max(0, p.get(stat_def["num_column"], 0) - base.get(stat_def["num_column"], 0))
                den = max(0, p.get(stat_def["den_column"], 0) - base.get(stat_def["den_column"], 0))
            if not den:
                continue
            value = num / den
        else:
            cur_val = p.get(stat_def["column"], 0)
            value = cur_val if baseline is None else max(0, cur_val - base.get(stat_def["column"], 0))
        if not value or value <= 0:
            continue
        scored.append((value, p["name"]))
    scored.sort(reverse=True)
    return [
        {"rank": i + 1, "name": name, "value": _format_stat_value(stat_def["fmt"], value)}
        for i, (value, name) in enumerate(scored[:top_n])
    ]


STAT_CATEGORIES = [
    {
        "name": "Kampf",
        "stats": [
            {"id": "kills", "label": "Top Kills", "kind": "counter", "column": "kills", "fmt": "int"},
            {"id": "deaths", "label": "Top Tode", "kind": "counter", "column": "deaths", "fmt": "int"},
            {"id": "kd", "label": "Top K/D-Verhältnis", "kind": "ratio", "num_column": "kills", "den_column": "deaths", "fmt": "float2"},
            {"id": "pvp_kills", "label": "Top PvP-Kills", "kind": "counter", "column": "prisoner_kills", "fmt": "int"},
            {"id": "headshots", "label": "Top Kopfschüsse", "kind": "counter", "column": "headshots", "fmt": "int"},
            {"id": "accuracy", "label": "Top Treffsicherheit", "kind": "ratio", "num_column": "shots_hit", "den_column": "shots_fired", "fmt": "percent"},
            {"id": "puppets", "label": "Top Puppet-Kills", "kind": "counter", "column": "puppets_killed", "fmt": "int"},
            {"id": "longest_kill", "label": "Top Scharfschützen-Distanz", "kind": "counter", "column": "longest_kill_distance", "fmt": "meters"},
        ],
    },
    {
        "name": "Überleben",
        "stats": [
            {"id": "survived", "label": "Top Überlebenszeit", "kind": "counter", "column": "minutes_survived", "fmt": "hours"},
            {"id": "distance", "label": "Top Distanz zu Fuß", "kind": "counter", "column": "distance_travelled_by_foot", "fmt": "km"},
            {"id": "locks", "label": "Top Schlösser geknackt", "kind": "counter", "column": "locks_picked", "fmt": "int"},
        ],
    },
    {
        "name": "Jagd & Angeln",
        "stats": [
            {"id": "animals", "label": "Top Tierkills", "kind": "counter", "column": "animals_killed", "fmt": "int"},
            {"id": "fish", "label": "Top Fische", "kind": "counter", "column": "fish_caught", "fmt": "int"},
        ],
    },
    {
        "name": "Sonstiges",
        "stats": [
            {"id": "fame", "label": "Top Ruhm", "kind": "counter", "column": "fame_points", "fmt": "int"},
        ],
    },
]
STAT_DEFS_PUBLIC = [s for cat in STAT_CATEGORIES for s in cat["stats"]]


# ===================== Auth-Hilfsfunktionen =====================

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "discord_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper


# ===================== Oeffentliche Seiten =====================

def _next_restart_datetime():
    from datetime import timedelta
    now = datetime.now()
    candidates = []
    for h in config.RESTART_HOURS:
        candidate = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        candidates.append(candidate)
    return min(candidates)


def _find_hero_banner() -> str | None:
    """Sucht static/hero_banner.{jpg,jpeg,png,webp} - so muss das Bild nur mit
    diesem Namen (egal welche Endung) in webapp/static/ abgelegt werden."""
    for ext in ("jpg", "jpeg", "png", "webp"):
        filename = f"hero_banner.{ext}"
        if os.path.exists(os.path.join(STATIC_DIR, filename)):
            return filename
    return None


@app.route("/")
def home():
    try:
        current = leaderboard_stats.get_current_player_data()
        current = {str(uid): p for uid, p in current.items()}
        squads_data = leaderboard_stats.get_current_squad_data()
    except Exception as e:
        print(f"[webapp] SCUM.db nicht erreichbar (SCUM_DB_PATH in /setup pruefen?): {e}")
        current, squads_data = {}, {}
    top_squads = sorted(squads_data.values(), key=lambda s: s.get("score", 0), reverse=True)[:5]
    top_players = _rank_stat(
        {"kind": "counter", "column": "fame_points", "fmt": "int"}, current, top_n=10
    )

    next_restart = _next_restart_datetime()

    categories = []
    for cat in STAT_CATEGORIES:
        boards = [
            {"label": d["label"], "entries": _rank_stat(d, current)}
            for d in cat["stats"]
        ]
        categories.append({"name": cat["name"], "boards": boards})

    eco = economy._load()
    total_coins = sum(v.get("balance", 0) for v in eco.values())

    try:
        weather = scum_db.get_weather()
    except Exception as e:
        print(f"[webapp] Wetter-DB Fehler: {e}")
        weather = None

    return render_template(
        "home.html",
        user=_current_user(),
        total_players=len(current),
        active_squads=len(squads_data),
        top_squads=top_squads,
        top_players=top_players,
        next_restart=next_restart,
        categories=categories,
        total_coins=total_coins,
        weather=weather,
        hero_banner=_find_hero_banner(),
        recent_chat=_load_chat_log()[-8:],
    )


@app.route("/wirtschaft")
def wirtschaft():
    eco_coins = economy._load()
    links = account_links._load_links()
    discord_to_name = {str(k): v.get("player_name", "?") for k, v in links.items()}

    rows = []
    for discord_id, entry in eco_coins.items():
        name = discord_to_name.get(str(discord_id), f"Discord-ID {discord_id}")
        rows.append({"name": name, "balance": entry.get("balance", 0)})
    rows.sort(key=lambda r: r["balance"], reverse=True)
    total_coins = sum(r["balance"] for r in rows)

    try:
        summary = scum_db.get_economy_summary()
        deals = scum_db.get_special_deals()
        outposts = scum_db.get_outposts_detail()
    except Exception as e:
        print(f"[webapp] Wirtschafts-DB Fehler: {e}")
        summary, deals, outposts = None, {}, []

    return render_template(
        "wirtschaft.html", rows=rows[:20], total_coins=total_coins,
        summary=summary, deals=deals, outposts=outposts, user=_current_user(),
        online_rate=config.COINS_PER_ONLINE_MINUTE,
        activity_rates=config.ACTIVITY_COIN_RATES,
        vote_reward=config.VOTE_REWARD_COINS,
    )


@app.route("/events")
def events():
    return render_template("events.html", user=_current_user())


@app.route("/leaderboard")
def leaderboard():
    period = request.args.get("period", "alltime")
    current = leaderboard_stats.get_current_player_data()
    current = {str(uid): p for uid, p in current.items()}

    baseline = None
    if period == "weekly":
        snap = leaderboard_snapshot.get_baseline()
        baseline = snap.get("players", {})

    top_players = _rank_stat(
        {"kind": "counter", "column": "fame_points", "fmt": "int"}, current, baseline, top_n=10
    )

    categories = []
    for cat in STAT_CATEGORIES:
        boards = [
            {"label": d["label"], "entries": _rank_stat(d, current, baseline)}
            for d in cat["stats"]
        ]
        categories.append({"name": cat["name"], "boards": boards})

    return render_template(
        "leaderboard.html", top_players=top_players, categories=categories, period=period, user=_current_user()
    )


@app.route("/shop")
def shop():
    items = config.get_purchasable_shop_items()
    grouped = {}
    for item in items:
        cat = item.get("category", "Sonstiges")
        grouped.setdefault(cat, []).append(item)
    ordered_groups = [(cat, grouped[cat]) for cat in config.SHOP_CATEGORIES if cat in grouped]
    return render_template("shop.html", groups=ordered_groups, user=_current_user())


@app.route("/squads")
def squads():
    squads_data = leaderboard_stats.get_current_squad_data()
    rows = sorted(squads_data.values(), key=lambda s: s.get("score", 0), reverse=True)
    return render_template("squads.html", squads=rows, user=_current_user())


LOG_VIEWER_CATEGORIES = {
    "chat": "chat_*.log",
    "gameplay": "gameplay_*.log",
    "kill": "kill_*.log",
    "login": "login_*.log",
    "admin": "admin_*.log",
}


@app.route("/admin/log-viewer")
@admin_required
def admin_log_viewer():
    import glob
    category = request.args.get("category", "chat")
    pattern = LOG_VIEWER_CATEGORIES.get(category, LOG_VIEWER_CATEGORIES["chat"])
    files = glob.glob(os.path.join(config.SCUM_LOGS_PATH, pattern))
    lines = []
    if files:
        latest = max(files, key=os.path.getmtime)
        encoding = economy_online._detect_encoding(latest)
        try:
            with open(latest, "r", encoding=encoding, errors="replace") as f:
                all_lines = f.readlines()
            lines = [l.strip() for l in all_lines[-200:]]
            lines.reverse()
        except Exception as e:
            print(f"[webapp] Log-Viewer Fehler: {e}")

    return render_template(
        "admin_log_viewer.html", lines=lines, category=category,
        categories=list(LOG_VIEWER_CATEGORIES.keys()),
    )


@app.route("/admin/activity-log")
@admin_required
def admin_activity_log():
    source = request.args.get("source") or None
    entries = activity_log.get_entries(source=source, limit=300)
    return render_template("admin_activity_log.html", entries=entries, source=source or "all")


@app.route("/admin/chat", methods=["GET", "POST"])
@admin_required
def admin_chat():
    result = None
    if request.method == "POST":
        sender = request.form.get("sender", "Admin").strip() or "Admin"
        message = request.form.get("message", "").strip()
        if message:
            try:
                with open(config.TAXI_COMMANDS_FILE, "a", encoding="utf-8") as f:
                    f.write(f"DISCORD_CHAT|{sender}: {message}\n")
                result = "Nachricht gesendet."
            except Exception as e:
                result = f"Fehler: {e}"

    try:
        with open(config.CHAT_LOG_JSON, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []
    entries = list(reversed(entries))

    return render_template("admin_chat.html", entries=entries, result=result)


def _load_chat_log() -> list:
    try:
        with open(config.CHAT_LOG_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


@app.route("/api/chat/recent")
def api_chat_recent():
    """Fuer das Live-Chat-Widget auf der Startseite (Polling per JS)."""
    entries = _load_chat_log()[-8:]
    return jsonify(entries)


@app.route("/chat")
def chat_history():
    entries = list(reversed(_load_chat_log()))
    return render_template("chat.html", entries=entries, user=_current_user())


@app.route("/bunker")
def bunker():
    try:
        with open(config.BUNKER_STATUS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"updated_at": None, "bunkers": []}
    return render_template("bunker.html", data=data, user=_current_user())


@app.route("/bunker/image/<filename>")
def bunker_image(filename):
    safe_name = secure_filename(filename)
    return send_from_directory(config.BUNKER_IMAGES_DIR, safe_name)


@app.route("/wirtschaft/image/<filename>")
def outpost_image(filename):
    safe_name = secure_filename(filename)
    return send_from_directory(config.OUTPOST_IMAGES_DIR, safe_name)


@app.route("/killfeed")
def killfeed():
    try:
        with open(config.KILLFEED_LOG_JSON, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []
    entries = list(reversed(entries))
    has_heatmap = len(config.get_kill_heatmap_points()) > 0
    return render_template("killfeed.html", entries=entries, user=_current_user(), has_heatmap=has_heatmap)


@app.route("/killfeed/heatmap.png")
def killfeed_heatmap_image():
    points = config.get_kill_heatmap_points()
    if not points:
        abort(404)
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    out_path = os.path.join(out_dir, "kill_heatmap_web.png")
    image_path = map_image.create_heatmap_image([(p["x"], p["y"]) for p in points], out_path)
    if image_path is None:
        abort(404)
    return send_from_directory(out_dir, "kill_heatmap_web.png")


# ===================== Discord-Login (fuer persoenliche Ansicht) =====================

def _current_user():
    if "discord_id" not in session:
        return None
    return {"id": session["discord_id"], "name": session.get("discord_name")}


@app.route("/login")
def login():
    params = {
        "client_id": config.DISCORD_CLIENT_ID,
        "redirect_uri": config.DISCORD_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify",
    }
    query = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return redirect(f"{DISCORD_API}/oauth2/authorize?{query}")


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return redirect(url_for("home"))

    token_resp = requests.post(
        f"{DISCORD_API}/oauth2/token",
        data={
            "client_id": config.DISCORD_CLIENT_ID,
            "client_secret": config.DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.DISCORD_OAUTH_REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return "Discord-Login fehlgeschlagen.", 400

    user_resp = requests.get(
        f"{DISCORD_API}/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    user_data = user_resp.json()

    session["discord_id"] = user_data["id"]
    session["discord_name"] = user_data.get("username", "?")
    return redirect(url_for("me"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/me")
@login_required
def me():
    discord_id = int(session["discord_id"])
    link = account_links.get_link(discord_id)
    stats = None
    if link:
        stats = leaderboard_stats.get_player_data_by_steam_id(link["steam_id"])
    balance = economy.get_balance(discord_id)
    return render_template("me.html", user=_current_user(), link=link, stats=stats, balance=balance)


# ===================== Admin-Bereich =====================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("password", ""), config.ADMIN_PASSWORD):
            session["is_admin"] = True
            session["admin_name"] = request.form.get("admin_name", "").strip() or "Admin"
            return redirect(url_for("admin_dashboard"))
        error = "Falsches Passwort."
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    session.pop("admin_name", None)
    return redirect(url_for("home"))


def _admin_actor() -> str:
    return session.get("admin_name", "Admin")


# ===================== Setup-Assistent (/setup) =====================
# Ersetzt manuelles Editieren von secrets.ini/config.py fuer neue Installationen.
# Solange noch nicht eingerichtet (kein echter Bot-Token hinterlegt) ist die
# Seite offen erreichbar; danach nur noch fuer eingeloggte Admins (verhindert,
# dass jemand eine laufende Installation ueberschreibt).

SETUP_CHANNEL_FIELDS = [
    ("STATUS_CHANNEL_ID", "Status-Embed"),
    ("CHAT_CHANNEL_ID", "Ingame-Chat-Spiegelung"),
    ("BUNKER_CHANNEL_ID", "Bunker-Status"),
    ("LEADERBOARD_ALLTIME_CHANNEL_ID", "Leaderboard (Gesamt)"),
    ("LEADERBOARD_WEEKLY_CHANNEL_ID", "Leaderboard (Woche)"),
    ("BALANCE_PANEL_CHANNEL_ID", "Konto-Panel"),
    ("SHOP_CHANNEL_ID", "Shop"),
    ("TAXI_PANEL_CHANNEL_ID", "Taxi-Panel"),
    ("LOTTERY_CHANNEL_ID", "Lotterie"),
    ("KILLFEED_CHANNEL_ID", "Killfeed"),
    ("ACCOUNT_PANEL_CHANNEL_ID", "Account-Verknüpfung"),
    ("DEAD_DROPS_QUESTS_CHANNEL_ID", "Tote Briefkästen & Quests"),
    ("WORLD_EVENT_CHANNEL_ID", "Weltereignisse"),
]

SETUP_PATH_FIELDS = [
    ("SCUM_MOD_DIR", r"Ordner des ScumBot-Mods auf dem Server (...\ue4ss\Mods\ScumBot)"),
    ("SCUM_DB_PATH", "Pfad zur SCUM.db"),
    ("SCUM_LOGS_PATH", "Pfad zum SCUM-Logs-Ordner"),
    ("SERVER_SETTINGS_PATH", "Pfad zur ServerSettings.ini"),
    ("ADMIN_USERS_PATH", "Pfad zur AdminUsers.ini"),
]

SETUP_SECRET_FIELDS = [
    ("DISCORD_BOT_TOKEN", "Discord-Bot-Token", True),
    ("DISCORD_CLIENT_ID", "Discord-OAuth Client-ID", False),
    ("DISCORD_CLIENT_SECRET", "Discord-OAuth Client-Secret", False),
    ("ADMIN_PASSWORD", "Admin-Passwort (für /admin)", True),
    ("AMP_USER", "AMP-Benutzername", False),
    ("AMP_PASSWORD", "AMP-Passwort", False),
    ("TOPGAMES_TOKEN", "top-games.net Token (Voting-Belohnung, optional)", False),
]


def _is_configured() -> bool:
    return bool(config.DISCORD_BOT_TOKEN) and not config.DISCORD_BOT_TOKEN.startswith("TODO_")


def _write_secrets_ini(values: dict) -> None:
    lines = [
        "# Alle echten Zugangsdaten/Passwoerter/Tokens - NICHT teilen, nicht in Git.",
        "# Vom Setup-Assistenten (/setup) geschrieben - kann hier auch von Hand",
        "# nachbearbeitet werden (Format: KEY=WERT, # am Zeilenanfang = Kommentar).",
        "",
    ]
    for key, value in values.items():
        lines.append(f"{key}={value}")
    with open(SECRETS_INI_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _write_server_settings(values: dict) -> None:
    with open(config._data("server_settings.json"), "w", encoding="utf-8") as f:
        json.dump(values, f, ensure_ascii=False, indent=2)


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if _is_configured() and not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    error = None
    if request.method == "POST":
        try:
            secrets_out = dict(config._secrets)
            for key, _label, required in SETUP_SECRET_FIELDS:
                submitted = request.form.get(key, "").strip()
                if submitted:
                    secrets_out[key] = submitted
                if required and not secrets_out.get(key):
                    raise ValueError(f"'{_label}' ist ein Pflichtfeld.")

            existing_webapp_key = config.WEBAPP_SECRET_KEY
            secrets_out["WEBAPP_SECRET_KEY"] = (
                existing_webapp_key
                if existing_webapp_key and not existing_webapp_key.startswith("TODO_")
                else secrets.token_urlsafe(48)
            )

            settings_out = dict(config._settings)
            for key, _label in SETUP_CHANNEL_FIELDS:
                raw = request.form.get(key, "").strip()
                settings_out[key] = int(raw) if raw.isdigit() else 0
            for key, _label in SETUP_PATH_FIELDS:
                settings_out[key] = request.form.get(key, "").strip()

            settings_out["AMP_ENABLED"] = request.form.get("AMP_ENABLED") == "on"
            settings_out["AMP_URL"] = request.form.get("AMP_URL", "").strip() or "http://localhost:8081"
            settings_out["STEAM_QUERY_HOST"] = request.form.get("STEAM_QUERY_HOST", "").strip()
            steam_port_raw = request.form.get("STEAM_QUERY_PORT", "").strip()
            settings_out["STEAM_QUERY_PORT"] = int(steam_port_raw) if steam_port_raw.isdigit() else 0
            settings_out["WEBAPP_PUBLIC_URL"] = request.form.get("WEBAPP_PUBLIC_URL", "").strip() or "http://localhost:5000"
            settings_out["ADMIN_PLAYER_NAME"] = request.form.get("ADMIN_PLAYER_NAME", "").strip()
            settings_out["SERVER_NAME"] = request.form.get("SERVER_NAME", "").strip() or "Mein SCUM-Server"
            submitted_support_url = request.form.get("SUPPORT_URL", "").strip()
            settings_out["SUPPORT_URL"] = submitted_support_url if submitted_support_url else settings_out.get("SUPPORT_URL", config.DEFAULT_SUPPORT_URL)

            _write_secrets_ini(secrets_out)
            _write_server_settings(settings_out)
            return render_template("setup_done.html")
        except ValueError as e:
            error = str(e)

    secrets_present = {key: bool(config._secrets.get(key)) for key, _label, _req in SETUP_SECRET_FIELDS}
    return render_template(
        "setup.html",
        error=error,
        channel_fields=SETUP_CHANNEL_FIELDS,
        path_fields=SETUP_PATH_FIELDS,
        secret_fields=SETUP_SECRET_FIELDS,
        secrets_present=secrets_present,
        current=config._settings,
        already_configured=_is_configured(),
        default_support_url=config.DEFAULT_SUPPORT_URL,
    )


def _get_online_player_names() -> list:
    """Liest die aktuell online Spieler aus live_positions.txt (vom Lua-Mod
    alle 8s geschrieben)."""
    try:
        with open(config.LIVE_POSITIONS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return []
    names = []
    for line in content.splitlines():
        parts = line.split("|")
        if len(parts) == 4:
            names.append(parts[0])
    return names


@app.route("/admin")
@admin_required
def admin_dashboard():
    links = account_links._load_links()
    eco = economy._load()
    total_coins = sum(v.get("balance", 0) for v in eco.values())

    status = _get_server_status()  # nutzt den bestehenden 15s-Cache

    try:
        weather = scum_db.get_weather()
    except Exception:
        weather = None
    try:
        total_players = scum_db.get_total_players()
        active_squads = scum_db.get_active_squads()
        vehicle_count = scum_db.get_vehicle_count()
        base_count = scum_db.get_base_count()
    except Exception as e:
        print(f"[webapp] Dashboard-DB Fehler: {e}")
        total_players = active_squads = vehicle_count = base_count = None

    online_players = _get_online_player_names()
    next_restart = _next_restart_datetime()

    return render_template(
        "admin_dashboard.html",
        linked_count=len(links),
        total_coins=total_coins,
        shop_item_count=len(config.get_shop_items()),
        status=status,
        weather=weather,
        total_players=total_players,
        active_squads=active_squads,
        vehicle_count=vehicle_count,
        base_count=base_count,
        online_players=online_players,
        next_restart=next_restart,
        admin_name=config.ADMIN_PLAYER_NAME,
    )


@app.route("/admin/live-map")
@admin_required
def admin_live_map():
    return render_template("admin_live_map.html", shop_items_json=json.dumps(config.get_shop_items()))


@app.route("/admin/live-map/image")
@admin_required
def admin_live_map_image():
    directory = os.path.dirname(config.KILL_MAP_IMAGE_PATH)
    filename = os.path.basename(config.KILL_MAP_IMAGE_PATH)
    return send_from_directory(directory, filename)


_OFFLINE_POS_RE = re.compile(
    r"^[\d.]+-[\d.]+:\s*'\S+\s+(?P<steamid>\d+):(?P<player>.+?)\((?P<slot>\d+)\)'\s+"
    r"logged (?P<action>in|out) at:\s*X=(?P<x>[-\d.]+)\s*Y=(?P<y>[-\d.]+)\s*Z=(?P<z>[-\d.]+)"
)


def _get_last_known_positions() -> dict:
    """Letzte bekannte Position je Spielername ueber ALLE login_*.log-Dateien
    (nicht nur die aktuellste), damit auch Spieler aus frueheren Server-Sessions
    auftauchen - 'logged in' und 'logged out' enthalten beide die Position.
    Dateien sind klein (SCUM behaelt nur wenige Tage), daher unproblematisch,
    bei jedem Aufruf alle einzulesen. Neuere Dateien ueberschreiben aeltere
    Eintraege je Spieler, damit wirklich die letzte bekannte Position gewinnt."""
    pattern = os.path.join(config.SCUM_LOGS_PATH, "login_*.log")
    files = sorted(glob.glob(pattern), key=lambda f: os.path.getmtime(f))

    positions = {}
    for path in files:
        encoding = economy_online._detect_encoding(path)
        try:
            with open(path, "r", encoding=encoding, errors="replace") as f:
                for line in f:
                    m = _OFFLINE_POS_RE.match(line.strip())
                    if m:
                        positions[m.group("player")] = (
                            float(m.group("x")), float(m.group("y")), float(m.group("z"))
                        )
        except FileNotFoundError:
            continue
    return positions


@app.route("/admin/live-map/positions")
@admin_required
def admin_live_map_positions():
    try:
        with open(config.LIVE_POSITIONS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = ""

    positions = []
    online_names = set()
    for line in content.splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        name, xs, ys, zs = parts
        try:
            x, y = float(xs), float(ys)
        except ValueError:
            continue
        px, py = map_image.log_to_pixel(x, y)
        positions.append({"name": name, "px": px, "py": py, "status": "online"})
        online_names.add(name)

    for name, (x, y, z) in _get_last_known_positions().items():
        if name in online_names:
            continue  # schon als online gelistet, aktuellere Position gilt
        px, py = map_image.log_to_pixel(x, y)
        positions.append({"name": name, "px": px, "py": py, "status": "offline"})

    vehicles = []
    try:
        with open(config.VEHICLE_POSITIONS_FILE, "r", encoding="utf-8") as f:
            vehicle_content = f.read()
        for line in vehicle_content.splitlines():
            parts = line.split("|")
            if len(parts) != 4:
                continue
            name, xs, ys, zs = parts
            try:
                x, y = float(xs), float(ys)
            except ValueError:
                continue
            px, py = map_image.log_to_pixel(x, y)
            vehicles.append({"name": name, "px": px, "py": py})
    except FileNotFoundError:
        pass

    try:
        from PIL import Image
        with Image.open(config.KILL_MAP_IMAGE_PATH) as img:
            width, height = img.size
    except Exception:
        width, height = None, None

    try:
        vehicle_total = scum_db.get_vehicle_count()
    except Exception:
        vehicle_total = None

    return jsonify({
        "positions": positions, "vehicles": vehicles, "vehicle_total": vehicle_total,
        "image_width": width, "image_height": height,
    })


def _find_steam_id_by_name(name: str) -> str | None:
    """Sucht per exaktem Namensvergleich unter allen jemals gesehenen Spielern
    (aus der SCUM.db) - fuer die Live-Karten-Aktionen (Item/Geld/Befehl)."""
    for record in leaderboard_stats.get_current_player_data().values():
        if record.get("name") == name:
            return record.get("user_id")
    return None


@app.route("/admin/live-map/click-to-log", methods=["POST"])
@admin_required
def admin_live_map_click_to_log():
    """Rechnet einen Karten-Klick (Pixel) in SCUM-Weltkoordinaten um."""
    data = request.get_json(force=True) or {}
    try:
        px, py = float(data["px"]), float(data["py"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False, "error": "Ungültige Koordinaten."}), 400
    log_x, log_y = map_image.pixel_to_log(px, py)
    return jsonify({"ok": True, "x": round(log_x, 1), "y": round(log_y, 1)})


@app.route("/admin/live-map/teleport", methods=["POST"])
@admin_required
def admin_live_map_teleport():
    data = request.get_json(force=True) or {}
    player = (data.get("player") or "").strip()
    try:
        x, y = float(data["x"]), float(data["y"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False, "error": "Ungültige Koordinaten."}), 400
    if not player:
        return jsonify({"ok": False, "error": "Spieler erforderlich."}), 400
    try:
        with open(config.TAXI_COMMANDS_FILE, "a", encoding="utf-8") as f:
            f.write(f"TELEPORT|{player}|{x}|{y}|0\n")
        activity_log.log("web", _admin_actor(), "Live-Karte: Teleport", f"{player} -> {x:.0f}, {y:.0f}")
        return jsonify({"ok": True, "message": f"{player} wird teleportiert (falls online)."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/admin/live-map/give-item", methods=["POST"])
@admin_required
def admin_live_map_give_item():
    data = request.get_json(force=True) or {}
    player = (data.get("player") or "").strip()
    item_type = "vehicle" if data.get("type") == "vehicle" else "item"
    item_id = (data.get("item_id") or "").strip()
    try:
        amount = max(1, int(data.get("amount") or 1))
    except (TypeError, ValueError):
        amount = 1
    if not player or not item_id:
        return jsonify({"ok": False, "error": "Spieler und Item-ID erforderlich."}), 400

    steam_id = _find_steam_id_by_name(player)
    if not steam_id:
        return jsonify({"ok": False, "error": f"SteamID von '{player}' nicht gefunden."}), 404

    try:
        _grant_temp_admin_sync(str(steam_id))
        with open(config.TAXI_COMMANDS_FILE, "a", encoding="utf-8") as f:
            f.write(f"BUY_ITEM|{player}|{item_type}|{item_id}|{amount}\n")
        activity_log.log("web", _admin_actor(), "Live-Karte: Item vergeben", f"{item_id} x{amount} -> {player}")
        return jsonify({"ok": True, "message": f"{item_id} x{amount} an {player} gesendet (falls online)."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/admin/live-map/give-money-fame", methods=["POST"])
@admin_required
def admin_live_map_give_money_fame():
    data = request.get_json(force=True) or {}
    player = (data.get("player") or "").strip()
    try:
        money = int(data.get("money") or 0)
        fame = int(data.get("fame") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Ungültiger Betrag."}), 400
    if not player or (money == 0 and fame == 0):
        return jsonify({"ok": False, "error": "Spieler und mind. ein Betrag ungleich 0 erforderlich."}), 400

    steam_id = _find_steam_id_by_name(player)
    if not steam_id:
        return jsonify({"ok": False, "error": f"SteamID von '{player}' nicht gefunden."}), 404

    try:
        ok = player_grants.grant_money_and_fame(str(steam_id), money, fame, player_name=player)
        if not ok:
            return jsonify({"ok": False, "error": "Kein Datensatz zu dieser SteamID gefunden."}), 404
        activity_log.log("web", _admin_actor(), "Live-Karte: Geld/Ruhm vergeben", f"{player}: {money:+d} Geld, {fame:+d} Ruhm")
        return jsonify({"ok": True, "message": f"{player}: {money:+d} Geld, {fame:+d} Ruhm vergeben."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/admin/live-map/run-command", methods=["POST"])
@admin_required
def admin_live_map_run_command():
    data = request.get_json(force=True) or {}
    player = (data.get("player") or "").strip()
    raw_cmd = (data.get("command") or "").strip().lstrip("#")
    if not player or not raw_cmd:
        return jsonify({"ok": False, "error": "Spieler und Befehl erforderlich."}), 400

    try:
        if player != config.ADMIN_PLAYER_NAME:
            steam_id = _find_steam_id_by_name(player)
            if not steam_id:
                return jsonify({"ok": False, "error": f"SteamID von '{player}' nicht gefunden."}), 404
            _grant_temp_admin_sync(str(steam_id))
        with open(config.TAXI_COMMANDS_FILE, "a", encoding="utf-8") as f:
            f.write(f"ADMIN_CMD|{player}|{raw_cmd}\n")
        activity_log.log("web", _admin_actor(), "Live-Karte: Custom-Befehl", f"als {player}: #{raw_cmd}")
        return jsonify({"ok": True, "message": f"Befehl gesendet (als {player}): {raw_cmd}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/admin/live-map/spawn-drop-marker", methods=["POST"])
@admin_required
def admin_live_map_spawn_drop_marker():
    import uuid
    data = request.get_json(force=True) or {}
    try:
        x, y, z = float(data["x"]), float(data["y"]), float(data["z"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False, "error": "X, Y und Z (Bodenhöhe) erforderlich."}), 400

    try:
        request_id = uuid.uuid4().hex[:12]
        with open(config.TAXI_COMMANDS_FILE, "a", encoding="utf-8") as f:
            f.write(f"SPAWN_DROP_MARKER|{request_id}|{x}|{y}|{z}\n")
        activity_log.log("web", _admin_actor(), "Live-Karte: Absprungkiste gespawnt", f"{x:.0f}, {y:.0f}, {z:.0f}")
        return jsonify({"ok": True, "message": f"Kiste wird bei {x:.0f}, {y:.0f}, {z:.0f} platziert (falls Server online)."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/admin/players")
@admin_required
def admin_players():
    current = leaderboard_stats.get_current_player_data()
    links = account_links._load_links()
    steam_to_discord = {v["steam_id"]: k for k, v in links.items()}
    rows = []
    for uid, p in current.items():
        discord_id = steam_to_discord.get(p.get("user_id"))
        link = links.get(discord_id) if discord_id else None
        rows.append({
            "name": p["name"],
            "steam_id": p.get("user_id"),
            "kills": p.get("kills", 0),
            "deaths": p.get("deaths", 0),
            "play_time_h": round((p.get("minutes_survived", 0) or 0) / 60, 1),
            "discord_id": discord_id,
            "discord_linked": link is not None,
            "starter_kit_claimed": bool(link and link.get("starter_kit_claimed")),
            "money": p.get("money_balance", 0),
        })
    rows.sort(key=lambda r: r["name"].lower())
    return render_template("admin_players.html", players=rows)


@app.route("/admin/players/<discord_id>/reset-starter-kit", methods=["POST"])
@admin_required
def admin_players_reset_starter_kit(discord_id):
    account_links.reset_starter_kit(int(discord_id))
    return redirect(url_for("admin_players"))


def _grant_temp_admin_sync(steam_id: str, seconds: int = 30) -> bool:
    """Synchrone Variante fuer die Webapp (kein asyncio-Loop wie im Discord-Bot)."""
    if not admin_file.add_temp_admin(steam_id):
        return False
    time.sleep(10)

    def revoke():
        admin_file.remove_temp_admin(steam_id)

    threading.Timer(max(0, seconds - 5), revoke).start()
    return True


@app.route("/admin/console", methods=["GET", "POST"])
@admin_required
def admin_console():
    result = None
    online_names = _get_online_player_names()

    if request.method == "POST":
        raw_cmd = request.form.get("command", "").strip().lstrip("#")
        run_as = request.form.get("run_as", config.ADMIN_PLAYER_NAME).strip()

        if raw_cmd:
            try:
                if run_as != config.ADMIN_PLAYER_NAME:
                    # Nicht der echte Admin-Charakter -> braucht kurzzeitige
                    # Admin-Rechte (wie beim Shop-Kauf), dafuer die SteamID finden.
                    current = leaderboard_stats.get_current_player_data()
                    steam_id = None
                    for p in current.values():
                        if p.get("name") == run_as:
                            steam_id = p.get("user_id")
                            break
                    if steam_id:
                        _grant_temp_admin_sync(str(steam_id))
                    else:
                        result = f"Konnte SteamID von '{run_as}' nicht finden."

                if result is None:
                    with open(config.TAXI_COMMANDS_FILE, "a", encoding="utf-8") as f:
                        f.write(f"ADMIN_CMD|{run_as}|{raw_cmd}\n")
                    result = f"Befehl gesendet (als {run_as}): {raw_cmd}"
            except Exception as e:
                result = f"Fehler: {e}"

    return render_template(
        "admin_console.html", result=result, admin_name=config.ADMIN_PLAYER_NAME,
        online_players=online_names,
    )


@app.route("/admin/shop")
@admin_required
def admin_shop():
    items = config.get_shop_items()
    grouped = {}
    for item in items:
        cat = item.get("category", "Sonstiges")
        grouped.setdefault(cat, []).append(item)
    ordered_groups = [(cat, grouped[cat]) for cat in config.SHOP_CATEGORIES if cat in grouped]
    items_by_key = {i["key"]: i for i in items}
    return render_template("admin_shop.html", groups=ordered_groups, items_by_key=items_by_key)


def _save_shop_items(items):
    with open(config.SHOP_ITEMS_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


@app.route("/admin/shop/upload-image", methods=["POST"])
@admin_required
def admin_shop_upload_image():
    file = request.files.get("image_file")
    if not file or file.filename == "":
        return jsonify({"error": "Keine Datei ausgewählt."}), 400
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({"error": f"Dateityp .{ext} nicht erlaubt (erlaubt: {', '.join(ALLOWED_IMAGE_EXTENSIONS)})."}), 400

    base_name = secure_filename(file.filename.rsplit(".", 1)[0]) or "bild"
    filename = f"{base_name}.{ext}"
    path = os.path.join(SHOP_IMAGES_DIR, filename)
    # Falls der Name schon existiert, eine Nummer anhaengen statt zu ueberschreiben
    counter = 1
    while os.path.exists(path):
        filename = f"{base_name}_{counter}.{ext}"
        path = os.path.join(SHOP_IMAGES_DIR, filename)
        counter += 1

    file.save(path)
    image_url = config.WEBAPP_PUBLIC_URL + url_for("static", filename=f"shop_images/{filename}")
    return jsonify({"image_url": image_url, "filename": filename})


@app.route("/admin/shop/image-library")
@admin_required
def admin_shop_image_library():
    files = sorted(os.listdir(SHOP_IMAGES_DIR), reverse=True)
    files = [f for f in files if f.rsplit(".", 1)[-1].lower() in ALLOWED_IMAGE_EXTENSIONS]
    urls = [config.WEBAPP_PUBLIC_URL + url_for("static", filename=f"shop_images/{f}") for f in files]
    return jsonify({"images": urls})


def _apply_shop_form(item: dict, form) -> None:
    item["name"] = form["name"].strip()
    item["category"] = form.get("category", "Sonstiges")
    item["type"] = form["type"]
    item["id"] = form["item_id"].strip()
    item["price"] = int(form["price"])
    item["shop_visible"] = "shop_visible" in form
    item["image_url"] = form.get("image_url", "").strip()
    if item["type"] == "item":
        item["amount"] = int(form.get("amount", 1) or 1)
    elif "amount" in item:
        del item["amount"]

    subcategory = form.get("subcategory", "").strip()
    if subcategory:
        item["subcategory"] = subcategory
    elif "subcategory" in item:
        del item["subcategory"]

    parent_key = form.get("parent_key", "").strip()
    if parent_key:
        item["parent_key"] = parent_key
    elif "parent_key" in item:
        del item["parent_key"]


def admin_shop_form_context(item: dict | None):
    all_items = config.get_shop_items()
    subcategories = sorted({i["subcategory"] for i in all_items if i.get("subcategory")})
    possible_parents = [i for i in all_items if not i.get("parent_key") and (item is None or i["key"] != item["key"])]
    return {
        "item": item, "categories": config.SHOP_CATEGORIES,
        "subcategories": subcategories, "possible_parents": possible_parents,
    }


@app.route("/admin/shop/new", methods=["GET", "POST"])
@admin_required
def admin_shop_new():
    if request.method == "POST":
        items = config.get_shop_items()
        new_item = {"key": request.form["key"].strip()}
        _apply_shop_form(new_item, request.form)
        items.append(new_item)
        _save_shop_items(items)
        return redirect(url_for("admin_shop"))
    return render_template("admin_shop_form.html", **admin_shop_form_context(None))


@app.route("/admin/shop/<key>/edit", methods=["GET", "POST"])
@admin_required
def admin_shop_edit(key):
    items = config.get_shop_items()
    item = next((i for i in items if i["key"] == key), None)
    if item is None:
        abort(404)

    if request.method == "POST":
        _apply_shop_form(item, request.form)
        _save_shop_items(items)
        return redirect(url_for("admin_shop"))

    return render_template("admin_shop_form.html", **admin_shop_form_context(item))


@app.route("/admin/shop/<key>/delete", methods=["POST"])
@admin_required
def admin_shop_delete(key):
    items = [i for i in config.get_shop_items() if i["key"] != key]
    _save_shop_items(items)
    return redirect(url_for("admin_shop"))


@app.route("/admin/shop/<key>/toggle-visible", methods=["POST"])
@admin_required
def admin_shop_toggle_visible(key):
    items = config.get_shop_items()
    item = next((i for i in items if i["key"] == key), None)
    if item is None:
        return jsonify({"ok": False, "error": "Artikel nicht gefunden."}), 404
    item["shop_visible"] = not item.get("shop_visible", True)
    _save_shop_items(items)
    return jsonify({"ok": True, "shop_visible": item["shop_visible"]})


@app.route("/admin/daily", methods=["GET", "POST"])
@admin_required
def admin_daily():
    if request.method == "POST":
        keys = request.form.getlist("item_key")
        amounts = request.form.getlist("item_amount")
        entries = [
            {"item_key": k, "amount": int(a)}
            for k, a in zip(keys, amounts) if k and a and int(a) > 0
        ]
        with open(config.DAILY_PACKAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        return redirect(url_for("admin_daily"))

    return render_template(
        "admin_daily.html", items=config.get_shop_items(), entries=config.get_daily_package_entries(),
        cooldown_hours=config.DAILY_PACKAGE_COOLDOWN_HOURS,
    )


@app.route("/admin/redeem-codes", methods=["GET", "POST"])
@admin_required
def admin_redeem_codes():
    if request.method == "POST":
        item_key = request.form["item_key"]
        amount = int(request.form.get("amount") or 1)
        max_uses = int(request.form.get("max_uses") or 1)
        expires_raw = request.form.get("expires_at", "").strip()
        expires_at = datetime.fromisoformat(expires_raw).isoformat() if expires_raw else None
        note = request.form.get("note", "").strip()
        new_code = redeem_codes.create_code(
            item_key, amount=amount, max_uses=max_uses, expires_at=expires_at, note=note
        )
        item = config.get_shop_item_by_key(item_key)
        activity_log.log(
            "web", _admin_actor(), "Redeem-Code erstellt",
            f"{new_code} -> {item['name'] if item else item_key} x{amount} (max {max_uses}x)",
        )
        return redirect(url_for("admin_redeem_codes", created=new_code))

    codes = sorted(redeem_codes.list_codes(), key=lambda c: c["created_at"], reverse=True)
    items_by_key = {i["key"]: i for i in config.get_shop_items()}
    return render_template(
        "admin_redeem_codes.html", codes=codes, items_by_key=items_by_key,
        items=config.get_shop_items(), created=request.args.get("created"),
    )


@app.route("/admin/redeem-codes/<code>/delete", methods=["POST"])
@admin_required
def admin_redeem_codes_delete(code):
    redeem_codes.delete_code(code)
    return redirect(url_for("admin_redeem_codes"))


def _save_dead_drops(drops):
    with open(config.DEAD_DROPS_FILE, "w", encoding="utf-8") as f:
        json.dump(drops, f, indent=2, ensure_ascii=False)


def _dead_drop_from_form(form) -> dict:
    item_keys = form.getlist("req_item_key")
    amounts = form.getlist("req_amount")
    requirements = [
        {"item_key": k, "amount": int(a)}
        for k, a in zip(item_keys, amounts) if k and a and int(a) > 0
    ]
    entry = {
        "name": form["name"].strip(),
        "description": form.get("description", "").strip(),
        "image_url": form.get("image_url", "").strip(),
        "x": float(form["x"]), "y": float(form["y"]), "z": 0.0,
        "radius": float(form.get("radius") or 15),
        "requirements": requirements,
        "payout_type": form.get("payout_type", "coins"),
    }
    if entry["payout_type"] == "package":
        entry["payout_package_key"] = form.get("payout_package_key", "")
        entry["payout_package_amount"] = int(form.get("payout_package_amount") or 1)
    else:
        entry["payout_amount"] = int(form.get("payout_amount") or 0)
    return entry


@app.route("/admin/dead-drops")
@admin_required
def admin_dead_drops():
    items_by_key = {i["key"]: i for i in config.get_shop_items()}
    return render_template("admin_dead_drops.html", drops=config.get_dead_drops(), items_by_key=items_by_key)


@app.route("/admin/dead-drops/new", methods=["GET", "POST"])
@admin_required
def admin_dead_drops_new():
    if request.method == "POST":
        drops = config.get_dead_drops()
        new_drop = {"key": request.form["key"].strip(), **_dead_drop_from_form(request.form)}
        drops.append(new_drop)
        _save_dead_drops(drops)
        return redirect(url_for("admin_dead_drops"))
    return render_template("admin_dead_drop_form.html", drop=None, items=config.get_shop_items())


@app.route("/admin/dead-drops/<key>/edit", methods=["GET", "POST"])
@admin_required
def admin_dead_drops_edit(key):
    drops = config.get_dead_drops()
    drop = next((d for d in drops if d["key"] == key), None)
    if drop is None:
        abort(404)
    if request.method == "POST":
        drop.update(_dead_drop_from_form(request.form))
        _save_dead_drops(drops)
        return redirect(url_for("admin_dead_drops"))
    return render_template("admin_dead_drop_form.html", drop=drop, items=config.get_shop_items())


@app.route("/admin/dead-drops/<key>/delete", methods=["POST"])
@admin_required
def admin_dead_drops_delete(key):
    drops = [d for d in config.get_dead_drops() if d["key"] != key]
    _save_dead_drops(drops)
    return redirect(url_for("admin_dead_drops"))


def _save_quests(quests):
    with open(config.QUESTS_FILE, "w", encoding="utf-8") as f:
        json.dump(quests, f, indent=2, ensure_ascii=False)


def _quest_from_form(form) -> dict:
    item_keys = form.getlist("req_item_key")
    amounts = form.getlist("req_amount")
    requirements = [
        {"item_key": k, "amount": int(a)}
        for k, a in zip(item_keys, amounts) if k and a and int(a) > 0
    ]
    entry = {
        "name": form["name"].strip(),
        "description": form.get("description", "").strip(),
        "image_url": form.get("image_url", "").strip(),
        "x": float(form["x"]), "y": float(form["y"]), "z": 0.0,
        "radius": float(form.get("radius") or 15),
        "requirements": requirements,
        "payout_type": form.get("payout_type", "coins"),
    }
    if entry["payout_type"] == "package":
        entry["payout_package_key"] = form.get("payout_package_key", "")
        entry["payout_package_amount"] = int(form.get("payout_package_amount") or 1)
    else:
        entry["payout_amount"] = int(form.get("payout_amount") or 0)
    return entry


@app.route("/admin/quests")
@admin_required
def admin_quests():
    items_by_key = {i["key"]: i for i in config.get_shop_items()}
    return render_template("admin_quests.html", quests=config.get_quests(), items_by_key=items_by_key)


@app.route("/admin/quests/new", methods=["GET", "POST"])
@admin_required
def admin_quests_new():
    if request.method == "POST":
        quests = config.get_quests()
        new_quest = {"key": request.form["key"].strip(), **_quest_from_form(request.form)}
        quests.append(new_quest)
        _save_quests(quests)
        return redirect(url_for("admin_quests"))
    return render_template("admin_quest_form.html", quest=None, items=config.get_shop_items())


@app.route("/admin/quests/<key>/edit", methods=["GET", "POST"])
@admin_required
def admin_quests_edit(key):
    quests = config.get_quests()
    quest = next((q for q in quests if q["key"] == key), None)
    if quest is None:
        abort(404)
    if request.method == "POST":
        quest.update(_quest_from_form(request.form))
        _save_quests(quests)
        return redirect(url_for("admin_quests"))
    return render_template("admin_quest_form.html", quest=quest, items=config.get_shop_items())


@app.route("/admin/quests/<key>/delete", methods=["POST"])
@admin_required
def admin_quests_delete(key):
    quests = [q for q in config.get_quests() if q["key"] != key]
    _save_quests(quests)
    return redirect(url_for("admin_quests"))


def _save_world_event_locations(locations):
    with open(config.WORLD_EVENT_LOCATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(locations, f, indent=2, ensure_ascii=False)


@app.route("/admin/world-events", methods=["GET", "POST"])
@admin_required
def admin_world_events():
    if request.method == "POST":
        keys = request.form.getlist("loot_item_key")
        amounts = request.form.getlist("loot_item_amount")
        entries = [
            {"item_key": k, "amount": int(a)}
            for k, a in zip(keys, amounts) if k and a and int(a) > 0
        ]
        with open(config.WORLD_EVENT_LOOT_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        return redirect(url_for("admin_world_events"))

    state = world_event.get_state()
    current_location = world_event.get_current_location()
    return render_template(
        "admin_world_events.html",
        locations=config.get_world_event_locations(),
        items=config.get_shop_items(),
        loot_entries=config.get_world_event_loot_entries(),
        state=state, current_location=current_location,
    )


@app.route("/admin/world-events/new", methods=["GET", "POST"])
@admin_required
def admin_world_events_new():
    if request.method == "POST":
        locations = config.get_world_event_locations()
        locations.append({
            "key": request.form["key"].strip(),
            "name": request.form["name"].strip(),
            "image_url": request.form.get("image_url", "").strip(),
            "x": float(request.form["x"]), "y": float(request.form["y"]), "z": 0.0,
            "radius": float(request.form.get("radius") or 400),
        })
        _save_world_event_locations(locations)
        return redirect(url_for("admin_world_events"))
    return render_template("admin_world_event_location_form.html", location=None)


@app.route("/admin/world-events/<key>/edit", methods=["GET", "POST"])
@admin_required
def admin_world_events_edit(key):
    locations = config.get_world_event_locations()
    location = next((loc for loc in locations if loc["key"] == key), None)
    if location is None:
        abort(404)
    if request.method == "POST":
        location["name"] = request.form["name"].strip()
        location["image_url"] = request.form.get("image_url", "").strip()
        location["x"] = float(request.form["x"])
        location["y"] = float(request.form["y"])
        location["radius"] = float(request.form.get("radius") or 400)
        _save_world_event_locations(locations)
        return redirect(url_for("admin_world_events"))
    return render_template("admin_world_event_location_form.html", location=location)


@app.route("/admin/world-events/<key>/delete", methods=["POST"])
@admin_required
def admin_world_events_delete(key):
    locations = [loc for loc in config.get_world_event_locations() if loc["key"] != key]
    _save_world_event_locations(locations)
    return redirect(url_for("admin_world_events"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.WEBAPP_PORT, debug=False)
