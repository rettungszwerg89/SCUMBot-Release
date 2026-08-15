# SCUM Discord Bot - Teil 1: Server-Status
# Startet einen Discord-Bot, der periodisch den AMP-Status der SCUM-Instanz
# abfragt und als Embed in einem festgelegten Channel aktuell haelt.

import os
import asyncio
import json
from datetime import datetime, timedelta
import discord
from discord.ext import tasks

import config
from services.amp_client import AMPClient
from dbdata import scum_db
from readers import chat_reader
from readers import bunker_reader
from dbdata import leaderboard_stats
from dbdata import leaderboard_snapshot
from readers import kill_reader
from econ import vote_rewards
from services import map_image
from services import mech_schedule
from dbdata import elevation
from services import admin_file
from services import steam_query
import account_links
from econ import redeem_codes
from econ import lottery
from dbdata import player_lookup
from services import item_check
from econ import player_grants
from econ import quest_progress
from econ import world_event
from econ import economy
from econ import economy_activity
from econ import economy_online
from services import activity_log

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

amp = AMPClient(config.AMP_URL, config.AMP_USER, config.AMP_PASSWORD)


def get_server_status() -> dict:
    """Liefert den Serverstatus im selben Format wie amp.get_status(), egal ob
    ueber AMP oder (ohne AMP konfiguriert) per generischer Steam-A2S-Abfrage.
    Wirft eine Exception, wenn beides nicht verfuegbar ist (vom Aufrufer wie
    ein AMP-Fehler behandelt -> 'Status unbekannt' im Embed)."""
    if config.AMP_ENABLED:
        return amp.get_status()

    info = steam_query.query(config.STEAM_QUERY_HOST, config.STEAM_QUERY_PORT)
    if info is None:
        raise RuntimeError("Serverstatus nicht abrufbar (Steam-Query antwortet nicht - Query-Port pruefen).")
    return {
        "State": 20 if info["online"] else 0,
        "Metrics": {"Active Users": {"RawValue": info["players"], "MaxValue": info["max_players"]}},
        "Ports": [],
        "Uptime": "?",
    }


def safe_gif_file(path: str, attachment_name: str) -> discord.File | None:
    """Gibt eine discord.File zurueck, wenn die Datei existiert und nicht zu
    gross fuer Discord ist - sonst None (mit Warnung), damit der Bot nicht abstuerzt."""
    if not os.path.exists(path):
        return None
    size = os.path.getsize(path)
    if size > config.MAX_ATTACHMENT_BYTES:
        print(f"WARNUNG: {path} ist {size / 1024 / 1024:.1f} MB, ueber dem Discord-Limit "
              f"({config.MAX_ATTACHMENT_BYTES / 1024 / 1024:.0f} MB). GIF wird uebersprungen, "
              f"bitte Datei verkleinern.")
        return None
    return discord.File(path, filename=attachment_name)


def load_message_id(store_path: str) -> int | None:
    if os.path.exists(store_path):
        with open(store_path, "r") as f:
            content = f.read().strip()
            return int(content) if content else None
    return None


def save_message_id(store_path: str, message_id: int) -> None:
    with open(store_path, "w") as f:
        f.write(str(message_id))


def clear_message_id(store_path: str) -> None:
    if os.path.exists(store_path):
        os.remove(store_path)


def next_restart_datetime() -> datetime:
    now = datetime.now()
    candidates = []
    for h in config.RESTART_HOURS:
        candidate = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        candidates.append(candidate)
    return min(candidates)


