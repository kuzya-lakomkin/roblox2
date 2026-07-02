"""Файлы карт (.json): загрузка, валидация, сохранение, применение к игре.

Формат (version=1) — плоский JSON без Panda3D, редактируется tools/map_editor:
{
  "version": 1, "name": "Моя карта",
  "size": 56.0,          # полукарта: мир = квадрат [-size, size]
  "wall_height": 11.0,   # высота ВСЕХ стен (коллизии единые)
  "level2_z": 12.0,      # базовая высота 2-го уровня (для подсказок редактора)
  "spawn": [0, -15],     # центр зоны спавна игроков
  "respawn": [0, 6],     # точка респавна (нет -> spawn)
  "boss_spawn": [0, 46],
  "floor":   {"texture": "backrooms_floor.jpg", "color": [r,g,b,a], "uv": 0.32},
  "carpets": [{"x","y","w","d","texture","color","uv"}],   # зоны пола (визуал)
  "walls":   [{"x","y","w","d","texture","color","uv","slit":bool}],
  "platforms": [{"x","y","w","d","z","color"}],
  "jump_pads": [[x, y]],
  "cup_spots": [[x, y]],       # пьедесталы ритуала BLACK KING
  "structures": [{"kind": "showcase", "x": 0, "y": 0}],   # встроенные структуры
  "perimeter": true,           # внешние стены по границе мира
  "ceiling_lights": true       # сетка люминесцентных панелей
}

Текстуры — имена файлов в assets/textures/. Цвета — [r,g,b,a] 0..1 или null.
Применение: apply() подменяет данные common/citydata (сервер и клиент читают
карту оттуда); server.world.World пересобирает кэши в __init__.
"""

import json
import os

from common import config as C
from common import citydata

MAP_VERSION = 1
STRUCTURE_KINDS = ("showcase",)

# активная кастомная карта (None = встроенная арена)
ACTIVE_PATH = None
ACTIVE_NAME = None
ACTIVE_DATA = None

_DEFAULT_WORLD_SIZE = C.WORLD_SIZE


class MapError(ValueError):
    pass


def _num(v, name, lo=None, hi=None):
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise MapError(f"{name}: ожидалось число, получено {v!r}")
    v = float(v)
    if lo is not None and v < lo:
        raise MapError(f"{name}: {v} < минимума {lo}")
    if hi is not None and v > hi:
        raise MapError(f"{name}: {v} > максимума {hi}")
    return v


def _pt(v, name):
    if not isinstance(v, (list, tuple)) or len(v) < 2:
        raise MapError(f"{name}: ожидалась точка [x, y]")
    return [_num(v[0], f"{name}.x"), _num(v[1], f"{name}.y")]


def _color(v, name):
    if v is None:
        return None
    if not isinstance(v, (list, tuple)) or len(v) < 3:
        raise MapError(f"{name}: цвет — [r,g,b] или [r,g,b,a] 0..1")
    c = [max(0.0, min(1.0, _num(x, name))) for x in v[:4]]
    if len(c) == 3:
        c.append(1.0)
    return c


def _texture(v, name):
    if v is None:
        return None
    if not isinstance(v, str) or "/" in v or "\\" in v or ".." in v:
        raise MapError(f"{name}: текстура — имя файла в assets/textures/, не путь")
    return v


def _rect(entry, name, need_z=False):
    if not isinstance(entry, dict):
        raise MapError(f"{name}: ожидался объект {{x,y,w,d,...}}")
    out = {
        "x": _num(entry.get("x"), f"{name}.x"),
        "y": _num(entry.get("y"), f"{name}.y"),
        "w": _num(entry.get("w"), f"{name}.w", lo=0.2, hi=500),
        "d": _num(entry.get("d"), f"{name}.d", lo=0.2, hi=500),
    }
    if need_z:
        out["z"] = _num(entry.get("z", citydata.LEVEL2_Z), f"{name}.z", lo=1.0, hi=80)
    if entry.get("texture") is not None:
        out["texture"] = _texture(entry.get("texture"), f"{name}.texture")
    if entry.get("color") is not None:
        out["color"] = _color(entry.get("color"), f"{name}.color")
    if entry.get("uv") is not None:
        out["uv"] = _num(entry.get("uv"), f"{name}.uv", lo=0.01, hi=8.0)
    if entry.get("slit"):
        out["slit"] = True
    return out


