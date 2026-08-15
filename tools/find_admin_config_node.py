# Testskript: Findet den internen AMP-Node-Namen fuer das "Admin Users"-Feld,
# damit wir es per API setzen koennen (wie beim manuellen Bearbeiten im Webinterface).

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

resp = session.post(config.AMP_URL + "/API/Core/GetSettingsSpec", json=payload, timeout=15)
data = resp.json()

print("Alle Kategorien:", list(data.keys()))

for category, entries in data.items():
    for entry in entries:
        name = entry.get("Name", "")
        node = entry.get("Node", "")
        if "admin" in name.lower() or "admin" in node.lower():
            print(f"\n[{category}] Name='{name}' Node='{node}'")
            print(f"  CurrentValue: {entry.get('CurrentValue')!r}")
            print(f"  ValType: {entry.get('ValType')}")
            print(f"  ReadOnly: {entry.get('ReadOnly')}")
            print(f"  RequiresRestart: {entry.get('RequiresRestart')}")
