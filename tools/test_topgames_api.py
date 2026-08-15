import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import requests
import config

if config.TOPGAMES_TOKEN.startswith("TODO"):
    print("FEHLER: Trag zuerst TOPGAMES_TOKEN in secrets.ini ein!")
    sys.exit(1)

print("Rufe ab:", config.TOPGAMES_RANKING_URL.replace(config.TOPGAMES_TOKEN, "***TOKEN***"))
resp = requests.get(config.TOPGAMES_RANKING_URL, timeout=15)
print("Status:", resp.status_code)
print("Rohdaten:")
print(resp.text[:3000])