def next_restart_info() -> str:
    """Berechnet den naechsten Neustart-Zeitpunkt anhand der festen Stunden
    in config.RESTART_HOURS (z.B. 0, 6, 12, 18 Uhr)."""
    now = datetime.now()
    next_dt = next_restart_datetime()
    delta = next_dt - now
    total_minutes = int(delta.total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{next_dt.strftime('%H:%M')} Uhr (in {hours}h {minutes}m)"


def build_status_embed(status: dict) -> discord.Embed:
    state_label = amp.get_state_label(status)
    metrics = status.get("Metrics", {})
    users = metrics.get("Active Users", {})

    # Server-Port aus der Ports-Liste holen (der Eintrag mit "Server Port" im Namen)
    server_port = "?"
    for p in status.get("Ports", []):
        if "Server" in (p.get("Name") or ""):
            server_port = p.get("Port", "?")
            break

    is_online = status.get("State") == 20
    color = discord.Color.green() if is_online else discord.Color.red()
    status_dot = "🟢" if is_online else "🔴"

    embed = discord.Embed(title="📡 SCUM Serverstatus", color=color)
    embed.add_field(name="🌍 Status", value=f"{status_dot} {state_label}", inline=False)
    embed.add_field(name="📍 Port", value=str(server_port), inline=True)
    embed.add_field(
        name="👥 Spieler online",
        value=f"{users.get('RawValue', '?')} / {users.get('MaxValue', '?')}",
        inline=True,
    )
    embed.add_field(name="⏱️ Uptime", value=status.get("Uptime", "?"), inline=True)

    embed.add_field(name="🔄 Nächster Neustart", value=next_restart_info(), inline=True)

    try:
        squads = scum_db.get_active_squads()
        total_players = scum_db.get_total_players()
    except Exception as e:
        squads, total_players = "?", "?"
        print(f"Fehler beim Lesen der SCUM.db: {e}")

    embed.add_field(name="🚩 Aktive Squads", value=str(squads), inline=True)
    embed.add_field(name="👤 Spieler gesamt", value=str(total_players), inline=True)

    embed.set_footer(text="SCUM Bot • Live-Daten (AMP)" if config.AMP_ENABLED else "SCUM Bot • Live-Daten (Steam-Query)")
    if os.path.exists(config.STATUS_GIF_PATH) and os.path.getsize(config.STATUS_GIF_PATH) <= config.MAX_ATTACHMENT_BYTES:
        embed.set_image(url="attachment://welt.gif")
    return embed


@tasks.loop(seconds=config.STATUS_UPDATE_SECONDS)
async def update_status():
    channel = client.get_channel(config.STATUS_CHANNEL_ID)
    if channel is None:
        print("FEHLER: Status-Channel nicht gefunden. Channel-ID in config.py pruefen.")
        return

    try:
        status = get_server_status()
        embed = build_status_embed(status)
    except Exception as e:
        embed = discord.Embed(
            title="📡 SCUM Serverstatus",
            description=f"⚠️ Fehler beim Abrufen des Status: {e}",
            color=discord.Color.orange(),
        )

    message_id = load_message_id(config.STATUS_MESSAGE_STORE)
    gif_file = safe_gif_file(config.STATUS_GIF_PATH, "welt.gif")

    if message_id:
        try:
            message = await channel.fetch_message(message_id)
            if gif_file:
                await message.edit(embed=embed, attachments=[gif_file])
            else:
                await message.edit(embed=embed)
            return
        except discord.NotFound:
            pass  # Nachricht existiert nicht mehr -> neue erstellen

    if gif_file:
        new_message = await channel.send(embed=embed, file=gif_file)
    else:
        new_message = await channel.send(embed=embed)
    save_message_id(config.STATUS_MESSAGE_STORE, new_message.id)


CHAT_TYPE_STYLE = {
    "Local": ("📍", "Lokal"),
    "Global": ("🌐", "Global"),
    "Squad": ("👥", "Squad"),
    "Admin": ("🛡️", "Admin"),
}


@tasks.loop(seconds=5)
async def poll_chat():
    channel = client.get_channel(config.CHAT_CHANNEL_ID)
    if channel is None:
        print(f"FEHLER: Chat-Channel mit ID {config.CHAT_CHANNEL_ID} nicht gefunden/nicht sichtbar.")
        return

    try:
        new_lines = chat_reader.get_new_lines()
    except Exception as e:
        print(f"Fehler beim Lesen der Chat-Log: {e}")
        return

    if new_lines:
        print(f"[chat] {len(new_lines)} neue Zeile(n) gefunden: {new_lines}")

    for line in new_lines:
        parsed = chat_reader.parse_chat_line(line)
        if parsed is None:
            print(f"[chat] Zeile ignoriert (kein Chat-Format): {line}")
            continue

        # Pruefen, ob die Nachricht ein Account-Registrierungscode ist
        linked_discord_id = account_links.try_consume_code(
            parsed["message"], parsed["steamid"], parsed["player"]
        )
        if linked_discord_id is not None:
            print(f"[account] Verknuepft: Discord {linked_discord_id} <-> SteamID {parsed['steamid']} ({parsed['player']})")
            try:
                user = await client.fetch_user(linked_discord_id)
                confirm_embed = discord.Embed(
                    title="✅ Account erfolgreich verknüpft!",
                    description="Dein Discord-Account wurde mit deinem SCUM-Charakter verknüpft.",
                    color=discord.Color.green(),
                )
                confirm_embed.add_field(name="🆔 Spielername", value=parsed["player"], inline=True)
                confirm_embed.add_field(name="🔑 Steam ID", value=f"`{parsed['steamid']}`", inline=True)
                confirm_embed.add_field(
                    name="📅 Verknüpft am", value=datetime.now().strftime("%A, %d. %B %Y %H:%M"), inline=False
                )
                confirm_embed.add_field(
                    name="ℹ️ Und jetzt?",
                    value="Nutze die Buttons im Account-Panel, um **deine Statistiken** zu sehen "
                          "oder die Verknüpfung zu **trennen**.",
                    inline=False,
                )
                confirm_embed.set_footer(text="SCUM Server Automation")
                await user.send(embed=confirm_embed, view=DMAccountView())
            except Exception as e:
                print(f"Konnte Bestaetigungs-DM nicht senden: {e}")
            continue  # Code-Nachricht nicht weiterleiten

        if parsed["chat_type"] != "Global":
            continue  # nur Global-Chat nach Discord spiegeln

        emoji, label = CHAT_TYPE_STYLE.get(parsed["chat_type"], ("💬", parsed["chat_type"]))
        text = f"{emoji} **{parsed['player']}** ({label}): {parsed['message']}"
        try:
            await channel.send(text[:2000])
        except Exception as e:
            print(f"FEHLER beim Senden an Discord: {e}")

        try:
            with open(config.CHAT_LOG_JSON, "r", encoding="utf-8") as f:
                chat_log = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            chat_log = []
        chat_log.append({
            "timestamp": datetime.now().isoformat(),
            "player": parsed["player"],
            "message": parsed["message"],
        })
        chat_log = chat_log[-config.CHAT_LOG_MAX_ENTRIES:]
        try:
            with open(config.CHAT_LOG_JSON, "w", encoding="utf-8") as f:
                json.dump(chat_log, f)
        except Exception as e:
            print(f"FEHLER beim Schreiben von chat_log.json: {e}")


def log_coords_to_map_coords(log_x: float, log_y: float) -> tuple[float, float]:
    """Rechnet SCUM-Log-Koordinaten (aus gameplay.log) in das Koordinatensystem
    von scum-map.com um. Die Konstanten wurden per kleinster-Quadrate-Anpassung
    aus 4 bekannten Bunker-Positionen ermittelt (Log-Koordinaten vs. echte
    scum-map.com-Links) und sind auf ca. 0,1% genau."""
    map_x = 0.98674118 * log_x + -0.00199109 * log_y + -9266.7487
    map_y = 0.00408397 * log_x + 0.99152969 * log_y + 3028.5509
    return map_x, map_y


def build_bunker_embed() -> discord.Embed:
    bunkers = bunker_reader.get_current_bunkers()
    now = datetime.now()

    open_lines = []
    locked_lines = []
    web_snapshot = []  # fuer die Webseite (data/bunker_status.json)

    for name, info in sorted(bunkers.items()):
        if name in config.BUNKER_MAP_LINKS:
            map_url = config.BUNKER_MAP_LINKS[name]
        else:
            map_x, map_y = log_coords_to_map_coords(info["x"], info["y"])
            map_url = f"{config.BUNKER_MAP_BASE_URL}/{map_x:.4f},{map_y:.4f},{config.BUNKER_MAP_ZOOM}"
        map_link = f"[🗺️ map]({map_url})"
        if info["status"] == "Active":
            activated_at = now - timedelta(seconds=info["seconds_since"])
            closes_at = activated_at + timedelta(hours=config.BUNKER_ACTIVE_DURATION_HOURS)
            ts = int(closes_at.timestamp())
            open_lines.append(f"🟢 **{name}** — closes <t:{ts}:R> · {map_link}")
            web_snapshot.append({
                "name": name, "status": "Active", "changes_at": ts, "map_url": map_url,
                "image_file": config.BUNKER_IMAGE_FILES.get(name),
            })
        else:
            opens_at = now + timedelta(seconds=info["seconds_until"])
            ts = int(opens_at.timestamp())
            locked_lines.append(f"🔒 **{name}** — opens <t:{ts}:R> · {map_link}")
            web_snapshot.append({
                "name": name, "status": "Locked", "changes_at": ts, "map_url": map_url,
                "image_file": config.BUNKER_IMAGE_FILES.get(name),
            })

    try:
        with open(config.BUNKER_STATUS_JSON, "w", encoding="utf-8") as f:
            json.dump({"updated_at": now.isoformat(), "bunkers": web_snapshot}, f)
    except Exception as e:
        print(f"FEHLER beim Schreiben von bunker_status.json: {e}")

    embed = discord.Embed(
        title="🏚️ Verlassene Bunker",
        description=(
            "Loote die **offenen** Bunker, bevor sie sich wieder verschließen — "
            "**verschlossene** öffnen sich nach dem angezeigten Timer erneut."
        ),
        color=discord.Color.dark_gold(),
    )
    embed.add_field(
        name="Übersicht",
        value=f"🟢 {len(open_lines)} offen · 🔒 {len(locked_lines)} verschlossen",
        inline=False,
    )
    if open_lines:
        embed.add_field(name=f"Open · {len(open_lines)}", value="\n".join(open_lines), inline=False)
    if locked_lines:
        embed.add_field(name=f"Locked · {len(locked_lines)}", value="\n".join(locked_lines), inline=False)

    embed.set_footer(text="SCUM Bot • Automatisch bei Statusänderung")
    if os.path.exists(config.BUNKER_GIF_PATH) and os.path.getsize(config.BUNKER_GIF_PATH) <= config.MAX_ATTACHMENT_BYTES:
        embed.set_image(url="attachment://bunker.gif")
    return embed


async def _send_or_edit_bunker_embed(channel):
    embed = build_bunker_embed()
    gif_file = safe_gif_file(config.BUNKER_GIF_PATH, "bunker.gif")
    message_id = load_message_id(config.BUNKER_MESSAGE_STORE)

    if message_id:
        try:
            message = await channel.fetch_message(message_id)
            if gif_file:
                await message.edit(embed=embed, attachments=[gif_file])
            else:
                await message.edit(embed=embed)
            return
        except discord.NotFound:
            pass  # Nachricht existiert nicht mehr -> neue erstellen
        except Exception as e:
            print(f"FEHLER beim Editieren des Bunker-Status: {e}")
            return

    try:
        if gif_file:
            new_message = await channel.send(embed=embed, file=gif_file)
        else:
            new_message = await channel.send(embed=embed)
        save_message_id(config.BUNKER_MESSAGE_STORE, new_message.id)
    except Exception as e:
        print(f"FEHLER beim Senden des Bunker-Status: {e}")


@tasks.loop(seconds=config.BUNKER_CHECK_SECONDS)
async def poll_bunkers():
    channel = client.get_channel(config.BUNKER_CHANNEL_ID)
    if not hasattr(poll_bunkers, "_debug_printed"):
        poll_bunkers._debug_printed = False
    if not hasattr(poll_bunkers, "_initial_posted"):
        poll_bunkers._initial_posted = False
    if channel is None:
        print(f"FEHLER: Bunker-Channel mit ID {config.BUNKER_CHANNEL_ID} nicht gefunden/nicht sichtbar.")
        return

    try:
        changed = bunker_reader.get_changes()
    except Exception as e:
        print(f"Fehler beim Lesen der Bunker-Logs: {e}")
        return

    if not poll_bunkers._debug_printed:
        print(f"[bunker] {bunker_reader.debug_summary()}")
        poll_bunkers._debug_printed = True

    # Einmalig direkt nach dem Start den aktuellen Status posten, auch ohne Aenderung
    if not poll_bunkers._initial_posted and bunker_reader.get_current_bunkers():
        poll_bunkers._initial_posted = True
        print("[bunker] Poste initialen Status...")
        await _send_or_edit_bunker_embed(channel)
        return

    if not changed:
        return

    print(f"[bunker] Statusaenderung erkannt bei: {changed}")
    await _send_or_edit_bunker_embed(channel)


async def _grant_temp_admin_and_schedule_revoke(steam_id: str, seconds: int = 30):
    """Traegt einen Spieler kurzzeitig in AdminUsers.ini ein (falls er's nicht
    schon ist, und nur wenn AMP konfiguriert ist) und entfernt ihn nach
    'seconds' Sekunden automatisch wieder. Bestaetigt per Live-Test: wirkt
    sofort, kein Serverneustart noetig.

    Ohne AMP ist dieser Schritt kein Problem: main.lua gewaehrt Item-/
    Starter-Kit-Kaeufen ihre Rechte bereits selbst per Engine-Hook."""
    if not config.AMP_ENABLED:
        return False
    try:
        was_added = admin_file.add_temp_admin(steam_id)
    except Exception as e:
        print(f"FEHLER beim temporaeren Admin-Eintrag: {e}")
        return False

    if not was_added:
        print(f"[admin_file] {steam_id} war schon Admin, fasse Eintrag nicht an.")
        return False

    print(f"[admin_file] {steam_id} temporaer als Admin eingetragen (fuer {seconds}s).")
    await asyncio.sleep(10)  # kurz warten, bis die AMP-Aenderung beim Server ankommt

    async def revoke_later():
        await asyncio.sleep(seconds)
        try:
            admin_file.remove_temp_admin(steam_id)
            print(f"[admin_file] {steam_id} wieder aus AdminUsers.ini entfernt.")
        except Exception as e:
            print(f"FEHLER beim Entfernen des temporaeren Admin-Eintrags: {e}")

    asyncio.create_task(revoke_later())
    return True


async def _grant_temp_elevation_and_schedule_revoke(steam_id: str, seconds: int = 20):
    """Stuft einen Spieler kurzzeitig als 'Elevated User' hoch (falls er es nicht
    schon ist) und nimmt das nach 'seconds' Sekunden automatisch wieder zurueck.
    Rueckgabe: True, wenn WIR die Hochstufung vorgenommen haben (und daher auch
    wieder zuruecknehmen), False wenn der Spieler schon vorher elevated war
    (dann fassen wir seinen Status nicht an)."""
    try:
        already_elevated = elevation.is_elevated(steam_id)
    except Exception as e:
        print(f"FEHLER beim Pruefen des Elevated-Status: {e}")
        return False

    if already_elevated:
        print(f"[elevation] {steam_id} war schon elevated, fasse Status nicht an.")
        return False

    try:
        elevation.add_elevated_user(steam_id)
        print(f"[elevation] {steam_id} temporaer elevated (fuer {seconds}s).")
    except Exception as e:
        print(f"FEHLER beim Hochstufen: {e}")
        return False

    async def revoke_later():
        await asyncio.sleep(seconds)
        try:
            elevation.remove_elevated_user(steam_id)
            print(f"[elevation] {steam_id} wieder zurueckgestuft.")
        except Exception as e:
            print(f"FEHLER beim Zuruecknehmen der Elevation: {e}")

    asyncio.create_task(revoke_later())
    return True


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


def _player_stat_value(stat_def: dict, uid: str, current: dict, baseline: dict | None) -> float | None:
    """Berechnet den Anzeigewert fuer einen Spieler + eine Kategorie.
    baseline=None -> Allzeit-Wert. baseline gesetzt -> Wochen-Delta."""
    cur = current.get(uid)
    if cur is None:
        return None
    base = (baseline or {}).get(uid, {})

    if stat_def["kind"] == "record":
        return cur.get(stat_def["column"], 0) if baseline is None else None  # Rekorde nur Allzeit

    if stat_def["kind"] == "counter":
        col = stat_def["column"]
        cur_val = cur.get(col, 0)
        if baseline is None:
            return cur_val
        base_val = base.get(col, 0)
        return leaderboard_snapshot.get_weekly_value(cur_val, base_val)

    if stat_def["kind"] == "ratio":
        num_col, den_col = stat_def["num_column"], stat_def["den_column"]
        if baseline is None:
            num, den = cur.get(num_col, 0), cur.get(den_col, 0)
        else:
            num = leaderboard_snapshot.get_weekly_value(cur.get(num_col, 0), base.get(num_col, 0))
            den = leaderboard_snapshot.get_weekly_value(cur.get(den_col, 0), base.get(den_col, 0))
        if not den:
            return None
        return num / den

    return None


def _rank_stat(stat_def: dict, current: dict, baseline: dict | None, names: dict) -> list[str]:
    scored = []
    for uid in current:
        value = _player_stat_value(stat_def, uid, current, baseline)
        if value is None or value <= 0:
            continue
        scored.append((value, names.get(uid, "?")))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[: config.LEADERBOARD_TOP_N]
    if not top:
        return ["Noch keine Daten"]
    return [f"{i+1}. {name} — {_format_stat_value(stat_def['fmt'], value)}" for i, (value, name) in enumerate(top)]


def _rank_squads(current_squads: dict, baseline_squads: dict | None) -> list[str]:
    scored = []
    for sid, s in current_squads.items():
        cur_score = s.get("score", 0)
        if baseline_squads is None:
            value = cur_score
        else:
            base_score = (baseline_squads.get(str(sid)) or {}).get("score", 0)
            value = leaderboard_snapshot.get_weekly_value(cur_score, base_score)
        if value <= 0:
            continue
        scored.append((value, s.get("name", "?")))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[: config.LEADERBOARD_TOP_N]
    if not top:
        return ["Noch keine Daten"]
    return [f"{i+1}. {name} — {value:.0f} score" for i, (value, name) in enumerate(top)]


def build_leaderboard_embed(mode: str, compact: bool) -> discord.Embed:
    is_weekly = mode == "weekly"
    current_players = leaderboard_stats.get_current_player_data()
    current_squads = leaderboard_stats.get_current_squad_data()

    baseline = None
    baseline_squads = None
    if is_weekly:
        snap = leaderboard_snapshot.get_baseline()
        baseline = snap["players"]
        baseline_squads = snap["squads"]

    if is_weekly:
        snap_reset = leaderboard_snapshot.get_baseline()["reset_at"]
        start = datetime.fromisoformat(snap_reset) if snap_reset else datetime.now()
        end = start + timedelta(days=7)
        title = f"🏆 Die Top-Performer dieser Woche ({start.strftime('%d.%m.%Y')} - {end.strftime('%d.%m.%Y')})"
    else:
        title = "🏆 Allzeit-Bestenlisten"

    embed = discord.Embed(
        title=title,
        description="Überblick über die Top-Kategorien" + ("" if compact else " — alle Kategorien"),
        color=discord.Color.gold(),
    )

    embed.add_field(name="🚩 Top Squads", value="\n".join(_rank_squads(current_squads, baseline_squads)), inline=False)

    defs_to_show = [d for d in leaderboard_stats.STAT_DEFS if (compact is False or d["compact"])]
    if is_weekly:
        defs_to_show = [d for d in defs_to_show if d["kind"] != "record"]

    for stat_def in defs_to_show:
        lines = _rank_stat(
            stat_def,
            {str(uid): v for uid, v in current_players.items()},
            baseline,
            {str(uid): p["name"] for uid, p in current_players.items()},
        )
        embed.add_field(name=f"{stat_def['emoji']} {stat_def['label']}", value="\n".join(lines), inline=False)

    footer = "SCUM Server Automation"
    embed.set_footer(text=footer)
    gif_path = config.LEADERBOARD_WEEKLY_GIF_PATH if is_weekly else config.LEADERBOARD_ALLTIME_GIF_PATH
    gif_name = "weekly.gif" if is_weekly else "alltime.gif"
    if os.path.exists(gif_path) and os.path.getsize(gif_path) <= config.MAX_ATTACHMENT_BYTES:
        embed.set_image(url=f"attachment://{gif_name}")
    return embed


class LeaderboardView(discord.ui.View):
    def __init__(self, mode: str, compact: bool):
        super().__init__(timeout=None)
        self.mode = mode
        self.compact = compact
        label = "🔽 Alle Kategorien anzeigen" if compact else "🔼 Weniger anzeigen"
        button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
        button.callback = self.on_toggle
        self.add_item(button)

    async def on_toggle(self, interaction: discord.Interaction):
        new_compact = not self.compact
        embed = build_leaderboard_embed(self.mode, new_compact)
        view = LeaderboardView(self.mode, new_compact)
        await interaction.response.edit_message(embed=embed, view=view)


async def _send_or_edit_leaderboard(channel, mode: str, gif_path: str, gif_name: str, store_path: str):
    embed = build_leaderboard_embed(mode, compact=True)
    view = LeaderboardView(mode, compact=True)
    gif_file = safe_gif_file(gif_path, gif_name)
    message_id = load_message_id(store_path)

    if message_id:
        try:
            message = await channel.fetch_message(message_id)
            if gif_file:
                await message.edit(embed=embed, view=view, attachments=[gif_file])
            else:
                await message.edit(embed=embed, view=view)
            return
        except discord.NotFound:
            pass

    if gif_file:
        new_message = await channel.send(embed=embed, view=view, file=gif_file)
    else:
        new_message = await channel.send(embed=embed, view=view)
    save_message_id(store_path, new_message.id)


@tasks.loop(seconds=config.LEADERBOARD_ALLTIME_UPDATE_SECONDS)
async def update_alltime_leaderboard():
    channel = client.get_channel(config.LEADERBOARD_ALLTIME_CHANNEL_ID)
    if channel is None:
        print(f"FEHLER: Allzeit-Leaderboard-Channel {config.LEADERBOARD_ALLTIME_CHANNEL_ID} nicht gefunden.")
        return
    try:
        await _send_or_edit_leaderboard(
            channel, "alltime", config.LEADERBOARD_ALLTIME_GIF_PATH, "alltime.gif", config.ALLTIME_MESSAGE_STORE
        )
    except Exception as e:
        print(f"FEHLER beim Allzeit-Leaderboard-Update: {e}")


@tasks.loop(seconds=config.LEADERBOARD_WEEKLY_UPDATE_SECONDS)
async def update_weekly_leaderboard():
    channel = client.get_channel(config.LEADERBOARD_WEEKLY_CHANNEL_ID)
    if channel is None:
        print(f"FEHLER: Wochen-Leaderboard-Channel {config.LEADERBOARD_WEEKLY_CHANNEL_ID} nicht gefunden.")
        return
    try:
        if leaderboard_snapshot.is_reset_due():
            print("[leaderboard] Woechentlicher Reset faellig -> neuer Snapshot, neue Nachricht.")
            leaderboard_snapshot.take_snapshot()
            clear_message_id(config.WEEKLY_MESSAGE_STORE)

        await _send_or_edit_leaderboard(
            channel, "weekly", config.LEADERBOARD_WEEKLY_GIF_PATH, "weekly.gif", config.WEEKLY_MESSAGE_STORE
        )
    except Exception as e:
        print(f"FEHLER beim Wochen-Leaderboard-Update: {e}")


def _clean_weapon_name(weapon: str | None) -> str:
    if not weapon:
        return "unbekannt"
    base = weapon
    bracket = ""
    if "[" in weapon and "]" in weapon:
        base, bracket = weapon.split("[", 1)
        bracket = bracket.rstrip("]").strip()
        base = base.strip()
    for prefix in ("BPC_Weapon_", "BP_Weapon_", "BP_"):
        if base.startswith(prefix):
            base = base[len(prefix):]
    if base.endswith("_C"):
        base = base[:-2]
    base = base.replace("_", " ").strip() or "unbekannt"
    return f"{base} ({bracket})" if bracket else base


KILL_TYPE_STYLE = {
    "player": ("🔫", "PvP-Kill"),
    "zombie": ("🧟", "Zombie-Kill"),
    "animal": ("🐾", "Tier-Kill"),
    "environment": ("💀", "Tod (Umgebung)"),
    "other": ("☠️", "Kill"),
}


def build_killfeed_embed(event: dict, kill_type: str, image_path: str | None) -> discord.Embed:
    killer = event.get("Killer") or {}
    victim = event.get("Victim") or {}
    killer_name = killer.get("ProfileName", "?")
    victim_name = victim.get("ProfileName", "?")
    weapon = _clean_weapon_name(event.get("Weapon"))
    emoji, label = KILL_TYPE_STYLE.get(kill_type, KILL_TYPE_STYLE["other"])

    if kill_type == "player":
        description = f"**{killer_name}** hat **{victim_name}** getötet\n🔫 Waffe: {weapon}"
    elif kill_type == "zombie":
        description = f"**{victim_name}** wurde von einem Zombie getötet"
    elif kill_type == "animal":
        description = f"**{victim_name}** wurde von einem Tier getötet"
    elif kill_type == "environment":
        description = f"**{victim_name}** ist gestorben (Umgebung)"
    else:
        description = f"**{victim_name}** wurde getötet von: {killer_name}"

    embed = discord.Embed(title=f"{emoji} {label}", description=description, color=discord.Color.dark_red())
    if image_path:
        embed.set_image(url="attachment://death_map.png")
    embed.set_footer(text="SCUM Killfeed")
    return embed


@tasks.loop(seconds=config.KILLFEED_CHECK_SECONDS)
async def poll_killfeed():
    channel = client.get_channel(config.KILLFEED_CHANNEL_ID)
    if channel is None:
        print(f"FEHLER: Killfeed-Channel {config.KILLFEED_CHANNEL_ID} nicht gefunden.")
        return

    try:
        events = kill_reader.get_new_kills()
    except Exception as e:
        print(f"Fehler beim Lesen der Kill-Logs: {e}")
        return

    for event in events:
        kill_type = kill_reader.classify_kill(event)
        victim = event.get("Victim") or {}
        killer = event.get("Killer") or {}
        loc = victim.get("ServerLocation") or {}
        image_path = None

        if "X" in loc and "Y" in loc:
            tmp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_kill_map.png")
            try:
                image_path = map_image.create_death_marker_image(loc["X"], loc["Y"], tmp_path)
            except Exception as e:
                print(f"Fehler beim Erzeugen des Kartenausschnitts: {e}")
                image_path = None

        embed = build_killfeed_embed(event, kill_type, image_path)

        try:
            if image_path:
                await channel.send(embed=embed, file=discord.File(image_path, filename="death_map.png"))
            else:
                await channel.send(embed=embed)
        except Exception as e:
            print(f"FEHLER beim Senden des Killfeed-Eintrags: {e}")

        # Fuer die Webseite: Eintrag ins killfeed_log.json anhaengen (letzte N behalten)
        try:
            killer = event.get("Killer") or {}
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "kill_type": kill_type,
                "killer_name": killer.get("ProfileName"),
                "victim_name": victim.get("ProfileName"),
                "weapon": event.get("Weapon"),
                "x": loc.get("X"), "y": loc.get("Y"),
            }
            try:
                with open(config.KILLFEED_LOG_JSON, "r", encoding="utf-8") as f:
                    log = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                log = []
            log.append(log_entry)
            log = log[-config.KILLFEED_LOG_MAX_ENTRIES:]
            with open(config.KILLFEED_LOG_JSON, "w", encoding="utf-8") as f:
                json.dump(log, f)
        except Exception as e:
            print(f"FEHLER beim Schreiben von killfeed_log.json: {e}")

        # Fuer die Kill-Heatmap: Koordinate dauerhaft (aber begrenzt) mitschreiben,
        # getrennt von killfeed_log.json, da letzteres viel kuerzer gehalten wird
        if "X" in loc and "Y" in loc:
            try:
                try:
                    with open(config.KILL_HEATMAP_POINTS_FILE, "r", encoding="utf-8") as f:
                        heatmap_points = json.load(f)
                except (FileNotFoundError, json.JSONDecodeError):
                    heatmap_points = []
                heatmap_points.append({"x": loc["X"], "y": loc["Y"], "kill_type": kill_type})
                heatmap_points = heatmap_points[-config.KILL_HEATMAP_MAX_POINTS:]
                with open(config.KILL_HEATMAP_POINTS_FILE, "w", encoding="utf-8") as f:
                    json.dump(heatmap_points, f)
            except Exception as e:
                print(f"FEHLER beim Schreiben von kill_heatmap_points.json: {e}")

        # Weltereignis: Bonus-Coins bei Kills/Toden im aktuellen Eventgebiet
        if "X" in loc and "Y" in loc:
            event_location = world_event.get_current_location()
            if event_location is not None:
                event_dist = _distance_2d(loc["X"], loc["Y"], event_location["x"], event_location["y"])
                if event_dist <= event_location.get("radius", 400):
                    bonus_lines = []
                    if kill_type == "player":
                        killer_steam_id_event = killer.get("UserId")
                        killer_discord_id_event = (
                            account_links.find_discord_id_by_steam_id(killer_steam_id_event)
                            if killer_steam_id_event else None
                        )
                        if killer_discord_id_event is not None:
                            new_balance = economy.add_coins(
                                killer_discord_id_event, config.WORLD_EVENT_KILL_BONUS_COINS,
                                reason="Weltereignis-Kill-Bonus",
                            )
                            bonus_lines.append(
                                f"<@{killer_discord_id_event}> +{config.WORLD_EVENT_KILL_BONUS_COINS} Coins "
                                f"(Kill im Eventgebiet, neuer Kontostand: {new_balance})"
                            )
                    victim_steam_id_event = victim.get("UserId")
                    victim_discord_id_event = (
                        account_links.find_discord_id_by_steam_id(victim_steam_id_event)
                        if victim_steam_id_event else None
                    )
                    if victim_discord_id_event is not None:
                        new_balance = economy.add_coins(
                            victim_discord_id_event, config.WORLD_EVENT_DEATH_BONUS_COINS,
                            reason="Weltereignis-Todes-Bonus",
                        )
                        bonus_lines.append(
                            f"<@{victim_discord_id_event}> +{config.WORLD_EVENT_DEATH_BONUS_COINS} Coins "
                            f"(Tod im Eventgebiet, neuer Kontostand: {new_balance})"
                        )
                    if bonus_lines:
                        world_event_channel = client.get_channel(config.WORLD_EVENT_CHANNEL_ID)
                        if world_event_channel is not None:
                            try:
                                await world_event_channel.send("🌍 " + " · ".join(bonus_lines))
                            except Exception as e:
                                print(f"FEHLER beim Ankuendigen des Weltereignis-Bonus: {e}")

        # Persoenliche DM, falls das Opfer seinen Account verknuepft hat und das aktiviert ist
        victim_steam_id = victim.get("UserId")
        if victim_steam_id:
            discord_id = account_links.find_discord_id_by_steam_id(victim_steam_id)
            if discord_id is not None:
                link = account_links.get_link(discord_id)
                if link and link.get("notify_on_death"):
                    try:
                        user = await client.fetch_user(discord_id)
                        await user.send(f"💀 Du bist gestorben!\n{embed.description}")
                    except Exception as e:
                        print(f"Konnte Sterbe-DM nicht senden: {e}")


