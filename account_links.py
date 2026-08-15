# Verwaltet die Verknuepfung zwischen Discord-Accounts und SCUM-Charakteren
# (per SteamID) sowie die temporaeren Registrierungscodes.

import json
import os
import random
import string
from datetime import datetime, timedelta
import config

# Registrierungscodes muessen nicht neustart-fest sein (kurzlebig) -> im Speicher
_pending_codes: dict[str, dict] = {}  # code -> {"discord_id": int, "expires_at": datetime}


def _load_links() -> dict:
    if not os.path.exists(config.ACCOUNT_LINKS_FILE):
        return {}
    with open(config.ACCOUNT_LINKS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_links(data: dict) -> None:
    with open(config.ACCOUNT_LINKS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def create_registration_code(discord_id: int) -> str:
    """Erstellt einen neuen 6-stelligen Code fuer diesen Discord-User (alte
    Codes desselben Users werden ungueltig)."""
    for code, info in list(_pending_codes.items()):
        if info["discord_id"] == discord_id:
            del _pending_codes[code]

    code = "".join(random.choices(string.digits, k=6))
    _pending_codes[code] = {
        "discord_id": discord_id,
        "expires_at": datetime.now() + timedelta(minutes=config.REGISTRATION_CODE_TIMEOUT_MINUTES),
    }
    return code


def try_consume_code(message_text: str, steam_id: str, player_name: str) -> int | None:
    """Prueft, ob message_text (Ingame-Chat-Nachricht) genau einem offenen Code
    entspricht. Falls ja: Account verknuepfen und Discord-ID zurueckgeben."""
    text = message_text.strip()
    now = datetime.now()

    # Abgelaufene Codes aufraeumen
    for code in list(_pending_codes.keys()):
        if _pending_codes[code]["expires_at"] < now:
            del _pending_codes[code]

    info = _pending_codes.get(text)
    if info is None:
        return None

    discord_id = info["discord_id"]
    del _pending_codes[text]

    links = _load_links()
    links[str(discord_id)] = {
        "steam_id": steam_id,
        "player_name": player_name,
        "linked_at": now.isoformat(),
        "notify_on_death": False,
        "referral_code": _generate_referral_code(links),
        "referred_by": None,
        "referral_count": 0,
    }
    _save_links(links)
    return discord_id


def _generate_referral_code(links: dict) -> str:
    """Erzeugt einen kurzen, eindeutigen Werbecode fuer einen neu verknuepften
    Account (Freund-werben-Feature)."""
    alphabet = string.ascii_uppercase + string.digits
    existing = {info.get("referral_code") for info in links.values()}
    code = "".join(random.choices(alphabet, k=6))
    while code in existing:
        code = "".join(random.choices(alphabet, k=6))
    return code


def get_referral_code(discord_id: int) -> str | None:
    """Gibt den Werbecode zurueck - erzeugt ihn nachtraeglich, falls der Account
    vor Einfuehrung des Freund-werben-Features verknuepft wurde."""
    links = _load_links()
    key = str(discord_id)
    if key not in links:
        return None
    if not links[key].get("referral_code"):
        links[key]["referral_code"] = _generate_referral_code(links)
        links[key].setdefault("referred_by", None)
        links[key].setdefault("referral_count", 0)
        _save_links(links)
    return links[key]["referral_code"]


def find_discord_id_by_referral_code(code: str) -> int | None:
    normalized = code.strip().upper()
    for discord_id, info in _load_links().items():
        if info.get("referral_code") == normalized:
            return int(discord_id)
    return None


def apply_referral(discord_id: int, referrer_discord_id: int) -> bool:
    """Setzt referred_by fuer discord_id und erhoeht den referral_count des
    Werbers. Gibt False zurueck, wenn discord_id sich selbst wirbt, schon
    geworben wurde, oder einer der beiden keinen verknuepften Account hat."""
    if discord_id == referrer_discord_id:
        return False
    links = _load_links()
    key, referrer_key = str(discord_id), str(referrer_discord_id)
    if key not in links or referrer_key not in links:
        return False
    if links[key].get("referred_by") is not None:
        return False
    links[key]["referred_by"] = referrer_discord_id
    links[referrer_key]["referral_count"] = links[referrer_key].get("referral_count", 0) + 1
    _save_links(links)
    return True


def get_link(discord_id: int) -> dict | None:
    return _load_links().get(str(discord_id))


def remove_link(discord_id: int) -> bool:
    links = _load_links()
    if str(discord_id) in links:
        del links[str(discord_id)]
        _save_links(links)
        return True
    return False


def toggle_notify_on_death(discord_id: int) -> bool | None:
    """Schaltet die Sterbe-Benachrichtigung um, gibt den neuen Zustand zurueck
    (oder None, wenn der Account nicht verknuepft ist)."""
    links = _load_links()
    key = str(discord_id)
    if key not in links:
        return None
    links[key]["notify_on_death"] = not links[key].get("notify_on_death", False)
    _save_links(links)
    return links[key]["notify_on_death"]


def get_daily_cooldown_remaining(discord_id: int) -> timedelta | None:
    """Gibt die verbleibende Cooldown-Zeit bis zum naechsten Tagespaket zurueck,
    oder None, wenn gerade abholbereit (oder noch nie abgeholt)."""
    link = _load_links().get(str(discord_id))
    if not link or not link.get("last_daily_claim"):
        return None
    next_claim = datetime.fromisoformat(link["last_daily_claim"]) + timedelta(hours=config.DAILY_PACKAGE_COOLDOWN_HOURS)
    remaining = next_claim - datetime.now()
    return remaining if remaining.total_seconds() > 0 else None


def claim_daily(discord_id: int) -> bool:
    """Setzt den Cooldown-Zeitstempel fuers Tagespaket. Gibt False zurueck,
    wenn kein Account verknuepft ist oder der Cooldown noch laeuft."""
    links = _load_links()
    key = str(discord_id)
    if key not in links:
        return False
    if get_daily_cooldown_remaining(discord_id) is not None:
        return False
    links[key]["last_daily_claim"] = datetime.now().isoformat()
    _save_links(links)
    return True


def has_claimed_starter_kit(discord_id: int) -> bool:
    link = _load_links().get(str(discord_id))
    return bool(link and link.get("starter_kit_claimed"))


def claim_starter_kit(discord_id: int) -> bool:
    """Markiert das Starter-Paket als abgeholt. Gibt False zurueck, wenn
    kein verknuepfter Account existiert oder es schon abgeholt wurde."""
    links = _load_links()
    key = str(discord_id)
    if key not in links:
        return False
    if links[key].get("starter_kit_claimed"):
        return False
    links[key]["starter_kit_claimed"] = True
    _save_links(links)
    return True


def reset_starter_kit(discord_id: int) -> bool:
    """Setzt das Starter-Paket zurueck, damit der Spieler es erneut abholen
    kann (Admin-Funktion). Gibt False zurueck, wenn kein Account verknuepft ist."""
    links = _load_links()
    key = str(discord_id)
    if key not in links:
        return False
    links[key]["starter_kit_claimed"] = False
    _save_links(links)
    return True


def find_discord_id_by_steam_id(steam_id: str) -> int | None:
    links = _load_links()
    for discord_id, info in links.items():
        if info.get("steam_id") == steam_id:
            return int(discord_id)
    return None
