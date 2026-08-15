# Testskript: Setzt Meta.GenericModule.AdminUsers per AMP-API (Core/SetConfig)
# und liest danach zur Kontrolle wieder aus.

import requests
import json as jsonlib
import config

session = requests.Session()
session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

login_resp = session.post(
    config.AMP_URL + "/API/Core/Login",
    json={"username": config.AMP_USER, "password": config.AMP_PASSWORD, "token": "", "rememberMe": False},
)
login_data = login_resp.json()
if not login_data.get("success"):
    print("LOGIN FEHLGESCHLAGEN:", login_data)
    exit()

session_id = login_data["sessionID"]

TEST_STEAM_ID = "00000000000000000"  # <-- eine echte SteamID64 zum Testen eintragen

# Aktuellen Wert holen
resp = session.post(
    config.AMP_URL + "/API/Core/GetConfig",
    json={"SESSIONID": session_id, "node": "Meta.GenericModule.AdminUsers"},
)
print("GetConfig Status:", resp.status_code)
print("GetConfig Antwort:", resp.json())

current = resp.json()
if isinstance(current, dict) and "CurrentValue" in current:
    current_list = current["CurrentValue"]
else:
    current_list = current if isinstance(current, list) else []

print("\nAktuelle Liste:", current_list)

if TEST_STEAM_ID not in current_list:
    new_list = current_list + [TEST_STEAM_ID]

    set_resp = session.post(
        config.AMP_URL + "/API/Core/SetConfig",
        json={"SESSIONID": session_id, "node": "Meta.GenericModule.AdminUsers", "value": jsonlib.dumps(new_list)},
    )
    print("\nSetConfig Status:", set_resp.status_code)
    print("SetConfig Antwort:", set_resp.json())

    # Kontrolle: nochmal auslesen
    check_resp = session.post(
        config.AMP_URL + "/API/Core/GetConfig",
        json={"SESSIONID": session_id, "node": "Meta.GenericModule.AdminUsers"},
    )
    print("\nKontroll-Auslesung:", check_resp.json())
else:
    print(f"\n{TEST_STEAM_ID} ist schon in der Liste, kein Test-Set noetig.")
