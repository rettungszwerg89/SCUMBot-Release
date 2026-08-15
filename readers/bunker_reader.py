# Liest die aktuelle gameplay_*.log-Datei und verfolgt den Bunker-Status
# (Active/Locked je Bunker). Erkennt, wenn sich der Status eines Bunkers
# aendert, damit der Bot nur bei echten Aenderungen ein Discord-Update postet.

import glob
import os
import re
from datetime import datetime, timedelta
import config

_state = {
    "current_file": None,
    "position": 0,
    "_first_run": True,
    "bunkers": {},  # name -> {"status": "Active"/"Locked", "seconds_since": int, "seconds_until": int|None, "x":, "y":, "z":}
}

_ACTIVE_RE = re.compile(
    r"\[LogBunkerLock\]\s+(?P<name>\w+)\s+Bunker is Active\.\s+Activated\s+"
    r"(?P<h>\d+)h\s+(?P<m>\d+)m\s+(?P<s>\d+)s ago\.\s+"
    r"X=(?P<x>[-\d.]+)\s+Y=(?P<y>[-\d.]+)\s+Z=(?P<z>[-\d.]+)"
)
_LOCKED_RE = re.compile(
    r"\[LogBunkerLock\]\s+(?P<name>\w+)\s+Bunker is Locked\.\s+Locked\s+"
    r"(?P<lh>\d+)h\s+(?P<lm>\d+)m\s+(?P<ls>\d+)s ago,\s+next Activation in\s+"
    r"(?P<nh>\d+)h\s+(?P<nm>\d+)m\s+(?P<ns>\d+)s\.\s+"
    r"X=(?P<x>[-\d.]+)\s+Y=(?P<y>[-\d.]+)\s+Z=(?P<z>[-\d.]+)"
)


def _find_latest_gameplay_log() -> str | None:
    pattern = os.path.join(config.SCUM_LOGS_PATH, "gameplay_*.log")
    files = glob.glob(pattern)
    if not files:
        return None
    files.sort(key=lambda f: os.path.getmtime(f))
    return files[-1]


def _detect_encoding(path: str) -> str:
    """Erkennt UTF-16 (mit oder ohne BOM) vs. UTF-8. SCUM-Logs sind nicht
    einheitlich kodiert und manche UTF-16-Dateien haben keine BOM-Kennung,
    was man aber am Muster der Null-Bytes erkennen kann (ASCII-Zeichen in
    UTF-16LE haben nach jedem Zeichen ein Null-Byte)."""
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


def _read_new_lines() -> list[str]:
    latest_file = _find_latest_gameplay_log()
    if latest_file is None:
        return []

    if latest_file != _state["current_file"]:
        was_first = _state["current_file"] is None
        _state["current_file"] = latest_file
        _state["position"] = 0
        _state["_first_run"] = False
        print(f"[bunker_reader] Gameplay-Log gefunden: {latest_file} (Encoding: {_detect_encoding(latest_file)})")

    new_lines: list[str] = []
    encoding = _detect_encoding(latest_file)
    try:
        with open(latest_file, "r", encoding=encoding, errors="replace") as f:
            f.seek(_state["position"])
            new_lines = f.readlines()
            _state["position"] = f.tell()
    except FileNotFoundError:
        _state["current_file"] = None
        _state["position"] = 0

    return new_lines


def get_changes() -> list[str]:
    """Liest neue Log-Zeilen, aktualisiert den bekannten Bunker-Status und
    gibt eine Liste der Bunker-Namen zurueck, deren Status (Active/Locked)
    sich seit dem letzten Aufruf geaendert hat."""
    is_very_first_read = _state["current_file"] is None and _state["_first_run"]
    lines = _read_new_lines()
    changed = []

    for line in lines:
        m = _ACTIVE_RE.search(line)
        if m:
            name = m.group("name")
            new_status = "Active"
            old = _state["bunkers"].get(name)
            _state["bunkers"][name] = {
                "status": new_status,
                "seconds_since": int(m.group("h")) * 3600 + int(m.group("m")) * 60 + int(m.group("s")),
                "seconds_until": None,
                "x": float(m.group("x")),
                "y": float(m.group("y")),
                "z": float(m.group("z")),
            }
            if (old is None or old["status"] != new_status) and not is_very_first_read:
                changed.append(name)
            continue

        m = _LOCKED_RE.search(line)
        if m:
            name = m.group("name")
            new_status = "Locked"
            old = _state["bunkers"].get(name)
            seconds_until = int(m.group("nh")) * 3600 + int(m.group("nm")) * 60 + int(m.group("ns"))
            _state["bunkers"][name] = {
                "status": new_status,
                "seconds_since": int(m.group("lh")) * 3600 + int(m.group("lm")) * 60 + int(m.group("ls")),
                "seconds_until": seconds_until,
                "x": float(m.group("x")),
                "y": float(m.group("y")),
                "z": float(m.group("z")),
            }
            if (old is None or old["status"] != new_status) and not is_very_first_read:
                changed.append(name)
            continue

    return changed


def debug_summary() -> str:
    return f"{len(_state['bunkers'])} Bunker bekannt: " + ", ".join(
        f"{name}={info['status']}" for name, info in sorted(_state['bunkers'].items())
    )


def get_current_bunkers() -> dict:
    return _state["bunkers"]
