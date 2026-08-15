# Liest die aktuelle SCUM chat_*.log-Datei aus und liefert neue Zeilen.
# SCUM legt pro Server-Start eine neue Datei mit Zeitstempel im Namen an
# (z.B. chat_20260806133220.log) - wir suchen daher bei jedem Check die
# neueste Datei und merken uns Dateiname + Leseposition.

import glob
import os
import re
import config

_state = {
    "current_file": None,
    "position": 0,
}

# Beispiel-Zeile: 2026.08.06-15.21.56: '76561190000000000:Spielername(3)' 'Local: Hallo'
_CHAT_LINE_RE = re.compile(
    r"^(?P<timestamp>[\d.]+-[\d.]+):\s*"
    r"'(?P<steamid>\d+):(?P<player>.+?)\((?P<slot>\d+)\)'\s*"
    r"'(?P<chat_type>\w+):\s*(?P<message>.*)'$"
)


def parse_chat_line(line: str) -> dict | None:
    """Zerlegt eine Zeile aus chat_*.log in ihre Bestandteile.
    Gibt None zurueck, wenn die Zeile keine Chat-Nachricht ist (z.B. 'Game version: ...')."""
    match = _CHAT_LINE_RE.match(line.strip())
    if not match:
        return None
    return match.groupdict()


def _find_latest_chat_log() -> str | None:
    pattern = os.path.join(config.SCUM_LOGS_PATH, "chat_*.log")
    files = glob.glob(pattern)
    if not files:
        print(f"[chat_reader] Keine Datei gefunden fuer Muster: {pattern}")
        return None
    # Neueste Datei anhand des Zeitstempels im Dateinamen (bzw. Aenderungsdatum als Fallback)
    files.sort(key=lambda f: os.path.getmtime(f))
    return files[-1]


def _detect_encoding(path: str) -> str:
    try:
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError:
        return "utf-8"

    if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"

    if len(head) >= 8:
        odd_bytes = head[1::2]
        if odd_bytes and (odd_bytes.count(0) / len(odd_bytes)) > 0.6:
            return "utf-16-le"

    return "utf-8"


def get_new_lines() -> list[str]:
    """Gibt alle neuen Zeilen seit dem letzten Aufruf zurueck.
    Erkennt automatisch, wenn eine neue chat_*.log (nach Serverneustart) begonnen hat."""
    latest_file = _find_latest_chat_log()
    if latest_file is None:
        return []

    if latest_file != _state["current_file"]:
        _state["current_file"] = latest_file
        if _state["position"] == 0 and _state.get("_first_run", True):
            # Beim allerersten Start nicht die komplette bisherige Historie posten,
            # sondern erst ab jetzt neue Zeilen erfassen.
            _state["position"] = os.path.getsize(latest_file)
            print(f"[chat_reader] Chat-Log gefunden: {latest_file} (Startposition: {_state['position']} Bytes)")
        else:
            # Datei wurde gewechselt (z.B. Serverneustart) -> neue Datei von vorne lesen
            _state["position"] = 0
            print(f"[chat_reader] Neue Chat-Log-Datei erkannt: {latest_file}")
        _state["_first_run"] = False

    new_lines: list[str] = []
    try:
        with open(latest_file, "r", encoding=_detect_encoding(latest_file), errors="replace") as f:
            f.seek(_state["position"])
            new_lines = f.readlines()
            _state["position"] = f.tell()
    except FileNotFoundError:
        # Datei wurde evtl. gerade erst angelegt/rotiert -> beim naechsten Mal neu versuchen
        _state["current_file"] = None
        _state["position"] = 0

    return [line.rstrip("\n").rstrip("\r") for line in new_lines if line.strip()]
