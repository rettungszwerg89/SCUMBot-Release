# Verwaltet die Lotterie: Lose kaufen (Coins -> Pot), automatische Ziehung
# nach festem Intervall, Gewinnauszahlung ueber economy.add_coins (macht der
# Aufrufer in bot.py, hier wird nur der Gewinner ermittelt).

import json
import os
import random
from datetime import datetime, timedelta
import config


def _default_state() -> dict:
    return {
        "pot": 0,
        "tickets": {},
        "next_draw_at": (datetime.now() + timedelta(hours=config.LOTTERY_DRAW_INTERVAL_HOURS)).isoformat(),
        "history": [],
    }


def _load() -> dict:
    if not os.path.exists(config.LOTTERY_FILE):
        return _default_state()
    with open(config.LOTTERY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "next_draw_at" not in data:
        data["next_draw_at"] = _default_state()["next_draw_at"]
    return data


def _save(data: dict) -> None:
    with open(config.LOTTERY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_status() -> dict:
    return _load()


def add_ticket(discord_id: int) -> dict:
    """Verbucht ein gekauftes Los (der Coins-Abzug passiert beim Aufrufer, hier
    wird nur Los + Pot verbucht). Gibt den neuen Status zurueck."""
    data = _load()
    key = str(discord_id)
    data["tickets"][key] = data["tickets"].get(key, 0) + 1
    data["pot"] += config.LOTTERY_TICKET_PRICE
    _save(data)
    return data


def is_draw_due() -> bool:
    return datetime.now() >= datetime.fromisoformat(_load()["next_draw_at"])


def draw_winner() -> dict:
    """Fuehrt eine Ziehung durch. Selbst wenn Lose verkauft wurden, gewinnt nicht
    garantiert jemand - mit config.LOTTERY_WIN_CHANCE wird zuerst ausgewuerfelt,
    ob es ueberhaupt einen Gewinner gibt. Ohne Gewinner bleibt der Pot stehen
    und waechst in der naechsten Runde weiter (Jackpot-Rollover); die Lose
    werden trotzdem zurueckgesetzt (neue Runde, neue Lose).

    Gibt immer ein Dict zurueck:
      {"won": bool, "total_tickets": int, "winner_discord_id": int|None, "amount": int}
    'amount' ist bei einem Gewinner die Auszahlung, sonst der (weiterhin im
    Pot verbleibende) aktuelle Potstand. Die Auszahlung der Coins macht der
    Aufrufer anhand des Rueckgabewerts."""
    data = _load()
    tickets = data["tickets"]
    total_tickets = sum(tickets.values())
    pot = data["pot"]

    won = total_tickets > 0 and random.random() < config.LOTTERY_WIN_CHANCE
    result = {"won": won, "total_tickets": total_tickets, "winner_discord_id": None, "amount": pot}

    if won:
        entries = [discord_id for discord_id, count in tickets.items() for _ in range(count)]
        winner_id = random.choice(entries)
        result["winner_discord_id"] = int(winner_id)
        data["history"] = (data.get("history", []) + [
            {"winner_discord_id": int(winner_id), "amount": pot, "total_tickets": total_tickets,
             "drawn_at": datetime.now().isoformat()}
        ])[-20:]
        data["pot"] = 0
    # ohne Gewinner bleibt data["pot"] unveraendert stehen (Rollover)

    data["tickets"] = {}
    data["next_draw_at"] = (datetime.now() + timedelta(hours=config.LOTTERY_DRAW_INTERVAL_HOURS)).isoformat()
    _save(data)
    return result
