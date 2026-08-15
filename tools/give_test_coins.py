# Einmal-Skript: schreibt Test-Coins auf ein Discord-Konto gut.
# Nur zum Testen gedacht - im Projektordner ausfuehren.

from econ import economy

DISCORD_ID = 0   # <-- deine Discord-User-ID eintragen (Rechtsklick auf deinen Namen -> ID kopieren)
AMOUNT = 1000     # genug fuer alle 12 Ziele a 750 Coins

new_balance = economy.add_coins(DISCORD_ID, AMOUNT, reason="Test-Gutschrift")
print(f"Neuer Kontostand: {new_balance} Coins")