def _format_personal_stats(data: dict) -> str:
    kills, deaths = data.get("kills", 0), data.get("deaths", 0)
    kd = f"{kills/deaths:.2f}" if deaths else str(kills)
    accuracy = f"{(data['shots_hit']/data['shots_fired']*100):.1f}%" if data.get("shots_fired") else "–"
    return (
        f"⚔️ Kills: **{kills}** · 💀 Tode: **{deaths}** · 📊 K/D: **{kd}**\n"
        f"🎯 Kopfschüsse: **{data.get('headshots', 0)}** · 📈 Treffsicherheit: **{accuracy}**\n"
        f"🧟 Puppet-Kills: **{data.get('puppets_killed', 0)}** · 🐾 Tier-Kills: **{data.get('animals_killed', 0)}**\n"
        f"🔒 Schlösser geknackt: **{data.get('locks_picked', 0)}** · 🐟 Fische: **{data.get('fish_caught', 0)}**\n"
        f"⭐ Ruhm: **{int(data.get('fame_points', 0))}** · 💰 Geld: **{int(data.get('money_balance', 0))}**\n"
        f"⏳ Überlebenszeit: **{data.get('minutes_survived', 0)/60:.1f}h** · "
        f"🏃 Distanz: **{data.get('distance_travelled_by_foot', 0)/1000:.1f} km**"
    )


async def _handle_unlink(interaction: discord.Interaction):
    removed = account_links.remove_link(interaction.user.id)
    msg = "🔒 Verknüpfung aufgehoben." if removed else "Du hattest keinen Account verknüpft."
    await interaction.response.send_message(msg, ephemeral=True, delete_after=15)


async def _handle_balance(interaction: discord.Interaction):
    link = account_links.get_link(interaction.user.id)
    if not link:
        await interaction.response.send_message(
            "Du hast noch keinen Account verknüpft. Nutze zuerst 'Account verknüpfen'.",
            ephemeral=True, delete_after=15,
        )
        return
    balance = economy.get_balance(interaction.user.id)
    await interaction.response.send_message(
        f"💰 Dein Kontostand: **{balance} Coins**", ephemeral=True, delete_after=15
    )


