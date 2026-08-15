# Testskript: Verbindung zur SCUM-Instanz in AMP testen (direkt per HTTP)
# Nutzt dieselben Zugangsdaten wie config.py/secrets.ini.

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import requests
import config

AMP_URL = config.AMP_URL
AMP_USER = config.AMP_USER
AMP_PASSWORD = config.AMP_PASSWORD


def main():
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json",
        "Content-Type": "application/json",
    })

    login_payload = {
        "username": AMP_USER,
        "password": AMP_PASSWORD,
        "token": "",
        "rememberMe": False,
    }

    login_resp = session.post(AMP_URL + "/API/Core/Login", json=login_payload)
    login_resp.raise_for_status()
    login_data = login_resp.json()

    if not login_data.get("success"):
        print("LOGIN FEHLGESCHLAGEN:")
        print(login_data)
        return

    print("LOGIN ERFOLGREICH (SCUM-Instanz)!")
    session_id = login_data["sessionID"]

    status_resp = session.post(
        AMP_URL + "/API/Core/GetStatus",
        json={"SESSIONID": session_id},
    )
    status_resp.raise_for_status()
    status_data = status_resp.json()

    print("SCUM SERVER STATUS (Rohdaten):")
    print(status_data)

    # Bonus: Userlist abfragen (falls bei SCUM verfuegbar)
    users_resp = session.post(
        AMP_URL + "/API/Core/GetUserList",
        json={"SESSIONID": session_id},
    )
    if users_resp.ok:
        print("\nUSERLIST (Rohdaten):")
        print(users_resp.json())


if __name__ == "__main__":
    main()
