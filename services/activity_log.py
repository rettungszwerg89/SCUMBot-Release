# Admin-Aktivitätsprotokoll: haelt fest, wer (Discord-Nutzer ODER Webapp-Admin)
# wann welche folgenreiche Aktion ausgeloest hat - z.B. Shop-Kaeufe, Redeem-
# Code-Einloesungen, Briefkasten-/Quest-Abgaben sowie alle Admin-Aktionen aus
# der Live-Karte (Teleport, Item/Geld/Ruhm vergeben, Custom-Befehl) und
# Redeem-Code-Erstellung. Nicht fuer jedes Klein-Event gedacht (kein Ersatz
# fuer die SCUM-eigenen Logs im Log Viewer), sondern fuer die Frage "wer hat
# das gemacht", wenn im Nachhinein etwas auffaellt.

import json
from datetime import datetime
import config


def _load() -> list:
    try:
        with open(config.ACTIVITY_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(entries: list) -> None:
    with open(config.ACTIVITY_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(entries[-config.ACTIVITY_LOG_MAX_ENTRIES:], f, indent=2, ensure_ascii=False)


def log(source: str, actor: str, action: str, details: str = "") -> None:
    """source: 'discord' oder 'web'. actor: Discord-Anzeigename oder Admin-Name.
    action: kurze Kategorie (z.B. 'Shop-Kauf'). details: Freitext mit Konkretem."""
    entries = _load()
    entries.append({
        "timestamp": datetime.now().isoformat(),
        "source": source,
        "actor": actor,
        "action": action,
        "details": details,
    })
    _save(entries)


def get_entries(source: str | None = None, limit: int = 300) -> list:
    """Neueste zuerst, optional nach source gefiltert."""
    entries = list(reversed(_load()))
    if source:
        entries = [e for e in entries if e.get("source") == source]
    return entries[:limit]
