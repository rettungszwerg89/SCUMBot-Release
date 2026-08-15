# Generische Steam-A2S_INFO-Abfrage (UDP) fuer den Server-Status OHNE AMP.
# Standardprotokoll aller Steamworks-Dedicated-Server (nicht SCUM-spezifisch),
# daher funktioniert das bei praktisch jedem Hoster/Panel - keine zusaetzliche
# Abhaengigkeit noetig, nur das Python-Standardmodul 'socket'.

import socket

_A2S_INFO_REQUEST = b"\xFF\xFF\xFF\xFFTSource Engine Query\x00"


def _read_cstring(buf: bytes, offset: int) -> tuple[str, int]:
    end = buf.index(b"\x00", offset)
    return buf[offset:end].decode("utf-8", errors="replace"), end + 1


def query(host: str, port: int, timeout: float = 3.0) -> dict | None:
    """Fragt Online-Status + Spieleranzahl per Steam-A2S-Protokoll ab.
    Gibt None zurueck, wenn der Server nicht (rechtzeitig) antwortet - z.B.
    falscher Query-Port oder Query deaktiviert - statt eine Exception zu
    werfen, damit der Aufrufer sauber auf 'Status unbekannt' zurueckfallen kann."""
    if not host or not port:
        return None

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(_A2S_INFO_REQUEST, (host, port))
        data, _ = sock.recvfrom(4096)

        # Manche Server antworten zuerst mit einem Challenge-Paket (0x41);
        # dann muss dieselbe Anfrage mit dem Challenge-Wert wiederholt werden.
        if len(data) > 4 and data[4] == 0x41:
            challenge = data[5:9]
            sock.sendto(_A2S_INFO_REQUEST + challenge, (host, port))
            data, _ = sock.recvfrom(4096)

        if len(data) < 6 or data[4] != 0x49:
            return None

        offset = 6  # Header (4) + Type (1) + Protocol-Version (1)
        name, offset = _read_cstring(data, offset)
        _map_name, offset = _read_cstring(data, offset)
        _folder, offset = _read_cstring(data, offset)
        _game, offset = _read_cstring(data, offset)
        offset += 2  # App-ID (2 Bytes, wird nicht gebraucht)
        players = data[offset]
        max_players = data[offset + 1]

        return {"online": True, "players": players, "max_players": max_players, "name": name}
    except (OSError, IndexError, ValueError):
        return None
    finally:
        sock.close()
