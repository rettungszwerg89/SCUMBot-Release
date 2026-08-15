@echo off
REM Startet den Discord-Bot UND die Webseite gleichzeitig, je in einem
REM eigenen Fenster (damit du beide Konsolen-Ausgaben separat siehst).
REM Einfach diese Datei doppelklicken.

cd /d "%~dp0"

echo Starte SCUM Bot...
start "SCUM Bot" cmd /k python bot.py

timeout /t 2 /nobreak >nul

echo Starte SCUM Webseite...
start "SCUM Webseite" cmd /k python webapp\app.py

echo.
echo Beide Fenster wurden geoeffnet. Dieses Fenster kannst du schliessen.
timeout /t 5
