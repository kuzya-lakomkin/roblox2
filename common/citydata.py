"""Данные карты — общие для клиента (отрисовка) и сервера (коллизии).

Тактическая арена backrooms на ДВУХ уровнях, 4-кратная симметрия — «крепость-кольцо»:
в центре открытая боевая яма (спавн + витрина SWAGA), вокруг неё низкое стеновое
КОЛЬЦО с 4 проёмами (N/S/E/W). Верхний уровень — сплошная дорожка-кольцо ПОВЕРХ этих
стен (высокая позиция, обзор всей ямы) с широкими угловыми бастионами. Поскольку
платформы лежат ровно на стенах, тараканы забираются наверх ПО СТЕНЕ (а не по воздуху),
а игрок — прыжковыми падами в проёмах. Снаружи кольца — коридор с колоннами-укрытиями
и северная арена босса.

Чистые данные, без Panda3D, чтобы импортировались и на сервере.
"""

ARENA = 56.0

# фиксированная точка спавна главного босса (открытая северная зона, вне кольца)
BOSS_SPAWN = (0.0, 46.0)

WALL_HEIGHT = 11.0       # высота стен (верх кольца); платформы 2-го уровня лежат на них


def _mirror4(blocks):
    """Размножить блоки одного квадранта (+x,+y, вне осей) на 4 симметрично."""
    out = []
    for cx, cy, w, d in blocks:
        for sx in (1, -1):
            for sy in (1, -1):
                out.append((cx * sx, cy * sy, w, d))
    return out


# --- Стены нижнего уровня ---
# Кольцо вокруг ямы (R=30) с проёмами по центрам сторон (ширина проёма ±8):
_RING = [
    (-19, 30, 22, 3), (19, 30, 22, 3),      # север (с дверным проёмом по центру)
    (-19, -30, 22, 3), (19, -30, 22, 3),     # юг
    (30, 19, 3, 22), (30, -19, 3, 22),       # восток
    (-30, 19, 3, 22), (-30, -19, 3, 22),     # запад
    (30, 30, 3, 3), (-30, 30, 3, 3),         # угловые стойки кольца
    (30, -30, 3, 3), (-30, -30, 3, 3),
]
# Колонны-укрытия снаружи кольца (4 угла) + по бокам (север открыт под арену босса):
_OUTER = _mirror4([(44, 44, 7, 7)]) + [
    (46, 0, 4, 16), (-46, 0, 4, 16), (0, -46, 16, 4),
]
# Невысокие колонны-укрытия в самой яме (прикрывают от выстрелов неоновых муравьёв):
_PLAZA = _mirror4([(15, 15, 5, 5)])

WALL_BLOCKS = _RING + _OUTER + _PLAZA


def building_specs():
    """Список стен-блоков: (cx, cy, w, d)."""
    return list(WALL_BLOCKS)


def building_rects(pad=0.0):
    """Прямоугольники стен в виде (min_x, min_y, max_x, max_y)."""
    rects = []
    for cx, cy, w, d in WALL_BLOCKS:
        hw, hd = w / 2 + pad, d / 2 + pad
        rects.append((cx - hw, cy - hd, cx + hw, cy + hd))
    return rects


def in_any_building(x, y, rects):
    for minx, miny, maxx, maxy in rects:
        if minx <= x <= maxx and miny <= y <= maxy:
            return True
    return False


def resolve_collision(x, y, rects, radius=0.6, z=0.0):
    """Вытолкнуть точку (x,y) с радиусом наружу из ближайшей стены.

    z задаёт высоту: стоя ВЫШЕ стен (на верхнем кольце-дорожке) игрок не толкается —
    иначе по платформам над стенами было бы не пройти.
    """
    if z >= WALL_HEIGHT - 0.1:
        return x, y
    for minx, miny, maxx, maxy in rects:
        if (minx - radius) <= x <= (maxx + radius) and (miny - radius) <= y <= (maxy + radius):
            push_left = x - (minx - radius)
            push_right = (maxx + radius) - x
            push_down = y - (miny - radius)
            push_up = (maxy + radius) - y
            m = min(push_left, push_right, push_down, push_up)
            if m == push_left:
                x = minx - radius
            elif m == push_right:
                x = maxx + radius
            elif m == push_down:
                y = miny - radius
            else:
                y = maxy + radius
    return x, y


def near_wall(x, y, rects):
    """True, если точка (x,y) вплотную к стене (rects — building_rects с запасом)."""
    return in_any_building(x, y, rects)


def _seg_aabb(x0, y0, x1, y1, minx, miny, maxx, maxy):
    """Пересекает ли отрезок (x0,y0)-(x1,y1) прямоугольник (Liang-Barsky)."""
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - minx), (dx, maxx - x0), (-dy, y0 - miny), (dy, maxy - y0)):
        if p == 0:
            if q < 0:
                return False          # параллельно и снаружи плиты
        else:
            t = q / p
            if p < 0:
                if t > t1:
                    return False
                if t > t0:
                    t0 = t
            else:
                if t < t0:
                    return False
                if t < t1:
                    t1 = t
    return t0 <= t1