STARTER_KIT_ITEMS = [
    "Mountainbike",
    "Rucksack",
    "Militärhemd",
    "Jeans",
    "Wanderschuhe",
    "Baseball-Cap",
    "Jagdmesser",
    "Baseballschläger",
    "2x MRE (Eintopf)",
    "Feldflasche",
    "Verbandspäckchen (groß)",
    "Einfaches Schloss",
]


async def _handle_starter_kit(interaction: discord.Interaction):
    link = account_links.get_link(interaction.user.id)
    if not link:
        await interaction.response.send_message(
            "Du hast noch keinen Account verknüpft. Nutze zuerst 'Account verknüpfen'.",
            ephemeral=True, delete_after=15,
        )
        return

    if account_links.has_claimed_starter_kit(interaction.user.id):
        await interaction.response.send_message(
            "Du hast dein Starter-Paket bereits abgeholt – geht nur einmal pro Account.",
            ephemeral=True, delete_after=15,
        )
        return

    if not account_links.claim_starter_kit(interaction.user.id):
        await interaction.response.send_message("Fehler beim Beanspruchen des Pakets.", ephemeral=True, delete_after=15)
        return

    # Sofort bestaetigen (Discord erlaubt nur 3s bis zur ersten Antwort) - der
    # eigentliche Admin-Grant + Wartezeit dauert laenger, daher per Follow-up.
    await interaction.response.defer(ephemeral=True)

    try:
        await _grant_temp_admin_and_schedule_revoke(link["steam_id"])
        with open(config.TAXI_COMMANDS_FILE, "a", encoding="utf-8") as f:
            f.write(f"STARTER_KIT|{link['player_name']}\n")
    except Exception as e:
        print(f"FEHLER beim Schreiben des Starter-Kit-Kommandos: {e}")

    items_text = "\n".join(f"• {item}" for item in STARTER_KIT_ITEMS)
    await interaction.followup.send(
        f"🎒 Starter-Paket angefordert! Falls du gerade online bist, bekommst du es gleich.\n\n{items_text}",
        ephemeral=True, delete_after=20,
    )


async def _handle_daily_package(interaction: discord.Interaction):
    link = account_links.get_link(interaction.user.id)
    if not link:
        await interaction.response.send_message(
            "Du hast noch keinen Account verknüpft. Nutze zuerst 'Account verknüpfen'.",
            ephemeral=True, delete_after=15,
        )
        return

    remaining = account_links.get_daily_cooldown_remaining(interaction.user.id)
    if remaining is not None:
        await interaction.response.send_message(
            f"⏳ Dein Tagespaket ist noch nicht bereit. Nächste Abholung in **{_format_timedelta(remaining)}**.",
            ephemeral=True, delete_after=15,
        )
        return

    items = []
    for entry in config.get_daily_package_entries():
        item = config.get_shop_item_by_key(entry["item_key"])
        if item is not None:
            items.append({**item, "amount": entry.get("amount", 1)})
    if not items:
        await interaction.response.send_message(
            "Das Tagespaket ist aktuell nicht konfiguriert. Sag Bescheid an einen Admin.",
            ephemeral=True, delete_after=15,
        )
        return

    if not account_links.claim_daily(interaction.user.id):
        await interaction.response.send_message(
            "Dein Tagespaket ist noch nicht bereit.", ephemeral=True, delete_after=15
        )
        return

    # Sofort bestaetigen (Discord erlaubt nur 3s bis zur ersten Antwort) - der
    # eigentliche Admin-Grant + Wartezeit dauert laenger, daher per Follow-up.
    await interaction.response.defer(ephemeral=True)

    try:
        await _deliver_shop_items(link["steam_id"], link["player_name"], items)
        activity_log.log(
            "discord", str(interaction.user), "Tagespaket abgeholt",
            ", ".join(f"{i['name']} x{i.get('amount', 1)}" for i in items) + f" -> {link['player_name']}",
        )
    except Exception as e:
        print(f"FEHLER beim Ausliefern des Tagespakets: {e}")

    items_text = "\n".join(f"• {i['name']}" for i in items)
    await interaction.followup.send(
        f"🎁 Tagespaket abgeholt! Falls du gerade online bist, bekommst du es gleich.\n\n{items_text}\n\n"
        f"Nächste Abholung in {config.DAILY_PACKAGE_COOLDOWN_HOURS}h.",
        ephemeral=True, delete_after=20,
    )


class RedeemCodeModal(discord.ui.Modal, title="Code einlösen"):
    code = discord.ui.TextInput(label="Redeem-Code", placeholder="XXXX-XXXX", max_length=20)

    async def on_submit(self, interaction: discord.Interaction):
        link = account_links.get_link(interaction.user.id)
        if not link:
            await interaction.response.send_message(
                "Du hast noch keinen Account verknüpft. Nutze zuerst 'Account verknüpfen'.",
                ephemeral=True, delete_after=15,
            )
            return

        ok, message, item = redeem_codes.redeem(interaction.user.id, self.code.value)
        if not ok:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True, delete_after=15)
            return

        # Sofort bestaetigen (Discord erlaubt nur 3s bis zur ersten Antwort) - der
        # eigentliche Admin-Grant + Wartezeit dauert laenger, daher per Follow-up.
        await interaction.response.defer(ephemeral=True)
        try:
            await _deliver_shop_items(link["steam_id"], link["player_name"], [item])
            activity_log.log(
                "discord", str(interaction.user), "Redeem-Code eingelöst",
                f"{self.code.value.strip().upper()} -> {item['name']} x{item.get('amount', 1)} -> {link['player_name']}",
            )
        except Exception as e:
            print(f"FEHLER beim Ausliefern des Redeem-Codes: {e}")

        await interaction.followup.send(
            f"🎫 Code eingelöst! Du bekommst **{item['name']}**. Falls du gerade online bist, bekommst du es gleich.",
            ephemeral=True, delete_after=20,
        )


async def _handle_redeem_code(interaction: discord.Interaction):
    await interaction.response.send_modal(RedeemCodeModal())


