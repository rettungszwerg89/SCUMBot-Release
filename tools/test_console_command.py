# Schnelltest: Prueft, ob sich Konsolenbefehle ueberhaupt per AMP-API einschleusen
# lassen (Core/SendConsoleMessage), bevor wir das Taxi-System darauf aufbauen.

import config
from services.amp_client import AMPClient

amp = AMPClient(config.AMP_URL, config.AMP_USER, config.AMP_PASSWORD)

print("Sende Testbefehl: #Announce Konsolentest vom Bot")
result = amp.send_console_message("#Announce Konsolentest vom Bot")
print("Antwort der API:")
print(result)
print()
print("--> Schau jetzt INGAME nach, ob eine rote Announce-Meldung erscheint.")
