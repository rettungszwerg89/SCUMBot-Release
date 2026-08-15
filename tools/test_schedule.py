# Testskript: Prueft, ob und wie AMP ueber die API Zeitplan-/Neustart-Infos preisgibt.
# Nutzt dieselben Zugangsdaten wie config.py.

import requests
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
payload = {"SESSIONID": session_id}

for endpoint in ["/Core/GetScheduleData", "/Core/GetUpdates"]:
    print(f"\n--- {endpoint} ---")
    try:
        resp = session.post(config.AMP_URL + "/API" + endpoint, json=payload, timeout=10)
        print(resp.status_code)
        print(resp.json())
    except Exception as e:
        print("Fehler:", e)
