# Schreibt ITEM_CHECK-Kommandos fuer den Lua-Mod (main.lua: findNearbyFreeItems)
# und wartet asynchron auf die Antwort in config.ITEM_CHECK_RESULTS_FILE.
# Wird von Toten Briefkaesten und Quests gemeinsam genutzt.

import asyncio
import os
import uuid
import config


async def check_items_present(x: float, y: float, z: float, radius: float,
                                item_id: str, amount: int, dry_run: bool = False) -> tuple[bool, int]:
    """Fragt den Lua-Mod, ob 'amount' freie (nicht angelegte) Items vom Typ
    item_id im Radius um (x,y,z) liegen. Bei Erfolg werden sie Lua-seitig
    zerstoert (verbraucht) - AUSSER dry_run=True, dann wird nur geprueft,
    nichts veraendert (fuer Faelle, in denen erst ALLE Anforderungen erfuellt
    sein muessen, bevor irgendwas verbraucht wird). Gibt (erfolg, gefundene_
    anzahl) zurueck - bei Timeout (Lua-Mod antwortet nicht): (False, 0)."""
    request_id = uuid.uuid4().hex[:12]
    dry_run_flag = "1" if dry_run else "0"
    try:
        with open(config.TAXI_COMMANDS_FILE, "a", encoding="utf-8") as f:
            f.write(f"ITEM_CHECK|{request_id}|{x}|{y}|{z}|{radius}|{item_id}|{amount}|{dry_run_flag}\n")
    except Exception as e:
        print(f"[item_check] FEHLER beim Schreiben des ITEM_CHECK-Kommandos: {e}")
        return False, 0

    waited = 0
    while waited < config.ITEM_CHECK_TIMEOUT_SECONDS:
        await asyncio.sleep(config.ITEM_CHECK_POLL_SECONDS)
        waited += config.ITEM_CHECK_POLL_SECONDS
        result = _find_and_consume_result(request_id)
        if result is not None:
            return result
    return False, 0


def _find_and_consume_result(request_id: str) -> tuple[bool, int] | None:
    """Sucht request_id in der Ergebnisdatei und entfernt die Zeile (damit sie
    nicht mehrfach gelesen wird). Gibt (erfolg, anzahl) zurueck, oder None,
    wenn noch keine Antwort da ist."""
    path = config.ITEM_CHECK_RESULTS_FILE
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return None

    remaining = []
    found = None
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) != 3:
            remaining.append(line)
            continue
        rid, success_s, count_s = parts
        if rid == request_id and found is None:
            found = (success_s == "true", int(count_s) if count_s.isdigit() else 0)
        else:
            remaining.append(line)

    if found is not None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(remaining) + ("\n" if remaining else ""))
        except OSError:
            pass
    return found
