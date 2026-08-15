# SCUMBot - Setup Guide

*(Deutsche Anleitung: [README_ANLEITUNG.md](README_ANLEITUNG.md))*

Discord bot + website for your own SCUM server: server status, shop, economy,
taxi, leaderboard, killfeed, quests, dead drops, world events, live map and
more. Everything runs on **your own** server/PC - nothing is sent to any
third party.

**AMP (CubeCoders) is NOT required.** Every gameplay action (purchases, taxi,
admin console, granting items/money, ...) runs through the included Lua mod.
Only the plain "server online + player count" display needs either AMP (if
you already use it) or a generic Steam server query (default, see below) -
without either, the site just shows "unknown status", nothing crashes.

## 1. Requirements

- **Python 3.11+** (https://www.python.org/downloads/, check "Add Python to
  PATH" during install)
- Your own SCUM dedicated server with **UE4SS** installed (for the Lua mod)
- A Discord server where you have admin rights

## 2. Create a Discord bot

1. https://discord.com/developers/applications → "New Application"
2. **Bot** tab → "Reset Token" → copy the token (you'll need it in the setup
   wizard in a moment)
3. Under bot permissions/intents: enable "Message Content Intent"
4. **OAuth2** tab → note the Client ID and Client Secret (for Discord login on
   the website, optional but recommended)
5. **OAuth2 → URL Generator**: scopes `bot` + `applications.commands`,
   permissions at least "Send Messages", "Manage Messages", "Embed Links",
   "Attach Files" → open the link and invite the bot to your server

## 3. Install the Lua mod on your SCUM server

1. Copy the `scum-mod\ScumBot` folder from this package entirely into
   `<your SCUM server>\SCUM\Binaries\Win64\ue4ss\Mods\ScumBot`
2. Add the line `ScumBot : 1` to `ue4ss\Mods\mods.txt` (**never** create an
   `enabled.txt` - it silently overrides `mods.txt`)
3. In `ue4ss\UE4SS-settings.ini`, make sure `HookProcessInternal=1` and
   `HookProcessLocalScriptFunction=1` are set
4. Restart the server - the server log should show "ScumBot ist geladen"

Note down the full path to this mod folder - you'll need it in the setup
wizard in a moment ("SCUM_MOD_DIR" field).

## 4. Install and configure the bot

```bash
pip install -r requirements.txt
python webapp\app.py
```

Then open in your browser: **http://localhost:5000/setup**

There you enter (each field is explained on the page itself):
- Discord bot token, admin password (required)
- Discord channel IDs for the features you want to use (0 = off)
- Paths to your SCUM server (SCUM.db, logs, mod folder, ServerSettings.ini,
  AdminUsers.ini)
- Optional: AMP credentials if you have them, or your server IP/query port
  for status display without AMP

After saving: exit the wizard, then restart both processes (e.g. double-click
`start_all.bat`, or individually `python bot.py` and `python webapp\app.py`).

## 5. What works with / without AMP

| Feature | Without AMP | With AMP |
|---|---|---|
| Shop, daily package, lottery, taxi, quests, dead drops | ✅ | ✅ |
| Admin console / live map (teleport, give item/money, run commands) | ✅ | ✅ |
| Mech/sentry schedule | ✅ | ✅ |
| Server status + player count | ✅ (Steam query) | ✅ (AMP) |
| Show AMP's own restart schedule | – | ✅ (cosmetic only, the bot has its own system) |

For the Steam query you only need your server's IP and its **Steam query
port** (not the game port - check your server config or ask your host).

## 6. After setup

- The admin area (`/admin`, password from setup) manages shop items, quests,
  dead drops, world events, daily package, etc. - no code changes needed.
- `/setup` stays reachable afterwards but requires the admin login (so no one
  else can overwrite your installation).
- Game balance (prices, cooldowns, coin rates, taxi destinations) still lives
  in `config.py` - commented, edit directly if you want to change it.