class ReferralModal(discord.ui.Modal, title="Werbecode einlösen"):
    friend_code = discord.ui.TextInput(label="Werbecode deines Freundes", max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        link = account_links.get_link(interaction.user.id)
        if not link:
            await interaction.response.send_message(
                "Du hast noch keinen Account verknüpft. Nutze zuerst 'Account verknüpfen'.",
                ephemeral=True, delete_after=15,
            )
            return
        if link.get("referred_by") is not None:
            await interaction.response.send_message(
                "Du hast bereits einen Werbecode eingelöst.", ephemeral=True, delete_after=15
            )
            return

        referrer_id = account_links.find_discord_id_by_referral_code(self.friend_code.value)
        if referrer_id is None:
            await interaction.response.send_message("Diesen Werbecode gibt es nicht.", ephemeral=True, delete_after=15)
            return

        if not account_links.apply_referral(interaction.user.id, referrer_id):
            await interaction.response.send_message(
                "Werbecode konnte nicht eingelöst werden (eigener Code oder schon verwendet).",
                ephemeral=True, delete_after=15,
            )
            return

        new_balance = economy.add_coins(interaction.user.id, config.REFERRAL_BONUS_COINS, reason="Freund geworben (geworben)")
        referrer_balance = economy.add_coins(referrer_id, config.REFERRAL_BONUS_COINS, reason="Freund geworben (Werber)")
        await interaction.response.send_message(
            f"👥 Werbecode eingelöst! Du bekommst **{config.REFERRAL_BONUS_COINS} Coins** "
            f"(neuer Kontostand: {new_balance}).",
            ephemeral=True, delete_after=20,
        )
        try:
            referrer_user = await client.fetch_user(referrer_id)
            await referrer_user.send(
                f"👥 **{link['player_name']}** hat deinen Werbecode eingelöst! Du bekommst "
                f"**{config.REFERRAL_BONUS_COINS} Coins** (neuer Kontostand: {referrer_balance})."
            )
        except Exception as e:
            print(f"Konnte Werber nicht per DM benachrichtigen: {e}")


class ReferralRedeemButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Werbecode einlösen", style=discord.ButtonStyle.primary, emoji="🎁")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ReferralModal())


async def _handle_referral(interaction: discord.Interaction):
    link = account_links.get_link(interaction.user.id)
    if not link:
        await interaction.response.send_message(
            "Du hast noch keinen Account verknüpft. Nutze zuerst 'Account verknüpfen'.",
            ephemeral=True, delete_after=15,
        )
        return

    code = account_links.get_referral_code(interaction.user.id)
    lines = [
        f"👥 Dein Werbecode: **{code}**",
        f"Teile ihn mit Freunden - ihr bekommt beide **{config.REFERRAL_BONUS_COINS} Coins**, sobald sie ihn einlösen.",
        f"Bisher geworbene Freunde: **{link.get('referral_count', 0)}**",
    ]

    view = discord.ui.View(timeout=120)
    if link.get("referred_by") is None:
        lines.append("\nHast du selbst einen Werbecode von jemandem bekommen? Klick unten zum Einlösen.")
        view.add_item(ReferralRedeemButton())
    else:
        lines.append("\nDu wurdest bereits geworben (Bonus schon erhalten).")

    await interaction.response.send_message(
        "\n".join(lines), view=view if view.children else None, ephemeral=True, delete_after=60
    )


def _get_live_position(player_name: str) -> tuple[float, float, float] | None:
    """Liest die aktuelle Position eines Online-Spielers aus live_positions.txt
    (vom Lua-Mod alle 8s geschrieben). None, wenn der Spieler nicht online ist."""
    try:
        with open(config.LIVE_POSITIONS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return None
    for line in content.splitlines():
        parts = line.split("|")
        if len(parts) == 4 and parts[0] == player_name:
            try:
                return float(parts[1]), float(parts[2]), float(parts[3])
            except ValueError:
                return None
    return None


def _distance_2d(x1: float, y1: float, x2: float, y2: float) -> float:
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


async def _apply_payout(discord_id: int, steam_id: str, player_name: str, config_entry: dict) -> str:
    """Zahlt die konfigurierte Belohnung aus (Coins/Bargeld/Paket-Artikel) und
    gibt einen Beschreibungstext fuer die Bestaetigungsnachricht zurueck.
    Genutzt von Toten Briefkaesten und Quests."""
    payout_type = config_entry.get("payout_type", "coins")
    if payout_type == "cash":
        amount = int(config_entry.get("payout_amount", 0))
        player_grants.grant_money_and_fame(steam_id, money_delta=amount, player_name=player_name)
        return f"💵 **{amount} Ingame-Geld** gutgeschrieben."
    elif payout_type == "package":
        item = config.get_shop_item_by_key(config_entry.get("payout_package_key", ""))
        if item is None:
            return "⚠️ Belohnungs-Artikel nicht gefunden, sag Bescheid an einen Admin."
        amount = int(config_entry.get("payout_package_amount") or 1)
        await _deliver_shop_items(steam_id, player_name, [{**item, "amount": amount}])
        suffix = f" x{amount}" if amount != 1 else ""
        return f"📦 **{item['name']}{suffix}** wird geliefert (falls du gerade online bist)."
    amount = int(config_entry.get("payout_amount", 0))
    new_balance = economy.add_coins(discord_id, amount, reason="Tote Briefkaesten/Quest")
    return f"💰 **{amount} Coins** gutgeschrieben (neuer Kontostand: {new_balance})."


async def _auto_delete(message: discord.Message, delay: float = 12):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except (discord.HTTPException, discord.NotFound):
        pass


def _build_dead_drop_list_view():
    drops = config.get_dead_drops()
    embed = discord.Embed(
        title="📦 Tote Briefkästen",
        description="Bring die passenden Gegenstände zum jeweiligen Ort, leg sie dort **frei am Boden** ab "
                     "(nicht im Rucksack/Container) und bestätige die Abgabe.",
        color=discord.Color.dark_gold(),
    )
    if not drops:
        embed.description = "Aktuell sind keine Toten Briefkästen eingerichtet."
    view = discord.ui.View(timeout=180)
    for drop in drops:
        view.add_item(DeadDropSelectButton(drop))
    return embed, view


class DeadDropSelectButton(discord.ui.Button):
    def __init__(self, drop: dict):
        super().__init__(label=drop["name"], style=discord.ButtonStyle.secondary)
        self.drop = drop

    async def callback(self, interaction: discord.Interaction):
        embed, view = _build_dead_drop_detail_view(self.drop)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


def _requirement_item_name(item_key: str) -> str:
    item = config.get_shop_item_by_key(item_key)
    return item["name"] if item else f"⚠️ {item_key}"


def _build_dead_drop_detail_view(drop: dict):
    embed = discord.Embed(
        title=f"📦 {drop['name']}", description=drop.get("description", ""), color=discord.Color.dark_gold()
    )
    lines = [f"• {req['amount']}x {_requirement_item_name(req['item_key'])}" for req in drop.get("requirements", [])]
    embed.add_field(name="Benötigt", value="\n".join(lines) or "–", inline=False)
    if drop.get("image_url"):
        embed.set_image(url=drop["image_url"])

    view = discord.ui.View(timeout=180)
    view.add_item(DeadDropConfirmButton(drop))

    back = discord.ui.Button(label="⬅️ Zurück", style=discord.ButtonStyle.secondary)

    async def back_callback(interaction: discord.Interaction):
        embed2, view2 = _build_dead_drop_list_view()
        await interaction.response.edit_message(content=None, embed=embed2, view=view2)

    back.callback = back_callback
    view.add_item(back)
    return embed, view


class DeadDropConfirmButton(discord.ui.Button):
    def __init__(self, drop: dict):
        super().__init__(label="Abgabe bestätigen", style=discord.ButtonStyle.success, emoji="✅")
        self.drop = drop

    async def callback(self, interaction: discord.Interaction):
        drop = self.drop
        link = account_links.get_link(interaction.user.id)
        if not link:
            await interaction.response.send_message(
                "Du hast noch keinen Account verknüpft. Nutze zuerst 'Account verknüpfen'.",
                ephemeral=True, delete_after=15,
            )
            return

        pos = _get_live_position(link["player_name"])
        if pos is None:
            await interaction.response.send_message(
                "Du scheinst nicht online zu sein (oder deine Position wurde noch nicht aktualisiert). "
                "Geh ingame zum Briefkasten und versuch's nochmal.",
                ephemeral=True, delete_after=15,
            )
            return

        radius = drop.get("radius", 15)
        dist = _distance_2d(pos[0], pos[1], drop["x"], drop["y"])
        if dist > radius:
            await interaction.response.send_message(
                f"📍 Du bist noch **{int(dist)}m** vom Briefkasten entfernt (Reichweite: {radius}m). "
                f"Geh näher ran und versuch's nochmal.",
                ephemeral=True, delete_after=15,
            )
            return

        requirements = drop.get("requirements", [])
        if not requirements:
            await interaction.response.send_message(
                "Dieser Briefkasten ist nicht richtig konfiguriert, sag Bescheid an einen Admin.",
                ephemeral=True, delete_after=15,
            )
            return

        resolved = [(req, config.get_shop_item_by_key(req["item_key"])) for req in requirements]
        unresolved = [req for req, item in resolved if item is None]
        if unresolved:
            await interaction.response.send_message(
                "Dieser Briefkasten verweist auf einen Artikel, der nicht mehr im Katalog existiert, "
                "sag Bescheid an einen Admin.",
                ephemeral=True, delete_after=15,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Erst ALLE Anforderungen im Dry-Run pruefen (nichts wird verbraucht),
        # damit bei mehreren Artikeln nicht welche verloren gehen, nur weil
        # ein anderer noch fehlt.
        dry_results = await asyncio.gather(*[
            item_check.check_items_present(
                drop["x"], drop["y"], drop["z"], radius, item["id"], req["amount"], dry_run=True
            )
            for req, item in resolved
        ])
        missing = [(item, req, found) for (req, item), (success, found) in zip(resolved, dry_results) if not success]
        if missing:
            lines = [f"❌ {item['name']}: {found}/{req['amount']} gefunden" for item, req, found in missing]
            await interaction.followup.send(
                "Noch nicht alles da:\n" + "\n".join(lines) +
                "\n\nLeg die fehlenden Gegenstände frei ab (nicht im Rucksack/Container) und versuch's erneut.",
                ephemeral=True,
            )
            return

        # Alles vorhanden -> jetzt wirklich verbrauchen
        await asyncio.gather(*[
            item_check.check_items_present(
                drop["x"], drop["y"], drop["z"], radius, item["id"], req["amount"], dry_run=False
            )
            for req, item in resolved
        ])

        payout_text = await _apply_payout(interaction.user.id, link["steam_id"], link["player_name"], drop)
        activity_log.log(
            "discord", str(interaction.user), "Briefkasten abgegeben",
            f"{drop['name']} ({link['player_name']})",
        )
        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            pass
        msg = await interaction.followup.send(f"✅ Abgabe erfolgreich! {payout_text}", ephemeral=True)
        asyncio.create_task(_auto_delete(msg))


async def _handle_dead_drops(interaction: discord.Interaction):
    embed, view = _build_dead_drop_list_view()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True, delete_after=180)


def _build_quest_list_view():
    quests = config.get_quests()
    embed = discord.Embed(
        title="🗺️ Quests",
        description="Bring die benötigten Gegenstände zum jeweiligen Ort und gib sie ab. "
                     "Teilabgaben sind möglich, dein Fortschritt bleibt erhalten.",
        color=discord.Color.dark_gold(),
    )
    if not quests:
        embed.description = "Aktuell sind keine Quests eingerichtet."
    view = discord.ui.View(timeout=180)
    for quest in quests:
        view.add_item(QuestSelectButton(quest))
    return embed, view


class QuestSelectButton(discord.ui.Button):
    def __init__(self, quest: dict):
        super().__init__(label=quest["name"], style=discord.ButtonStyle.secondary)
        self.quest = quest

    async def callback(self, interaction: discord.Interaction):
        embed, view = _build_quest_detail_view(self.quest, interaction.user.id)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


def _build_quest_detail_view(quest: dict, discord_id: int):
    progress = quest_progress.get_progress(quest["key"], discord_id)
    embed = discord.Embed(
        title=f"🗺️ {quest['name']}", description=quest.get("description", ""), color=discord.Color.dark_gold()
    )
    lines = []
    for req in quest.get("requirements", []):
        item = config.get_shop_item_by_key(req["item_key"])
        item_name = item["name"] if item else req["item_key"]
        have = progress.get(req["item_key"], 0)
        need = req["amount"]
        mark = "✅" if have >= need else "▫️"
        lines.append(f"{mark} {item_name}: **{min(have, need)}/{need}**")
    embed.add_field(name="Fortschritt", value="\n".join(lines) or "–", inline=False)
    if quest.get("image_url"):
        embed.set_image(url=quest["image_url"])

    view = discord.ui.View(timeout=180)
    view.add_item(QuestDeliverButton(quest))

    back = discord.ui.Button(label="⬅️ Zurück", style=discord.ButtonStyle.secondary)

    async def back_callback(interaction: discord.Interaction):
        embed2, view2 = _build_quest_list_view()
        await interaction.response.edit_message(content=None, embed=embed2, view=view2)

    back.callback = back_callback
    view.add_item(back)
    return embed, view


class QuestDeliverButton(discord.ui.Button):
    def __init__(self, quest: dict):
        super().__init__(label="Abgabe versuchen", style=discord.ButtonStyle.success, emoji="✅")
        self.quest = quest

    async def callback(self, interaction: discord.Interaction):
        quest = self.quest
        link = account_links.get_link(interaction.user.id)
        if not link:
            await interaction.response.send_message(
                "Du hast noch keinen Account verknüpft. Nutze zuerst 'Account verknüpfen'.",
                ephemeral=True, delete_after=15,
            )
            return

        pos = _get_live_position(link["player_name"])
        if pos is None:
            await interaction.response.send_message(
                "Du scheinst nicht online zu sein (oder deine Position wurde noch nicht aktualisiert). "
                "Geh ingame zum Questort und versuch's nochmal.",
                ephemeral=True, delete_after=15,
            )
            return

        radius = quest.get("radius", 15)
        dist = _distance_2d(pos[0], pos[1], quest["x"], quest["y"])
        if dist > radius:
            await interaction.response.send_message(
                f"📍 Du bist noch **{int(dist)}m** vom Questort entfernt (Reichweite: {radius}m). "
                f"Geh näher ran und versuch's nochmal.",
                ephemeral=True, delete_after=15,
            )
            return

        await interaction.response.defer(ephemeral=True)

        progress = quest_progress.get_progress(quest["key"], interaction.user.id)
        result_lines = []
        for req in quest.get("requirements", []):
            item = config.get_shop_item_by_key(req["item_key"])
            already = progress.get(req["item_key"], 0)
            still_needed = req["amount"] - already
            if still_needed <= 0 or item is None:
                continue
            success, found = await item_check.check_items_present(
                quest["x"], quest["y"], quest["z"], radius, item["id"], still_needed
            )
            delivered = found if success else min(found, still_needed)
            if delivered > 0:
                progress = quest_progress.add_progress(quest["key"], interaction.user.id, req["item_key"], delivered)
                result_lines.append(f"• {item['name']}: +{delivered} abgegeben")
            else:
                result_lines.append(f"• {item['name']}: nichts gefunden")

        all_done = all(
            progress.get(req["item_key"], 0) >= req["amount"] for req in quest.get("requirements", [])
        )

        if not all_done:
            embed, view = _build_quest_detail_view(quest, interaction.user.id)
            await interaction.followup.send(
                "📦 " + ("\n".join(result_lines) or "Nichts gefunden.") +
                "\n\nNoch nicht vollständig - dein Fortschritt wurde gespeichert.",
                ephemeral=True,
            )
            return

        payout_text = await _apply_payout(interaction.user.id, link["steam_id"], link["player_name"], quest)
        quest_progress.reset_progress(quest["key"], interaction.user.id)
        activity_log.log(
            "discord", str(interaction.user), "Quest abgeschlossen",
            f"{quest['name']} ({link['player_name']})",
        )
        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            pass
        msg = await interaction.followup.send(
            f"🎉 Quest **{quest['name']}** abgeschlossen! {payout_text}", ephemeral=True
        )
        asyncio.create_task(_auto_delete(msg))


async def _handle_quests(interaction: discord.Interaction):
    embed, view = _build_quest_list_view()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True, delete_after=180)


class AccountPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Account verknüpfen", style=discord.ButtonStyle.success, emoji="🔗",
                        custom_id="scumbot_link_account")
    async def link_account(self, interaction: discord.Interaction, button: discord.ui.Button):
        existing = account_links.get_link(interaction.user.id)
        if existing:
            await interaction.response.send_message(
                f"Du bist bereits mit **{existing['player_name']}** verknüpft. "
                f"Nutze zuerst 'Trennen', falls du neu verknüpfen willst.",
                ephemeral=True, delete_after=15,
            )
            return
        code = account_links.create_registration_code(interaction.user.id)
        await interaction.response.send_message(
            f"🔗 Dein Registrierungscode: **{code}**\n"
            f"Tritt dem Server bei und tippe den Code irgendwo in den Spielchat "
            f"(gültig {config.REGISTRATION_CODE_TIMEOUT_MINUTES} Minuten).",
            ephemeral=True, delete_after=config.REGISTRATION_CODE_TIMEOUT_MINUTES * 60,
        )

    @discord.ui.button(label="Trennen", style=discord.ButtonStyle.danger, emoji="🔒",
                        custom_id="scumbot_unlink")
    async def unlink(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_unlink(interaction)

    @discord.ui.button(label="Starter-Paket abholen", style=discord.ButtonStyle.success, emoji="🎒",
                        custom_id="scumbot_starter_kit")
    async def starter_kit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_starter_kit(interaction)

    @discord.ui.button(label="Tagespaket abholen", style=discord.ButtonStyle.success, emoji="🎁",
                        custom_id="scumbot_daily_package")
    async def daily_package(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_daily_package(interaction)

    @discord.ui.button(label="Code einlösen", style=discord.ButtonStyle.primary, emoji="🎫",
                        custom_id="scumbot_redeem_code")
    async def redeem_code(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_redeem_code(interaction)

    @discord.ui.button(label="Freund werben", style=discord.ButtonStyle.success, emoji="👥",
                        custom_id="scumbot_referral")
    async def referral(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_referral(interaction)


class DMAccountView(discord.ui.View):
    """Kompakte Button-Leiste fuer die Bestaetigungs-DM nach dem Verknuepfen
    (ohne 'Account verknuepfen', da zu dem Zeitpunkt schon verknuepft)."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Trennen", style=discord.ButtonStyle.danger, emoji="🔒",
                        custom_id="scumbot_dm_unlink")
    async def unlink(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_unlink(interaction)

    @discord.ui.button(label="Starter-Paket abholen", style=discord.ButtonStyle.success, emoji="🎒",
                        custom_id="scumbot_dm_starter_kit")
    async def starter_kit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_starter_kit(interaction)

    @discord.ui.button(label="Tagespaket abholen", style=discord.ButtonStyle.success, emoji="🎁",
                        custom_id="scumbot_dm_daily_package")
    async def daily_package(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_daily_package(interaction)

    @discord.ui.button(label="Code einlösen", style=discord.ButtonStyle.primary, emoji="🎫",
                        custom_id="scumbot_dm_redeem_code")
    async def redeem_code(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_redeem_code(interaction)

    @discord.ui.button(label="Freund werben", style=discord.ButtonStyle.success, emoji="👥",
                        custom_id="scumbot_dm_referral")
    async def referral(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_referral(interaction)


async def ensure_account_panel_posted():
    channel = client.get_channel(config.ACCOUNT_PANEL_CHANNEL_ID)
    if channel is None:
        print(f"FEHLER: Account-Panel-Channel {config.ACCOUNT_PANEL_CHANNEL_ID} nicht gefunden.")
        return

    message_id = load_message_id(config.ACCOUNT_PANEL_MESSAGE_STORE)
    if message_id:
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(view=AccountPanelView())  # neue Buttons (z.B. Starter-Paket) nachziehen
            return
        except discord.NotFound:
            pass

    embed = discord.Embed(
        title="🔗 Account-Verknüpfung",
        description=(
            "Verknüpfe deinen Discord-Account mit deinem SCUM-Charakter und schalte "
            "exklusive Funktionen frei.\n\n"
            "**So geht's:**\n"
            "1. Klicke unten auf **Account verknüpfen**\n"
            "2. Du erhältst einen Registrierungscode (nur für dich sichtbar)\n"
            "3. Tritt dem Server bei und tippe den Code in den Spielchat\n"
            "4. Deine Accounts werden automatisch verknüpft!\n\n"
            "**Vorteile:**\n"
            "• Nutze **Meine Statistiken**, um deine eigenen Werte zu sehen\n"
            "• Persönliche Benachrichtigung, wenn du ingame stirbst"
        ),
        color=discord.Color.green(),
    )
    embed.set_footer(text="SCUM Server Automation")
    gif_file = safe_gif_file(config.ACCOUNT_PANEL_GIF_PATH, "account.gif")
    if gif_file:
        embed.set_image(url="attachment://account.gif")
        new_message = await channel.send(embed=embed, view=AccountPanelView(), file=gif_file)
    else:
        new_message = await channel.send(embed=embed, view=AccountPanelView())
    save_message_id(config.ACCOUNT_PANEL_MESSAGE_STORE, new_message.id)


_restart_warning_state = {"target": None, "fired": set()}


@tasks.loop(seconds=config.RESTART_WARNING_CHECK_SECONDS)
async def poll_restart_warnings():
    next_dt = next_restart_datetime()

    if _restart_warning_state["target"] != next_dt:
        _restart_warning_state["target"] = next_dt
        _restart_warning_state["fired"] = set()

    minutes_remaining = (next_dt - datetime.now()).total_seconds() / 60

    for threshold in sorted(config.RESTART_WARNING_MINUTES, reverse=True):
        if minutes_remaining <= threshold and threshold not in _restart_warning_state["fired"]:
            _restart_warning_state["fired"].add(threshold)
            message = f"⚠ SERVER NEUSTART IN {threshold} MINUTE{'N' if threshold != 1 else ''} ⚠"
            print(f"[restart_warning] Sende: {message}")
            try:
                with open(config.TAXI_MOD_COMMANDS_FILE, "a", encoding="utf-8") as f:
                    f.write(f"ANNOUNCE|{message}\n")
            except Exception as e:
                print(f"FEHLER beim Schreiben der Neustart-Warnung: {e}")


@tasks.loop(seconds=config.ECONOMY_CHECK_SECONDS)
async def poll_economy_activity():
    try:
        earnings = economy_activity.calculate_activity_earnings()
    except Exception as e:
        print(f"Fehler bei Economy-Aktivitaetspruefung: {e}")
        return

    for uid, (coins, deltas, player_name, steam_id) in earnings.items():
        if not steam_id:
            continue
        discord_id = account_links.find_discord_id_by_steam_id(steam_id)
        if discord_id is None:
            continue  # nicht verknuepft -> kein Discord-Konto zum Gutschreiben

        reason = ", ".join(f"{v}x {k}" for k, v in deltas.items())
        new_balance = economy.add_coins(discord_id, coins, reason=reason)
        print(f"[economy] {player_name}: +{coins} Coins ({reason}) -> Konto {new_balance}")

    # Online-Zeit-Coins
    try:
        online_earnings = economy_online.process_and_get_earned_seconds()
    except Exception as e:
        print(f"Fehler bei Online-Zeit-Berechnung: {e}")
        online_earnings = {}

    for steam_id, (seconds, player_name) in online_earnings.items():
        minutes = seconds / 60
        coins = round(minutes * config.COINS_PER_ONLINE_MINUTE)
        if coins <= 0:
            continue
        discord_id = account_links.find_discord_id_by_steam_id(steam_id)
        if discord_id is None:
            continue

        new_balance = economy.add_coins(discord_id, coins, reason=f"{minutes:.1f}min online")
        print(f"[economy] {player_name}: +{coins} Coins (Online-Zeit) -> Konto {new_balance}")


class BalancePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Kontostand abfragen", style=discord.ButtonStyle.primary, emoji="💰",
                        custom_id="scumbot_balance_panel")
    async def check_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_balance(interaction)


async def ensure_balance_panel_posted():
    channel = client.get_channel(config.BALANCE_PANEL_CHANNEL_ID)
    if channel is None:
        print(f"FEHLER: Konto-Panel-Channel {config.BALANCE_PANEL_CHANNEL_ID} nicht gefunden.")
        return

    message_id = load_message_id(config.BALANCE_PANEL_MESSAGE_STORE)
    if message_id:
        try:
            await channel.fetch_message(message_id)
            return
        except discord.NotFound:
            pass

    embed = discord.Embed(
        title="💰 Spielerkonto",
        description="Klick auf den Button, um deinen aktuellen Kontostand abzufragen. "
                     "Die Antwort ist nur für dich sichtbar.",
        color=discord.Color.gold(),
    )
    new_message = await channel.send(embed=embed, view=BalancePanelView())
    save_message_id(config.BALANCE_PANEL_MESSAGE_STORE, new_message.id)


class TaxiSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=f"{name} — {coords[3]} Coins", value=name, emoji="🚕")
            for name, coords in config.TAXI_DESTINATIONS.items()
        ]
        super().__init__(placeholder="Wähle dein Taxi-Ziel...", options=options, custom_id="scumbot_taxi_select")

    async def callback(self, interaction: discord.Interaction):
        link = account_links.get_link(interaction.user.id)
        if not link:
            await interaction.response.send_message(
                "Du hast noch keinen Account verknüpft. Nutze zuerst 'Account verknüpfen' im Account-Panel.",
                ephemeral=True, delete_after=15,
            )
            return

        dest_name = self.values[0]
        coords = config.TAXI_DESTINATIONS.get(dest_name)
        if not coords:
            await interaction.response.send_message("Unbekanntes Ziel.", ephemeral=True, delete_after=15)
            return

        x, y, z, price = coords
        balance = economy.get_balance(interaction.user.id)
        if balance < price:
            await interaction.response.send_message(
                f"💸 Nicht genug Coins. Die Fahrt nach **{dest_name}** kostet **{price} Coins**, "
                f"du hast aber nur **{balance}**.",
                ephemeral=True, delete_after=15,
            )
            return

        if not economy.spend_coins(interaction.user.id, price):
            await interaction.response.send_message("Fehler beim Abbuchen der Coins.", ephemeral=True, delete_after=15)
            return

        try:
            with open(config.TAXI_COMMANDS_FILE, "a", encoding="utf-8") as f:
                f.write(f"TELEPORT|{link['player_name']}|{x}|{y}|{z}\n")
            new_balance = economy.get_balance(interaction.user.id)
            await interaction.response.send_message(
                f"🚕 Taxi nach **{dest_name}** bezahlt ({price} Coins) und angefordert! "
                f"Falls du gerade online bist, wirst du gleich teleportiert.\n"
                f"Neuer Kontostand: **{new_balance} Coins**",
                ephemeral=True, delete_after=15,
            )
        except Exception as e:
            economy.add_coins(interaction.user.id, price, reason="Rueckerstattung: Taxi-Fehler")
            await interaction.response.send_message(
                f"Fehler beim Anfordern, Coins wurden zurückerstattet: {e}", ephemeral=True, delete_after=15
            )


class TaxiPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TaxiSelect())


async def ensure_taxi_panel_posted():
    channel = client.get_channel(config.TAXI_PANEL_CHANNEL_ID)
    if channel is None:
        print(f"FEHLER: Taxi-Panel-Channel {config.TAXI_PANEL_CHANNEL_ID} nicht gefunden.")
        return

    message_id = load_message_id(config.TAXI_PANEL_MESSAGE_STORE)
    if message_id:
        try:
            await channel.fetch_message(message_id)
            return
        except discord.NotFound:
            pass

    embed = discord.Embed(
        title="🚕 Taxi-Service",
        description="Wähle unten dein Ziel aus – du musst dafür ingame online sein und "
                     "deinen Account verknüpft haben.",
        color=discord.Color.blue(),
    )
    new_message = await channel.send(embed=embed, view=TaxiPanelView())
    save_message_id(config.TAXI_PANEL_MESSAGE_STORE, new_message.id)


def _load_last_mech_run() -> str | None:
    if os.path.exists(config.MECH_SCHEDULE_STATE_FILE):
        with open(config.MECH_SCHEDULE_STATE_FILE, "r") as f:
            return f.read().strip() or None
    return None


def _save_last_mech_run(date_str: str) -> None:
    with open(config.MECH_SCHEDULE_STATE_FILE, "w") as f:
        f.write(date_str)


@tasks.loop(seconds=60)
async def poll_mech_schedule():
    now = datetime.now()
    if now.hour != config.MECH_SCHEDULE_HOUR or now.minute < config.MECH_SCHEDULE_MINUTE:
        return

    today_str = now.strftime("%Y-%m-%d")
    if _load_last_mech_run() == today_str:
        return  # heute schon erledigt

    # Wir stellen auf den WochenTAG NACH dem gleich anstehenden 00:00-Neustart ein
    tomorrow_weekday = (now.weekday() + 1) % 7
    should_disable = (tomorrow_weekday == config.MECH_OFF_WEEKDAY)

    try:
        changed = mech_schedule.set_sentries_disabled(should_disable)
        print(f"[mech_schedule] DisableSentrySpawning={should_disable} gesetzt (Datei geaendert: {changed})")
    except Exception as e:
        print(f"FEHLER beim Umschalten der Mech-Einstellung: {e}")
        return

    if should_disable:
        try:
            with open(config.TAXI_COMMANDS_FILE, "a", encoding="utf-8") as f:
                f.write("DESTROY_SENTRIES|\n")
            print("[mech_schedule] DESTROY_SENTRIES an Lua-Mod gesendet.")
        except Exception as e:
            print(f"FEHLER beim Senden von DESTROY_SENTRIES: {e}")

    _save_last_mech_run(today_str)


def _format_timedelta(td: timedelta) -> str:
    total_minutes = max(1, int(td.total_seconds() // 60))
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


async def _deliver_shop_items(steam_id: str, player_name: str, items: list[dict]):
    """Schreibt fuer jedes Item eine BUY_ITEM-Zeile in die Commands-Datei (gleicher
    Auslieferungsweg wie beim Shop-Kauf) und gewaehrt kurzzeitig Admin-Rechte,
    damit die Auslieferung greift. Wird von Shop, Tagespaket, Redeem-Codes und
    Paketen gleichermassen genutzt."""
    await _grant_temp_admin_and_schedule_revoke(steam_id)
    with open(config.TAXI_COMMANDS_FILE, "a", encoding="utf-8") as f:
        for item in items:
            amount = item.get("amount", 1)
            f.write(f"BUY_ITEM|{player_name}|{item['type']}|{item['id']}|{amount}\n")


async def _do_purchase(interaction: discord.Interaction, item: dict):
    """Zieht Coins ab, vergibt kurzzeitig Admin-Rechte und gibt das Item aus.
    Erwartet, dass die Interaktion noch NICHT beantwortet wurde."""
    link = account_links.get_link(interaction.user.id)
    if not link:
        await interaction.response.edit_message(
            content="Du hast noch keinen Account verknüpft. Nutze zuerst 'Account verknüpfen' im Account-Panel.",
            embeds=[], view=None,
        )
        return

    balance = economy.get_balance(interaction.user.id)
    if balance < item["price"]:
        await interaction.response.edit_message(
            content=f"💸 Nicht genug Coins. **{item['name']}** kostet **{item['price']} Coins**, "
                    f"du hast aber nur **{balance}**.",
            embeds=[], view=None,
        )
        return

    if not economy.spend_coins(interaction.user.id, item["price"]):
        await interaction.response.edit_message(content="Fehler beim Abbuchen der Coins.", embeds=[], view=None)
        return

    await interaction.response.edit_message(
        content=f"⏳ **{item['name']}** wird vorbereitet ({item['price']} Coins abgebucht)...",
        embeds=[], view=None,
    )

    try:
        await _deliver_shop_items(link["steam_id"], link["player_name"], [item])
        new_balance = economy.get_balance(interaction.user.id)
        activity_log.log(
            "discord", str(interaction.user), "Shop-Kauf",
            f"{item['name']} x{item.get('amount', 1)} für {item['price']} Coins -> {link['player_name']}",
        )
        await interaction.followup.send(
            f"🛒 **{item['name']}** gekauft! Falls du gerade online bist, bekommst du es gleich.\n"
            f"Neuer Kontostand: **{new_balance} Coins**",
            ephemeral=True, delete_after=20,
        )
    except Exception as e:
        economy.add_coins(interaction.user.id, item["price"], reason="Rueckerstattung: Shop-Fehler")
        await interaction.followup.send(
            f"Fehler beim Kauf, Coins wurden zurückerstattet: {e}", ephemeral=True, delete_after=20
        )


class ShopBuyButton(discord.ui.Button):
    """Kauft direkt (Bild ist schon in der Kategorie-Ansicht sichtbar, kein
    Zwischenschritt mehr noetig)."""
    def __init__(self, item: dict, category: str):
        super().__init__(
            label=f"{item['name']} — {item['price']} Coins",
            style=discord.ButtonStyle.primary,
        )
        self.item = item
        self.category = category

    async def callback(self, interaction: discord.Interaction):
        await _do_purchase(interaction, self.item)


class ShopItemsBackButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="⬅️ Kategorien", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction):
        embed, view = _build_category_list_view()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class ShopSubcategoriesBackButton(discord.ui.Button):
    """Zurueck zur Unterkategorie-Liste einer Kategorie (nur wenn die Kategorie
    Unterkategorien hat - siehe _build_items_view)."""
    def __init__(self, category: str):
        super().__init__(label="⬅️ Unterkategorien", style=discord.ButtonStyle.secondary, row=4)
        self.category = category

    async def callback(self, interaction: discord.Interaction):
        embed, view = _build_subcategory_list_view(self.category)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class ShopPageButton(discord.ui.Button):
    def __init__(self, category: str, subcategory: str | None, target_page: int, label: str):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=4)
        self.category = category
        self.subcategory = subcategory
        self.target_page = target_page

    async def callback(self, interaction: discord.Interaction):
        embeds, view = _build_items_view(self.category, self.subcategory, self.target_page)
        await interaction.response.edit_message(content=None, embeds=embeds, view=view)


class ShopItemDetailButton(discord.ui.Button):
    """Fuer Artikel mit Zubehoer (z.B. eine Waffe mit Magazin/Munition):
    oeffnet statt direktem Kauf erst eine Detailansicht mit dem Artikel selbst
    plus all seinem Zubehoer, jeweils einzeln kaufbar."""
    def __init__(self, item: dict, category: str, subcategory: str | None):
        super().__init__(label=f"{item['name']} — Details", style=discord.ButtonStyle.secondary)
        self.item = item
        self.category = category
        self.subcategory = subcategory

    async def callback(self, interaction: discord.Interaction):
        embeds, view = _build_item_detail_view(self.item, self.category, self.subcategory)
        await interaction.response.edit_message(content=None, embeds=embeds, view=view)


PAGE_SIZE = 10  # Discord erlaubt maximal 10 Embeds pro Nachricht


def _item_embed(item: dict) -> discord.Embed:
    e = discord.Embed(title=item["name"], color=discord.Color.dark_gold())
    e.add_field(name="Coins", value=str(item["price"]), inline=True)
    if item.get("image_url"):
        e.set_image(url=item["image_url"])
    return e


def _build_items_view(category: str, subcategory: str | None, page: int = 0):
    """Baut eine Liste von Embeds (eine Bild-Karte pro Artikel) plus Buttons
    darunter - fuer Artikel mit Zubehoer ein 'Details'-Button (oeffnet Basis-
    Artikel + Zubehoer einzeln kaufbar), sonst ein direkter Kauf-Button.
    Bei mehr als 10 Artikeln (Discord-Limit) wird automatisch in Seiten
    a 10 Artikel aufgeteilt, mit Weiter/Zurueck."""
    all_items = config.get_shop_base_items(category, subcategory)
    start = page * PAGE_SIZE
    items = all_items[start:start + PAGE_SIZE]

    embeds = [_item_embed(item) for item in items]

    view = discord.ui.View(timeout=120)
    for item in items:
        if config.get_shop_item_accessories(item["key"]):
            view.add_item(ShopItemDetailButton(item, category, subcategory))
        else:
            view.add_item(ShopBuyButton(item, category))

    total_pages = max(1, (len(all_items) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > 0:
        view.add_item(ShopPageButton(category, subcategory, page - 1, "⬅️ Vorherige Seite"))
    if page < total_pages - 1:
        view.add_item(ShopPageButton(category, subcategory, page + 1, "➡️ Nächste Seite"))
    if subcategory is not None:
        view.add_item(ShopSubcategoriesBackButton(category))
    else:
        view.add_item(ShopItemsBackButton())
    return embeds, view


def _build_item_detail_view(item: dict, category: str, subcategory: str | None):
    """Basis-Artikel + all sein Zubehoer (z.B. Waffe + Magazin + Munition),
    jeweils mit eigenem Kauf-Button."""
    accessories = config.get_shop_item_accessories(item["key"])
    all_items = [item] + accessories

    embeds = [_item_embed(i) for i in all_items[:PAGE_SIZE]]

    view = discord.ui.View(timeout=120)
    for i in all_items[:PAGE_SIZE]:
        view.add_item(ShopBuyButton(i, category))

    back = discord.ui.Button(label="⬅️ Zurück", style=discord.ButtonStyle.secondary, row=4)

    async def back_callback(interaction: discord.Interaction):
        embeds2, view2 = _build_items_view(category, subcategory, page=0)
        await interaction.response.edit_message(content=None, embeds=embeds2, view=view2)

    back.callback = back_callback
    view.add_item(back)
    return embeds, view


def _build_subcategory_list_view(category: str):
    subcats = config.get_shop_subcategories(category)
    embed = discord.Embed(
        title=f"🛒 {category}",
        description="Wähle eine Unterkategorie, um die Artikel zu sehen.",
        color=discord.Color.gold(),
    )
    view = discord.ui.View(timeout=120)
    for sub in subcats:
        count = len(config.get_shop_base_items(category, sub))
        view.add_item(SubcategoryButton(category, sub, count))
    view.add_item(ShopItemsBackButton())
    return embed, view


class SubcategoryButton(discord.ui.Button):
    def __init__(self, category: str, subcategory: str, count: int):
        super().__init__(label=f"{subcategory} ({count})", style=discord.ButtonStyle.primary)
        self.category = category
        self.subcategory = subcategory

    async def callback(self, interaction: discord.Interaction):
        embeds, view = _build_items_view(self.category, self.subcategory, page=0)
        await interaction.response.edit_message(content=None, embeds=embeds, view=view)


class ShopCategoryButton(discord.ui.Button):
    def __init__(self, category: str, count: int):
        super().__init__(label=f"{category} ({count})", style=discord.ButtonStyle.primary)
        self.category = category

    async def callback(self, interaction: discord.Interaction):
        subcats = config.get_shop_subcategories(self.category)
        if subcats:
            embed, view = _build_subcategory_list_view(self.category)
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        else:
            embeds, view = _build_items_view(self.category, None, page=0)
            await interaction.response.edit_message(content=None, embeds=embeds, view=view)


def _build_category_list_view():
    items = config.get_purchasable_shop_items()
    counts = {}
    for i in items:
        cat = i.get("category", "Sonstiges")
        counts[cat] = counts.get(cat, 0) + 1
    embed = discord.Embed(
        title="🛒 SCUM Shop",
        description="Wähle eine Kategorie, um die Artikel zu sehen.",
        color=discord.Color.gold(),
    )
    view = discord.ui.View(timeout=120)
    for cat in config.SHOP_CATEGORIES:
        if cat in counts:
            view.add_item(ShopCategoryButton(cat, counts[cat]))
    return embed, view


class ShopOpenButton(discord.ui.Button):
    """Persistentes Element im Haupt-Panel: oeffnet die Kategorie-Liste privat."""
    def __init__(self):
        super().__init__(label="🛒 Shop öffnen", style=discord.ButtonStyle.success, custom_id="scumbot_shop_open")

    async def callback(self, interaction: discord.Interaction):
        embed, view = _build_category_list_view()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True, delete_after=90)


class ShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ShopOpenButton())


async def ensure_shop_panel_posted():
    channel = client.get_channel(config.SHOP_CHANNEL_ID)
    if channel is None:
        print(f"FEHLER: Shop-Channel {config.SHOP_CHANNEL_ID} nicht gefunden.")
        return

    message_id = load_message_id(config.SHOP_PANEL_MESSAGE_STORE)
    if message_id:
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(view=ShopView())
            return
        except discord.NotFound:
            pass

    embed = discord.Embed(
        title="🛒 SCUM Shop",
        description="Klick unten, um den Shop zu öffnen – nach Kategorien sortiert, mit Bildern pro Artikel.",
        color=discord.Color.gold(),
    )
    new_message = await channel.send(embed=embed, view=ShopView())
    save_message_id(config.SHOP_PANEL_MESSAGE_STORE, new_message.id)


class DeadDropsQuestsView(discord.ui.View):
    """Persistentes Panel-Element im gemeinsamen Briefkaesten/Quests-Channel."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Tote Briefkästen", style=discord.ButtonStyle.secondary, emoji="📦",
                        custom_id="scumbot_dead_drops_open")
    async def dead_drops(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_dead_drops(interaction)

    @discord.ui.button(label="Quests", style=discord.ButtonStyle.secondary, emoji="🗺️",
                        custom_id="scumbot_quests_open")
    async def quests(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_quests(interaction)


async def ensure_dead_drops_quests_panel_posted():
    channel = client.get_channel(config.DEAD_DROPS_QUESTS_CHANNEL_ID)
    if channel is None:
        print(f"FEHLER: Briefkästen/Quests-Channel {config.DEAD_DROPS_QUESTS_CHANNEL_ID} nicht gefunden.")
        return

    message_id = load_message_id(config.DEAD_DROPS_QUESTS_PANEL_MESSAGE_STORE)
    if message_id:
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(view=DeadDropsQuestsView())
            return
        except discord.NotFound:
            pass

    embed = discord.Embed(
        title="📦 Tote Briefkästen & 🗺️ Quests",
        description="Klick unten, um verfügbare Tote Briefkästen oder Quests zu sehen.",
        color=discord.Color.dark_gold(),
    )
    new_message = await channel.send(embed=embed, view=DeadDropsQuestsView())
    save_message_id(config.DEAD_DROPS_QUESTS_PANEL_MESSAGE_STORE, new_message.id)


@tasks.loop(minutes=5)
async def poll_shop_refresh():
    """Aktualisiert das Shop-Panel regelmaessig, damit Aenderungen aus dem
    Admin-Webbereich (shop_items.json) ohne Bot-Neustart sichtbar werden."""
    try:
        await ensure_shop_panel_posted()
    except Exception as e:
        print(f"FEHLER beim Aktualisieren des Shop-Panels: {e}")


@tasks.loop(seconds=config.VOTE_CHECK_SECONDS)
async def poll_votes():
    """Prueft die top-games.net Voting-API und schreibt neue Stimmen als
    Coins gut."""
    if config.TOPGAMES_TOKEN.startswith("TODO"):
        return  # noch nicht eingerichtet
    try:
        rewards = vote_rewards.check_and_reward_votes()
        for name, new_votes, discord_id, coins in rewards:
            if discord_id:
                print(f"[vote] {name}: +{new_votes} Stimme(n) -> {coins} Coins gutgeschrieben.")
            else:
                print(f"[vote] {name}: +{new_votes} Stimme(n), aber kein verknuepfter Discord-Account gefunden.")
    except Exception as e:
        print(f"FEHLER beim Pruefen der Voting-API: {e}")


async def _handle_lottery_buy(interaction: discord.Interaction):
    link = account_links.get_link(interaction.user.id)
    if not link:
        await interaction.response.send_message(
            "Du hast noch keinen Account verknüpft. Nutze zuerst 'Account verknüpfen'.",
            ephemeral=True, delete_after=15,
        )
        return

    balance = economy.get_balance(interaction.user.id)
    if balance < config.LOTTERY_TICKET_PRICE:
        await interaction.response.send_message(
            f"💸 Nicht genug Coins. Ein Los kostet **{config.LOTTERY_TICKET_PRICE} Coins**, "
            f"du hast aber nur **{balance}**.",
            ephemeral=True, delete_after=15,
        )
        return

    if not economy.spend_coins(interaction.user.id, config.LOTTERY_TICKET_PRICE):
        await interaction.response.send_message("Fehler beim Abbuchen der Coins.", ephemeral=True, delete_after=15)
        return

    data = lottery.add_ticket(interaction.user.id)
    my_count = data["tickets"][str(interaction.user.id)]
    next_draw = datetime.fromisoformat(data["next_draw_at"])
    await interaction.response.send_message(
        f"🎟️ Los gekauft! Du hast jetzt **{my_count}** Los(e) in dieser Runde.\n"
        f"Aktueller Pot: **{data['pot']} Coins** · Nächste Ziehung: {next_draw.strftime('%d.%m. %H:%M')} Uhr",
        ephemeral=True, delete_after=20,
    )
    try:
        await ensure_lottery_panel_posted()
    except Exception as e:
        print(f"FEHLER beim Aktualisieren des Lotterie-Panels: {e}")


async def _handle_lottery_status(interaction: discord.Interaction):
    data = lottery.get_status()
    my_count = data["tickets"].get(str(interaction.user.id), 0)
    total_tickets = sum(data["tickets"].values())
    next_draw = datetime.fromisoformat(data["next_draw_at"])
    await interaction.response.send_message(
        f"🎰 Aktueller Pot: **{data['pot']} Coins**\n"
        f"Deine Lose: **{my_count}** / insgesamt **{total_tickets}**\n"
        f"Nächste Ziehung: **{next_draw.strftime('%d.%m.%Y %H:%M')} Uhr**",
        ephemeral=True, delete_after=20,
    )


def _build_lottery_embed() -> discord.Embed:
    data = lottery.get_status()
    total_tickets = sum(data["tickets"].values())
    next_draw = datetime.fromisoformat(data["next_draw_at"])
    embed = discord.Embed(
        title="🎰 SCUM Lotterie",
        description="Kauf Lose fuer eine Chance auf den Pot - eine Ziehung findet automatisch statt.",
        color=discord.Color.gold(),
    )
    embed.add_field(name="💰 Aktueller Pot", value=f"{data['pot']} Coins", inline=True)
    embed.add_field(name="🎟️ Verkaufte Lose", value=str(total_tickets), inline=True)
    embed.add_field(name="💵 Preis pro Los", value=f"{config.LOTTERY_TICKET_PRICE} Coins", inline=True)
    embed.add_field(name="⏱️ Nächste Ziehung", value=f"{next_draw.strftime('%d.%m.%Y %H:%M')} Uhr", inline=False)
    return embed


class LotteryPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Los kaufen", style=discord.ButtonStyle.success, emoji="🎟️",
                        custom_id="scumbot_lottery_buy")
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_lottery_buy(interaction)

    @discord.ui.button(label="Mein Status", style=discord.ButtonStyle.secondary, emoji="📊",
                        custom_id="scumbot_lottery_status")
    async def status(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_lottery_status(interaction)


async def ensure_lottery_panel_posted():
    channel = client.get_channel(config.LOTTERY_CHANNEL_ID)
    if channel is None:
        print(f"FEHLER: Lotterie-Channel {config.LOTTERY_CHANNEL_ID} nicht gefunden (config.LOTTERY_CHANNEL_ID setzen).")
        return

    embed = _build_lottery_embed()
    message_id = load_message_id(config.LOTTERY_PANEL_MESSAGE_STORE)
    if message_id:
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(embed=embed, view=LotteryPanelView())
            return
        except discord.NotFound:
            pass

    new_message = await channel.send(embed=embed, view=LotteryPanelView())
    save_message_id(config.LOTTERY_PANEL_MESSAGE_STORE, new_message.id)


@tasks.loop(minutes=config.LOTTERY_REFRESH_MINUTES)
async def poll_lottery_refresh():
    try:
        await ensure_lottery_panel_posted()
    except Exception as e:
        print(f"FEHLER beim Aktualisieren des Lotterie-Panels: {e}")


@tasks.loop(seconds=config.LOTTERY_CHECK_SECONDS)
async def poll_lottery_draw():
    if not lottery.is_draw_due():
        return

    channel = client.get_channel(config.LOTTERY_CHANNEL_ID)
    result = lottery.draw_winner()

    if not result["won"]:
        if channel is not None:
            try:
                if result["total_tickets"] > 0:
                    await channel.send(
                        f"🎰 Ziehung durchgeführt — diesmal **kein Gewinner**! Der Pot von "
                        f"**{result['amount']} Coins** wandert in die nächste Runde."
                    )
                else:
                    await channel.send("🎰 Ziehung durchgeführt, aber niemand hat mitgespielt.")
            except Exception as e:
                print(f"FEHLER beim Ankuendigen der Lotterie-Ziehung: {e}")
    else:
        winner_id = result["winner_discord_id"]
        new_balance = economy.add_coins(winner_id, result["amount"], reason="Lotterie-Gewinn")
        try:
            user = await client.fetch_user(winner_id)
            winner_mention = user.mention
        except Exception:
            winner_mention = f"<@{winner_id}>"
        if channel is not None:
            try:
                await channel.send(
                    f"🎉 **Lotterie-Ziehung!** {winner_mention} gewinnt **{result['amount']} Coins** "
                    f"(bei {result['total_tickets']} verkauften Losen)! Neuer Kontostand: {new_balance} Coins."
                )
            except Exception as e:
                print(f"FEHLER beim Ankuendigen des Lotterie-Gewinners: {e}")

    try:
        await ensure_lottery_panel_posted()
    except Exception as e:
        print(f"FEHLER beim Aktualisieren des Lotterie-Panels nach der Ziehung: {e}")


def _get_online_players_in_radius(x: float, y: float, radius: float) -> list[str]:
    """Liest live_positions.txt und gibt die Namen aller Online-Spieler
    innerhalb des Radius um (x,y) zurueck."""
    try:
        with open(config.LIVE_POSITIONS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return []
    names = []
    for line in content.splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        name, xs, ys, _zs = parts
        try:
            px, py = float(xs), float(ys)
        except ValueError:
            continue
        if _distance_2d(px, py, x, y) <= radius:
            names.append(name)
    return names


async def _drop_world_event_loot(location: dict, channel):
    """Liefert Loot an alle Online-Spieler im Eventgebiet (ueber die bestehende
    BUY_ITEM-Pipeline, wie beim Shop) und kuendigt es an."""
    nearby = _get_online_players_in_radius(location["x"], location["y"], location.get("radius", 400))
    world_event.mark_loot_dropped()
    if not nearby:
        return

    high_pop = len(nearby) >= config.WORLD_EVENT_HIGH_POP_PLAYER_COUNT
    delivered_names = []
    for name in nearby:
        items = world_event.pick_loot_items(high_pop)
        if not items:
            continue
        steam_id = player_lookup.find_steam_id_by_name(name)
        if not steam_id:
            continue
        try:
            await _deliver_shop_items(steam_id, name, items)
            delivered_names.append(name)
        except Exception as e:
            print(f"FEHLER beim Weltereignis-Loot-Abwurf an {name}: {e}")

    if delivered_names and channel is not None:
        try:
            await channel.send(
                f"🎁 Loot-Abwurf bei **{location['name']}**! "
                + ("Bonus-Loot, viele Spieler vor Ort! " if high_pop else "")
                + f"Betroffen: {', '.join(delivered_names)}"
            )
        except Exception as e:
            print(f"FEHLER beim Ankuendigen des Weltereignis-Loot-Abwurfs: {e}")


@tasks.loop(seconds=config.WORLD_EVENT_CHECK_SECONDS)
async def poll_world_event():
    channel = client.get_channel(config.WORLD_EVENT_CHANNEL_ID)
    try:
        if world_event.is_location_change_due():
            location = world_event.pick_new_location()
            if location is None:
                return  # keine Orte konfiguriert
            if channel is not None:
                embed = discord.Embed(
                    title="🌍 Weltereignis verlegt!",
                    description=f"Das Ereignis ist jetzt bei **{location['name']}**!",
                    color=discord.Color.orange(),
                )
                if location.get("image_url"):
                    embed.set_image(url=location["image_url"])
                try:
                    await channel.send(embed=embed)
                except Exception as e:
                    print(f"FEHLER beim Ankuendigen des Weltereignis-Ortswechsels: {e}")
            await _drop_world_event_loot(location, channel)
        elif world_event.is_loot_due():
            location = world_event.get_current_location()
            if location is not None:
                await _drop_world_event_loot(location, channel)
    except Exception as e:
        print(f"FEHLER in poll_world_event: {e}")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.channel.id != config.CHAT_CHANNEL_ID:
        return
    content = message.content.strip()
    if not content:
        return
    display_name = message.author.display_name
    try:
        with open(config.TAXI_COMMANDS_FILE, "a", encoding="utf-8") as f:
            f.write(f"DISCORD_CHAT|{display_name}: {content}\n")
    except Exception as e:
        print(f"FEHLER beim Weiterleiten der Discord-Chat-Nachricht: {e}")


@client.event
async def on_ready():
    print(f"Bot eingeloggt als {client.user}")
    if not update_status.is_running():
        update_status.start()
    if not poll_chat.is_running():
        poll_chat.start()
    if not poll_bunkers.is_running():
        poll_bunkers.start()
    if not update_alltime_leaderboard.is_running():
        update_alltime_leaderboard.start()
    if not update_weekly_leaderboard.is_running():
        update_weekly_leaderboard.start()
    if not poll_killfeed.is_running():
        poll_killfeed.start()
    if not poll_restart_warnings.is_running():
        poll_restart_warnings.start()
    if not poll_economy_activity.is_running():
        poll_economy_activity.start()
    if not poll_mech_schedule.is_running():
        poll_mech_schedule.start()
    if not poll_shop_refresh.is_running():
        poll_shop_refresh.start()
    if not poll_votes.is_running():
        poll_votes.start()
    if not poll_lottery_refresh.is_running():
        poll_lottery_refresh.start()
    if not poll_lottery_draw.is_running():
        poll_lottery_draw.start()
    if not poll_world_event.is_running():
        poll_world_event.start()
    client.add_view(AccountPanelView())
    client.add_view(DMAccountView())
    client.add_view(BalancePanelView())
    client.add_view(TaxiPanelView())
    client.add_view(ShopView())
    client.add_view(LotteryPanelView())
    client.add_view(DeadDropsQuestsView())
    try:
        await ensure_account_panel_posted()
    except Exception as e:
        print(f"FEHLER beim Posten des Account-Panels: {e}")
    try:
        await ensure_balance_panel_posted()
    except Exception as e:
        print(f"FEHLER beim Posten des Konto-Panels: {e}")
    try:
        await ensure_taxi_panel_posted()
    except Exception as e:
        print(f"FEHLER beim Posten des Taxi-Panels: {e}")
    try:
        await ensure_shop_panel_posted()
    except Exception as e:
        print(f"FEHLER beim Posten des Shop-Panels: {e}")
    try:
        await ensure_dead_drops_quests_panel_posted()
    except Exception as e:
        print(f"FEHLER beim Posten des Briefkästen/Quests-Panels: {e}")
    try:
        await ensure_lottery_panel_posted()
    except Exception as e:
        print(f"FEHLER beim Posten des Lotterie-Panels: {e}")


if __name__ == "__main__":
    if not config.DISCORD_BOT_TOKEN or config.DISCORD_BOT_TOKEN.startswith("TODO_"):
        print(
            "\nNoch nicht eingerichtet: es fehlt ein echter Discord-Bot-Token.\n"
            "Bitte zuerst 'python webapp\\app.py' starten, im Browser die Seite\n"
            "/setup aufrufen und das Formular ausfuellen - danach diesen Bot neu starten.\n"
        )
        raise SystemExit(1)
    client.run(config.DISCORD_BOT_TOKEN)