def line_blocked(x0, y0, x1, y1, rects):
    """True, если отрезок взгляда пересекает хотя бы одну стену (нет прямой видимости).

    Мобы НЕ учитываются — загораживают только стены/столбы (rects)."""
    for (minx, miny, maxx, maxy) in rects:
        if _seg_aabb(x0, y0, x1, y1, minx, miny, maxx, maxy):
            return True
    return False


# --- Места для белых пластиковых стаканов в 4 углах карты (ритуал BLACK KING) ---
CUP_SPOTS = [(38.0, 38.0), (-38.0, 38.0), (38.0, -38.0), (-38.0, -38.0)]
CUP_SPOT_RADIUS = 3.0        # на каком расстоянии можно поставить стакан на пьедестал


# --- Второй уровень по высоте (дорожка-кольцо поверх стен) и прыжковые пады ---
LEVEL2_Z = 12.0

# Дорожка-кольцо лежит ровно над кольцевыми стенами + широкие угловые бастионы:
PLATFORMS = [
    (0, 30, 64, 7),        # северная дорожка
    (0, -30, 64, 7),       # южная
    (30, 0, 7, 64),        # восточная
    (-30, 0, 7, 64),       # западная
    (30, 30, 12, 12),      # угловые бастионы (широкие — вынос/обзор)
    (-30, 30, 12, 12),
    (30, -30, 12, 12),
    (-30, -30, 12, 12),
]


def platform_specs():
    """(cx, cy, w, d, top_z) для каждой платформы 2-го уровня."""
    return [(cx, cy, w, d, LEVEL2_Z) for (cx, cy, w, d) in PLATFORMS]


def platform_top_at(x, y):
    """Верх платформы, под которой/над которой стоит точка (x,y); 0 если её нет."""
    best = 0.0
    for cx, cy, w, d, top in platform_specs():
        if abs(x - cx) <= w / 2 and abs(y - cy) <= d / 2 and top > best:
            best = top
    return best


def support_z(x, y, z_feet, tol=0.5):
    """Высота опоры под ногами (x, y, z_feet): верх платформы либо 0 (пол).

    Платформа — опора, только если ноги уже на её уровне или выше (с допуском tol),
    чтобы при прыжке можно было пролететь сквозь неё снизу.
    """
    best = 0.0
    for cx, cy, w, d, top in platform_specs():
        if abs(x - cx) <= w / 2 and abs(y - cy) <= d / 2:
            if z_feet >= top - tol and top > best:
                best = top
    return best


# Прыжковые пады — в дверных проёмах кольца, под дорожкой (запрыгнуть на верхнее кольцо):
JUMP_PADS = [
    (0, -30),    # южный проём
    (0, 30),     # северный проём
    (30, 0),     # восточный проём
    (-30, 0),    # западный проём
]
JUMP_PAD_RADIUS = 2.0


def on_jump_pad(x, y):
    for cx, cy in JUMP_PADS:
        if (x - cx) ** 2 + (y - cy) ** 2 <= JUMP_PAD_RADIUS ** 2:
            return True
    return False


# --- Точки появления ЩЕЛЕЙ на внутренних гранях кольцевых стен ---

def slit_spawn_points():
    """Точки на внутренних гранях кольцевых стен (лицом в центр арены).

    Возвращает [(x, y, nx, ny), ...]: позиция чуть перед поверхностью стены и
    нормаль (единичная), смотрящая ВНУТРЬ арены (к центру). Высоту (z) задаёт
    сервер — на уровне игрока (половина его роста). Угловые стойки пропускаются.
    """
    pts = []
    margin = 4.0     # отступ от краёв стены, чтобы щель не вылезала за угол
    eps = 0.8        # вынос перед поверхностью стены, чтобы щель выступала и была видна
    for cx, cy, w, d in _RING:
        if abs(w - d) < 0.5:
            continue  # квадратные угловые стойки — мало места, пропускаем
        if w > d:     # горизонтальная стена (север/юг): нормаль вдоль -y/+y
            ny = -1.0 if cy > 0 else 1.0
            face_y = cy + ny * (d / 2.0 + eps)
            lo, hi = cx - w / 2 + margin, cx + w / 2 - margin
            for t in (0.25, 0.5, 0.75):
                pts.append((round(lo + (hi - lo) * t, 2), round(face_y, 2), 0.0, ny))
        else:         # вертикальная стена (восток/запад): нормаль вдоль -x/+x
            nx = -1.0 if cx > 0 else 1.0
            face_x = cx + nx * (w / 2.0 + eps)
            lo, hi = cy - d / 2 + margin, cy + d / 2 - margin
            for t in (0.25, 0.5, 0.75):
                pts.append((round(face_x, 2), round(lo + (hi - lo) * t, 2), nx, 0.0))
    return pts
