# SCUMBot - Anleitung zur Einrichtung

*(English guide: [README.md](README.md))*

Kostenlos und frei für alle. Wenn dir das Zeit gespart hat, kannst du dem
Ersteller gerne einen Kaffee spendieren: [paypal.me/rettungszwerg](https://www.paypal.com/paypalme/rettungszwerg) - völlig freiwillig.

Discord-Bot + Webseite für einen eigenen SCUM-Server: Serverstatus, Shop, Wirtschaft,
Taxi, Leaderboard, Killfeed, Quests, Tote Briefkästen, Weltereignisse, Live-Karte
und mehr. Alles läuft auf **deinem eigenen** Server/PC - nirgendwo werden Daten an
Dritte geschickt.

**AMP (CubeCoders) wird NICHT gebraucht.** Alle Spielaktionen (Käufe, Taxi,
Admin-Konsole, Item/Geld vergeben, ...) laufen über den mitgelieferten Lua-Mod.
Nur die reine "Server online + Spieleranzahl"-Anzeige braucht entweder AMP
(falls du es eh nutzt) oder eine generische Steam-Server-Abfrage (Standard,
siehe unten) - ohne beides zeigt die Seite einfach "Status unbekannt" an, nichts
stürzt ab.

## 1. Voraussetzungen

- **Python 3.11+** (https://www.python.org/downloads/, bei der Installation "Add
  Python to PATH" anhaken)
- Ein eigener SCUM-Dedicated-Server mit **UE4SS** installiert (für den Lua-Mod)
- Ein Discord-Server, auf dem du Admin-Rechte hast

## 2. Discord-Bot anlegen

1. https://discord.com/developers/applications → "New Application"
2. Reiter **Bot** → "Reset Token" → Token kopieren (brauchst du gleich im
   Setup-Assistenten)
3. Bei den Bot-Berechtigungen: "Message Content Intent" aktivieren
4. Reiter **OAuth2** → Client-ID und Client-Secret notieren (für den Website-Login
   mit Discord, optional aber empfohlen)
5. Reiter **OAuth2 → URL Generator**: Scopes `bot` + `applications.commands`,
   Berechtigungen mindestens "Send Messages", "Manage Messages", "Embed Links",
   "Attach Files" → Link öffnen und Bot auf deinen Server einladen

## 3. Lua-Mod auf dem SCUM-Server installieren

1. Ordner `scum-mod\ScumBot` aus diesem Paket komplett nach
   `<dein SCUM-Server>\SCUM\Binaries\Win64\ue4ss\Mods\ScumBot` kopieren
2. In `ue4ss\Mods\mods.txt` die Zeile `ScumBot : 1` hinzufügen (**keine**
   `enabled.txt` anlegen, die überschreibt `mods.txt` stillschweigend)
3. In `ue4ss\UE4SS-settings.ini` sicherstellen, dass `HookProcessInternal=1`
   und `HookProcessLocalScriptFunction=1` gesetzt sind
4. Server neu starten - im Server-Log sollte "ScumBot ist geladen" erscheinen

Merk dir den vollen Pfad zu diesem Mod-Ordner, den brauchst du gleich im
Setup-Assistenten (Feld "SCUM_MOD_DIR").

## 4. Bot installieren und einrichten

```bash
pip install -r requirements.txt
python webapp\app.py
```

Danach im Browser öffnen: **http://localhost:5000/setup**

Dort trägst du ein (Erklärung zu jedem Feld direkt auf der Seite):
- Discord-Bot-Token, Admin-Passwort (Pflicht)
- Discord-Channel-IDs für die Features, die du nutzen willst (0 = aus)
- Pfade zu deinem SCUM-Server (SCUM.db, Logs, Mod-Ordner, ServerSettings.ini,
  AdminUsers.ini)
- Optional: AMP-Zugangsdaten, falls vorhanden, oder Server-IP/Query-Port für die
  Status-Anzeige ohne AMP

Nach dem Speichern: Assistent beenden, dann beides neu starten (z.B. per
Doppelklick auf `start_all.bat`, oder einzeln `python bot.py` und
`python webapp\app.py`).

## 5. Was mit / ohne AMP funktioniert

| Funktion | Ohne AMP | Mit AMP |
|---|---|---|
| Shop, Tagespaket, Lotterie, Taxi, Quests, Tote Briefkästen | ✅ | ✅ |
| Admin-Konsole / Live-Karte (Teleport, Item/Geld geben, Befehle) | ✅ | ✅ |
| Mech/Sentry-Zeitplan | ✅ | ✅ |
| Serverstatus + Spieleranzahl | ✅ (Steam-Query) | ✅ (AMP) |
| Neustart-Zeitplan aus AMP anzeigen | – | ✅ (kosmetisch, Bot hat eigenes System) |

Für die Steam-Query brauchst du nur die Server-IP und den **Steam-Query-Port**
deines Servers (nicht den Spielport - steht in deiner Server-Config bzw. bei
deinem Hoster).

## 6. Danach

- Der Admin-Bereich (`/admin`, Passwort aus dem Setup) verwaltet Shop-Artikel,
  Quests, Tote Briefkästen, Weltereignisse, Tagespaket usw. - alles ohne
  Code-Änderungen.
- `/setup` bleibt danach erreichbar, verlangt aber den Admin-Login (verhindert,
  dass jemand sonst deine Installation überschreibt).
- Spielbalance (Preise, Cooldowns, Coin-Raten, Taxi-Ziele) steht weiterhin in
  `config.py` - dort mit Kommentaren, bei Bedarf direkt anpassen.
