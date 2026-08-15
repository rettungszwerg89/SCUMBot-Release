# Rechnet SCUM-Log-Koordinaten (aus den Server-Logs) in Pixelpositionen auf
# deinem Kartenbild um und erzeugt einen zugeschnittenen Ausschnitt mit
# eingezeichnetem Marker an der Todesposition.
#
# Kalibriert anhand von 5 echten Ingame-Positionen mit exakt bekannten
# Log-Koordinaten, abgeglichen gegen die Pixelposition auf der Karte
# (max. 3px Abweichung bei 1439px Kartenbreite).

from PIL import Image, ImageDraw
import config

# Log-Koordinate -> Pixel auf config.KILL_MAP_IMAGE_PATH (Karte muss 1439x1438px sein!)
_COEF_X = (-0.0009451413, -0.0000014193, 586.2351)
_COEF_Y = (0.0000003763, -0.0009452848, 583.8711)


def log_to_pixel(log_x: float, log_y: float) -> tuple[float, float]:
    px = _COEF_X[0] * log_x + _COEF_X[1] * log_y + _COEF_X[2]
    py = _COEF_Y[0] * log_x + _COEF_Y[1] * log_y + _COEF_Y[2]
    return px, py


def pixel_to_log(px: float, py: float) -> tuple[float, float]:
    """Umkehrung von log_to_pixel - fuer Klicks auf die Live-Karte, die in
    SCUM-Weltkoordinaten uebersetzt werden muessen (z.B. fuers Teleportieren)."""
    a, b, c = _COEF_X
    d, e, f = _COEF_Y
    det = a * e - b * d
    log_x = (e * (px - c) - b * (py - f)) / det
    log_y = (a * (py - f) - d * (px - c)) / det
    return log_x, log_y


def create_death_marker_image(log_x: float, log_y: float, out_path: str) -> str | None:
    """Erstellt einen zugeschnittenen Kartenausschnitt mit rotem Marker an der
    Todesposition und speichert ihn unter out_path. Gibt None zurueck, wenn
    die Kartendatei nicht gefunden wird."""
    try:
        img = Image.open(config.KILL_MAP_IMAGE_PATH).convert("RGB")
    except (FileNotFoundError, OSError):
        return None

    px, py = log_to_pixel(log_x, log_y)
    half = config.KILL_MAP_CROP_SIZE // 2
    left = max(0, int(px - half))
    top = max(0, int(py - half))
    right = min(img.width, int(px + half))
    bottom = min(img.height, int(py + half))

    crop = img.crop((left, top, right, bottom))

    # Hochskalieren fuer bessere Lesbarkeit in Discord
    scale = 2
    crop = crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS)

    draw = ImageDraw.Draw(crop)
    mx, my = (px - left) * scale, (py - top) * scale
    r = 12
    draw.ellipse([mx - r, my - r, mx + r, my + r], outline=(255, 40, 40), width=4)
    draw.line([mx - r - 8, my, mx + r + 8, my], fill=(255, 40, 40), width=3)
    draw.line([mx, my - r - 8, mx, my + r + 8], fill=(255, 40, 40), width=3)

    crop.save(out_path)
    return out_path


def _heat_color(intensity: float) -> tuple[int, int, int]:
    """Einfache Blau -> Gruen -> Gelb -> Rot Farbskala fuer die Heatmap (0..1)."""
    if intensity < 0.33:
        t = intensity / 0.33
        return (0, int(255 * t), 255)
    elif intensity < 0.66:
        t = (intensity - 0.33) / 0.33
        return (int(255 * t), 255, int(255 * (1 - t)))
    else:
        t = min(1.0, (intensity - 0.66) / 0.34)
        return (255, int(255 * (1 - t)), 0)


def create_heatmap_image(points: list[tuple[float, float]], out_path: str, cell_size: int = 10) -> str | None:
    """Erzeugt eine Heatmap-Ueberlagerung ueber der vollen Kartengrafik anhand
    einer Liste von (log_x, log_y)-Koordinaten (z.B. aus data/kill_heatmap_points.json).
    Reine PIL-Loesung (Zaehl-Raster + Farbverlauf), keine neue Dependency."""
    try:
        base = Image.open(config.KILL_MAP_IMAGE_PATH).convert("RGB")
    except (FileNotFoundError, OSError):
        return None
    if not points:
        return None

    width, height = base.size
    cols = width // cell_size + 1
    rows = height // cell_size + 1
    grid = [[0] * cols for _ in range(rows)]
    max_count = 0

    for log_x, log_y in points:
        px, py = log_to_pixel(log_x, log_y)
        if not (0 <= px < width and 0 <= py < height):
            continue
        col, row = int(px // cell_size), int(py // cell_size)
        grid[row][col] += 1
        if grid[row][col] > max_count:
            max_count = grid[row][col]

    if max_count == 0:
        return None

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for row in range(rows):
        for col in range(cols):
            count = grid[row][col]
            if count == 0:
                continue
            intensity = count / max_count
            color = _heat_color(intensity)
            alpha = int(60 + intensity * 150)
            x0, y0 = col * cell_size, row * cell_size
            draw.rectangle([x0, y0, x0 + cell_size, y0 + cell_size], fill=(*color, alpha))

    result = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    result.save(out_path)
    return out_path
