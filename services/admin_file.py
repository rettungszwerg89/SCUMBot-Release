# Verwaltet TEMPORAERE Admin-Eintraege ueber die AMP-API (Meta.GenericModule.AdminUsers),
# damit nicht-Admin-Spieler kurzzeitig Items/Fahrzeuge per echtem Admin-Befehl
# bekommen koennen. Bestaetigt per Live-Test: wirkt sofort, kein Serverneustart.
#
# WICHTIG: add_temp_admin/remove_temp_admin machen ein Lesen-Aendern-Schreiben
# auf einer GEMEINSAMEN Liste. Wenn zwei Kaeufe/Anfragen fast gleichzeitig
# passieren (auch prozessuebergreifend: Bot + Webseite), kann sonst der eine
# Vorgang die Aenderung des anderen ueberschreiben (klassische Race Condition).
# Eine datei-basierte Sperre (funktioniert ueber Prozessgrenzen hinweg, da
# beide auf dieselbe Datei auf derselben Maschine zugreifen) verhindert das.

import os
import time
import random
from services.amp_client import AMPClient
import config

_amp = AMPClient(config.AMP_URL, config.AMP_USER, config.AMP_PASSWORD)
_LOCK_PATH = config.ADMIN_LIST_LOCK_FILE


class _FileLock:
    """Einfache, portable (Windows-kompatible) Sperre ueber exklusives
    Anlegen einer Lock-Datei. Kein zusaetzliches Package noetig."""

    def __init__(self, path: str, timeout: float = 15.0):
        self.path = path
        self.timeout = timeout

    def __enter__(self):
        start = time.time()
        while True:
            try:
                # O_CREAT|O_EXCL: schlaegt fehl, wenn die Datei schon existiert
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                if time.time() - start > self.timeout:
                    # Alte/haengengebliebene Lock-Datei (z.B. nach Absturz) -> aufraeumen
                    try:
                        os.remove(self.path)
                    except OSError:
                        pass
                    continue
                time.sleep(0.05 + random.random() * 0.1)

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            os.remove(self.path)
        except OSError:
            pass


def is_admin(steam_id: str) -> bool:
    if not config.AMP_ENABLED:
        return False
    return steam_id in _amp.get_admin_users()


def add_temp_admin(steam_id: str) -> bool:
    """Gibt True zurueck, wenn WIR den Eintrag neu hinzugefuegt haben (und ihn
    daher auch wieder entfernen sollten). False, wenn der Spieler schon vorher
    Admin war (dann fassen wir die Liste nicht an).

    Ohne AMP (config.AMP_ENABLED=False) ist dieser Weg gar nicht noetig: der
    Lua-Mod (main.lua, withTemporaryAdmin) gewaehrt privilegierte Befehle
    bereits selbst auf Engine-Ebene. Wir geben dann nur False zurueck, ohne
    etwas anzufassen - der Aufrufer liefert trotzdem normal aus."""
    if not config.AMP_ENABLED:
        return False
    with _FileLock(_LOCK_PATH):
        current = _amp.get_admin_users()
        if steam_id in current:
            return False
        new_list = current + [steam_id]
        _amp.set_admin_users(new_list)
        return True


def remove_temp_admin(steam_id: str) -> None:
    if not config.AMP_ENABLED:
        return
    with _FileLock(_LOCK_PATH):
        current = _amp.get_admin_users()
        new_list = [s for s in current if s != steam_id]
        if len(new_list) != len(current):
            _amp.set_admin_users(new_list)
