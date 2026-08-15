# Liest die aktuelle kill_*.log und parst neue Kill-Events.
# SCUM schreibt pro Kill ZWEI Zeilen: eine lesbare Textzeile und direkt
# danach eine JSON-Zeile mit denselben Daten - wir nutzen nur die JSON-Zeile,
# da sie zuverlaessig zu parsen ist.
#
# Erwartetes JSON-Format (Community-Referenz, ggf. je nach SCUM-Version leicht
# abweichend - bei Bedarf anhand echter Beispiele anpassen):
# {"Killer": {"ServerLocation": {"X":.., "Y":.., "Z":..}, "ProfileName":.., "UserId":..},
#  "Victim": {"ServerLocation": {"X":.., "Y":.., "Z":..}, "ProfileName":.., "UserId":..},
#  "Weapon": "...", "TimeOfDay": "..."}

import glob
import json
import os
import re
import config

_state = {
    "current_file": None,
    "position": 0,
    "_first_run": True,
}


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


def _find_latest_kill_log() -> str | None:
    pattern = os.path.join(config.SCUM_LOGS_PATH, "kill_*.log")
    files = glob.glob(pattern)
    if not files:
        return None
    files.sort(key=lambda f: os.path.getmtime(f))
    return files[-1]


def _read_new_lines() -> list[str]:
    latest_file = _find_latest_kill_log()
    if latest_file is None:
        return []

    if latest_file != _state["current_file"]:
        _state["current_file"] = latest_file
        if _state["_first_run"]:
            # Beim ersten Start ans Dateiende springen, keine alten Kills nachtragen
            _state["position"] = os.path.getsize(latest_file)
        else:
            _state["position"] = 0
        _state["_first_run"] = False
        print(f"[kill_reader] Kill-Log gefunden: {latest_file}")

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


def _extract_json(line: str) -> dict | None:
    """Die Zeile beginnt mit 'YYYY.MM.DD-HH.MM.SS: {...json...}' - wir schneiden
    den Zeitstempel ab und parsen den Rest als JSON. Nicht-JSON-Zeilen (die
    lesbare Textzeile) werden ignoriert."""
    idx = line.find("{")
    if idx == -1:
        return None
    try:
        return json.loads(line[idx:])
    except json.JSONDecodeError:
        return None


ANIMAL_KEYWORDS = ["bear", "wolf", "boar", "horse", "goat", "deer", "chicken",
                    "rabbit", "donkey", "shark", "crow", "seagull"]


def classify_kill(event: dict) -> str:
    """Gibt 'player', 'zombie', 'animal' oder 'other' zurueck, je nachdem,
    wer/was den Kill verursacht hat."""
    killer = event.get("Killer")
    if not killer:
        return "environment"

    user_id = killer.get("UserId")
    if user_id:
        return "player"

    name = (killer.get("ProfileName") or "").lower()
    if "puppet" in name or "zombie" in name:
        return "zombie"
    if any(kw in name for kw in ANIMAL_KEYWORDS):
        return "animal"
    return "other"


def get_new_kills() -> list[dict]:
    """Liest neue Zeilen und gibt eine Liste geparster Kill-Events zurueck."""
    lines = _read_new_lines()
    events = []
    for line in lines:
        data = _extract_json(line)
        if data is None:
            continue
        if "Victim" not in data:
            continue  # keine erkennbare Kill-Struktur
        events.append(data)
    return events
