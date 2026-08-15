# Zeigt, welchen AMP-Benutzernamen config.py (und damit auch bot.py) tatsaechlich
# aus secrets.ini geladen hat. Zeigt das Passwort NICHT im Klartext, nur ob es
# gesetzt/leer/noch der Platzhalter ist - zum Vergleich mit tools/amp_test.py.

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config

print("AMP_URL:", config.AMP_URL)
print("AMP_USER (aus secrets.ini):", repr(config.AMP_USER))

pw = config.AMP_PASSWORD
if pw == "TODO_AMP_PASSWORT":
    print("AMP_PASSWORD: NICHT GESETZT (steht noch auf dem Platzhalter!)")
elif not pw:
    print("AMP_PASSWORD: LEER")
else:
    print(f"AMP_PASSWORD: gesetzt, {len(pw)} Zeichen lang, beginnt mit '{pw[0]}' und endet mit '{pw[-1]}'")