def normalize(data):
    """Проверить dict карты и заполнить умолчания. Бросает MapError."""
    if not isinstance(data, dict):
        raise MapError("карта: ожидался JSON-объект")
    if int(data.get("version", MAP_VERSION)) > MAP_VERSION:
        raise MapError(f"карта: версия {data.get('version')} новее поддерживаемой {MAP_VERSION}")
    out = {
        "version": MAP_VERSION,
        "name": str(data.get("name", "без имени"))[:60],
        "size": _num(data.get("size", 56.0), "size", lo=20, hi=240),
        "wall_height": _num(data.get("wall_height", 11.0), "wall_height", lo=3, hi=40),
        "level2_z": _num(data.get("level2_z", 12.0), "level2_z", lo=4, hi=60),
        "spawn": _pt(data.get("spawn", [0, 0]), "spawn"),
        "boss_spawn": _pt(data.get("boss_spawn", [0, 0]), "boss_spawn"),
        "perimeter": bool(data.get("perimeter", True)),
        "ceiling_lights": bool(data.get("ceiling_lights", True)),
    }
    out["respawn"] = (_pt(data["respawn"], "respawn")
                      if data.get("respawn") is not None else None)
    floor = data.get("floor") or {}
    out["floor"] = {
        "texture": _texture(floor.get("texture", "backrooms_floor.jpg"), "floor.texture"),
        "color": _color(floor.get("color"), "floor.color"),
        "uv": _num(floor.get("uv", 0.32), "floor.uv", lo=0.01, hi=8.0),
    }
    out["walls"] = [_rect(w, f"walls[{i}]")
                    for i, w in enumerate(data.get("walls", []))]
    out["carpets"] = [_rect(cz, f"carpets[{i}]")
                      for i, cz in enumerate(data.get("carpets", []))]
    out["platforms"] = [_rect(p, f"platforms[{i}]", need_z=True)
                        for i, p in enumerate(data.get("platforms", []))]
    out["jump_pads"] = [_pt(p, f"jump_pads[{i}]")
                        for i, p in enumerate(data.get("jump_pads", []))]
    out["cup_spots"] = [_pt(p, f"cup_spots[{i}]")
                        for i, p in enumerate(data.get("cup_spots", []))]
    if len(out["walls"]) > 600:
        raise MapError("слишком много стен (макс 600)")
    structures = []
    for i, s in enumerate(data.get("structures", [])):
        kind = (s or {}).get("kind")
        if kind not in STRUCTURE_KINDS:
            raise MapError(f"structures[{i}]: неизвестный kind {kind!r} "
                           f"(доступно: {', '.join(STRUCTURE_KINDS)})")
        p = _pt([s.get("x"), s.get("y")], f"structures[{i}]")
        structures.append({"kind": kind, "x": p[0], "y": p[1]})
    out["structures"] = structures
    # точки должны попадать в границы мира
    lim = out["size"] - 1.0
    for label, (px, py) in (("spawn", out["spawn"]), ("boss_spawn", out["boss_spawn"])):
        if abs(px) > lim or abs(py) > lim:
            raise MapError(f"{label}: точка ({px}, {py}) вне границ карты ±{lim}")
    return out


def load_map(path):
    """Прочитать и нормализовать файл карты."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return normalize(raw)


def save_map(path, data):
    """Сохранить карту (нормализует перед записью)."""
    data = normalize(data)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return data


def apply(data, path=None):
    """Применить карту к игре (citydata + config). data=None -> встроенная арена."""
    global ACTIVE_PATH, ACTIVE_NAME, ACTIVE_DATA
    if data is None:
        citydata.apply_map(None)
        C.WORLD_SIZE = _DEFAULT_WORLD_SIZE
        ACTIVE_PATH = None
        ACTIVE_NAME = None
        ACTIVE_DATA = None
        return
    data = normalize(data)
    citydata.apply_map(data)
    C.WORLD_SIZE = data["size"]
    ACTIVE_PATH = path
    ACTIVE_NAME = data["name"]
    ACTIVE_DATA = data
    return data


def suspend():
    """Временно вернуть встроенную арену (обучение), не сбрасывая активную карту."""
    citydata.apply_map(None)
    C.WORLD_SIZE = _DEFAULT_WORLD_SIZE


def resume():
    """Вернуть активную кастомную карту после suspend(). Без карты — no-op."""
    if ACTIVE_DATA is not None:
        citydata.apply_map(ACTIVE_DATA)
        C.WORLD_SIZE = ACTIVE_DATA["size"]


def load_and_apply(path):
    data = load_map(path)
    apply(data, path=path)
    return data


def default_map_dict():
    """Встроенная арена в формате файла карты — отправная точка для редактора."""
    d = citydata._DEFAULT_STATE
    slit_set = set(d["SLIT_WALLS"])
    return normalize({
        "version": MAP_VERSION,
        "name": "SWAGA арена (копия)",
        "size": d["ARENA"],
        "wall_height": d["WALL_HEIGHT"],
        "level2_z": d["LEVEL2_Z"],
        "spawn": list(d["PLAYER_SPAWN"]),
        "respawn": list(d["PLAYER_RESPAWN"]),
        "boss_spawn": list(d["BOSS_SPAWN"]),
        "walls": [
            {"x": cx, "y": cy, "w": w, "d": dd,
             **({"slit": True} if (cx, cy, w, dd) in slit_set else {})}
            for (cx, cy, w, dd) in d["WALL_BLOCKS"]
        ],
        "platforms": [{"x": cx, "y": cy, "w": w, "d": dd, "z": z}
                      for (cx, cy, w, dd, z) in d["PLATFORMS"]],
        "jump_pads": [list(p) for p in d["JUMP_PADS"]],
        "cup_spots": [list(p) for p in d["CUP_SPOTS"]],
        "structures": [{"kind": "showcase", "x": 0.0, "y": 0.0}],
        "perimeter": True,
        "ceiling_lights": True,
    })


def empty_map_dict(size=56.0):
    """Пустая карта: пол, спавны и ничего больше."""
    return normalize({
        "version": MAP_VERSION,
        "name": "новая карта",
        "size": size,
        "spawn": [0, -size * 0.5],
        "boss_spawn": [0, size * 0.7],
        "walls": [], "platforms": [], "jump_pads": [], "cup_spots": [],
        "structures": [],
    })
