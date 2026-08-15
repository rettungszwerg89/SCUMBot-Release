# Schaltet die Mech/Sentry-Spawns in ServerSettings.ini je nach Wochentag um.
# Sonntags aus, unter der Woche an. Aenderung wirkt erst nach einem Neustart -
# daher zeitlich kurz vor den 00:00-Neustart gelegt (siehe config.MECH_SCHEDULE_*).

import re
import config

_SETTING_LINE_RE = re.compile(r"^scum\.DisableSentrySpawning=(True|False)\s*$", re.MULTILINE)


def set_sentries_disabled(disabled: bool) -> bool:
    """Schreibt scum.DisableSentrySpawning=True/False in die ServerSettings.ini.
    Gibt True zurueck, wenn die Zeile gefunden und geaendert wurde."""
    with open(config.SERVER_SETTINGS_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    new_value = "True" if disabled else "False"
    new_line = f"scum.DisableSentrySpawning={new_value}"

    if not _SETTING_LINE_RE.search(content):
        return False

    new_content = _SETTING_LINE_RE.sub(new_line, content)
    with open(config.SERVER_SETTINGS_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True


def get_sentries_disabled() -> bool | None:
    with open(config.SERVER_SETTINGS_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    m = _SETTING_LINE_RE.search(content)
    if not m:
        return None
    return m.group(1) == "True"
