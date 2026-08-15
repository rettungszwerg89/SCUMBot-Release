# Liest die aktuelle login_*.log und verfolgt, wie lange Spieler online sind.
# Coins werden nicht erst beim Ausloggen vergeben, sondern bei jedem Tick fuer
# die seit dem letzten Tick vergangene Online-Zeit (bessere UX: man sieht
# waehrend des Spielens Fortschritt statt erst am Ende der Session).

import glob
import os
import re
from datetime import datetime
import config

_state = {
    "current_file": None,
    "position": 0,
    "_first_run": True,
    # steamid -> {"checkpoint": datetime, "player": name}
    "sessions": {},
}

_LOGIN_RE = re.compile(
    r"^[\d.]+-[\d.]+:\s*'\S+\s+(?P<steamid>\d+):(?P<player>.+?)\((?P<slot>\d+)\)'\s+"
    r"logged (?P<action>in|out) at:"
)


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


def _find_latest_login_log() -> str | None:
    pattern = os.path.join(config.SCUM_LOGS_PATH, "login_*.log")
    files = glob.glob(pattern)
    if not files:
        return None
    files.sort(key=lambda f: os.path.getmtime(f))
    return files[-1]


def _read_new_lines() -> list[str]:
    latest_file = _find_latest_login_log()
    if latest_file is None:
        return []

    if latest_file != _state["current_file"]:
        _state["current_file"] = latest_file
        if _state["_first_run"]:
            _state["position"] = os.path.getsize(latest_file)  # Historie nicht nachtragen
        else:
            _state["position"] = 0
        _state["_first_run"] = False
        print(f"[economy_online] Login-Log gefunden: {latest_file}")

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


def process_and_get_earned_seconds() -> dict:
    """Liest neue Login/Logout-Zeilen und gibt {steamid: (sekunden, player_name)}
    zurueck - die seit dem letzten Aufruf online verbrachte Zeit je Spieler."""
    now = datetime.now()
    lines = _read_new_lines()
    results: dict[str, list] = {}

    def add_result(steamid, player, seconds):
        if steamid not in results:
            results[steamid] = [0.0, player]
        results[steamid][0] += seconds

    for line in lines:
        m = _LOGIN_RE.match(line.strip())
        if not m:
            continue
        steamid, player, action = m.group("steamid"), m.group("player"), m.group("action")

        if action == "in":
            _state["sessions"][steamid] = {"checkpoint": now, "player": player}
        elif action == "out":
            session = _state["sessions"].pop(steamid, None)
            if session:
                elapsed = (now - session["checkpoint"]).total_seconds()
                if elapsed > 0:
                    add_result(steamid, player, elapsed)

    # Laufende Sessions: seit dem letzten Checkpoint vergangene Zeit gutschreiben
    for steamid, info in _state["sessions"].items():
        elapsed = (now - info["checkpoint"]).total_seconds()
        if elapsed > 0:
            add_result(steamid, info["player"], elapsed)
            info["checkpoint"] = now

    return {sid: (secs, name) for sid, (secs, name) in results.items()}
