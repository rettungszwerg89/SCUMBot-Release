# AMP-API-Client fuer die SCUM-Instanz.
# Kapselt Login, Session-Verwaltung und die Status-Abfrage.
# Nutzt direktes HTTP statt einer Wrapper-Bibliothek (siehe amp_test.py Testreihe).

import requests

# Bestaetigte AMP-ApplicationState-Codes (direkt aus der Live-API deiner Instanz).
STATE_LABELS = {
    -1: "Unbekannt",
    0: "Gestoppt",
    5: "Startet vor...",
    7: "Konfiguriert...",
    10: "Startet...",
    20: "Online",
    30: "Startet neu...",
    40: "Stoppt...",
    45: "Bereitet Ruhezustand vor...",
    50: "Ruhezustand",
    60: "Wartet...",
    70: "Installiert...",
    75: "Aktualisiert...",
    80: "Wartet auf Eingabe",
    100: "Fehler",
    200: "Pausiert",
    250: "Wartungsmodus",
    999: "Unbestimmt",
}


class AMPClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        self.session_id = None

    def login(self) -> bool:
        payload = {
            "username": self.username,
            "password": self.password,
            "token": "",
            "rememberMe": False,
        }
        resp = self.session.post(f"{self.base_url}/API/Core/Login", json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            self.session_id = None
            return False

        self.session_id = data["sessionID"]
        return True

    def _post(self, endpoint: str, extra_payload: dict | None = None) -> dict:
        """Fuehrt einen API-Call aus und meldet sich bei Bedarf automatisch neu an
        (z.B. wenn die Session abgelaufen ist)."""
        if self.session_id is None:
            if not self.login():
                raise RuntimeError("AMP-Login fehlgeschlagen (Zugangsdaten pruefen).")

        payload = {"SESSIONID": self.session_id}
        if extra_payload:
            payload.update(extra_payload)

        resp = self.session.post(f"{self.base_url}/API{endpoint}", json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # Falls die Session ungueltig geworden ist: einmal neu einloggen und wiederholen.
        if isinstance(data, dict) and data.get("Title") in ("Session Not Found", "Unauthorized"):
            if self.login():
                payload["SESSIONID"] = self.session_id
                resp = self.session.post(f"{self.base_url}/API{endpoint}", json=payload, timeout=10)
                resp.raise_for_status()
                data = resp.json()

        return data

    def get_status(self) -> dict:
        return self._post("/Core/GetStatus")

    def get_restart_schedule_description(self) -> str | None:
        """Sucht in den AMP-Zeitplaenen nach einem aktiven Trigger, der einen
        Neustart ausloest, und gibt dessen Beschreibung zurueck (z.B. "Alle 6 Stunden").
        AMP liefert keinen exakten naechsten Zeitpunkt, nur die Regel selbst."""
        try:
            data = self._post("/Core/GetScheduleData")
        except Exception:
            return None

        for trigger in data.get("PopulatedTriggers", []):
            if trigger.get("EnabledState") != 1:
                continue
            for task in trigger.get("Tasks", []):
                if task.get("TaskMethodName") == "Event.GenericModule.Restart":
                    return trigger.get("Description")
        return None

    def get_admin_users(self) -> list[str]:
        result = self._post("/Core/GetConfig", {"node": "Meta.GenericModule.AdminUsers"})
        return result.get("CurrentValue", []) or []

    def set_admin_users(self, steam_ids: list[str]) -> bool:
        import json as _json
        result = self._post("/Core/SetConfig", {
            "node": "Meta.GenericModule.AdminUsers",
            "value": _json.dumps(steam_ids),
        })
        return bool(result.get("Status"))

    def send_console_message(self, message: str) -> dict:
        """Sendet einen Befehl/Text direkt an die Server-Konsole, so als haette
        ein Admin ihn im Ingame-Chat eingetippt (z.B. '#Announce Hallo Welt')."""
        return self._post("/Core/SendConsoleMessage", {"message": message})

    def get_state_label(self, status: dict) -> str:
        state = status.get("State")
        return STATE_LABELS.get(state, f"Unbekannt ({state})")
