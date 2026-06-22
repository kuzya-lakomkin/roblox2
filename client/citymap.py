"""Карта в стиле backrooms (жёлтые комнаты-лабиринт на двух уровнях по высоте).

Нижний уровень — ковролин + лабиринт жёлтых стен с гудящими люминесцентными
панелями на потолке. Верхний уровень — платформы со светящейся кромкой, куда
забираются прыжковыми падами (джамп-падами). Свечение — full-bright (setLightOff)
панелей/падов/кромок + bloom-постэффект.
"""

import math

from panda3d.core import CardMaker, NodePath, TextNode, Texture

import client.assets as _assets_mod
from client.assets import load_texture, texture_exists
from client.primitives import make_box
from client.procgen import make_cylinder
from client import asset_config as AC
from common.citydata import (ARENA, BOSS_SPAWN, building_specs, PLATFORMS,
                             LEVEL2_Z, JUMP_PADS, JUMP_PAD_RADIUS, WALL_HEIGHT,
                             CUP_SPOTS)

# ----- палитра backrooms: грязно-жёлтые обои/ковролин + холодное свечение
#       люминесцентных ламп и контрастные голубые джамп-пады. -----
SKY = (0.05, 0.045, 0.03, 1)         # тёмный «нигде»-фон за пределами комнат
CARPET = (0.46, 0.40, 0.16, 1)       # грязно-жёлтый ковролин
WALLPAPER = (0.74, 0.63, 0.27, 1)    # жёлтые обои (#bda045)
WALLPAPER_DARK = (0.57, 0.48, 0.20, 1)
BASEBOARD = (0.30, 0.25, 0.12, 1)    # тёмный плинтус
LIGHT_PANEL = (1.0, 0.97, 0.80, 1)   # флуоресцентный свет (тёплый белый), full-bright
LIGHT_FRAME = (0.34, 0.32, 0.22, 1)
PLATFORM_TOP = (0.50, 0.44, 0.18, 1)  # верх платформы (ковролин 2-го уровня)
PLATFORM_EDGE = (1.0, 0.93, 0.55, 1)  # светящаяся кромка платформы
JUMP_PAD = (0.22, 0.85, 1.0, 1)       # светящийся джамп-пад (голубой контраст)
JUMP_PAD_CORE = (0.6, 0.97, 1.0, 1)


def _neon(np):
    """Сделать узел «светящимся» — игнорировать освещение сцены."""
    np.setLightOff(1)
    return np


def _tiled_texture(loader, path):
    """Загрузить текстуру с повтором (тайлингом) и сглаживанием. Нет файла -> None."""
    if loader is None or not texture_exists(path):
        return None
    tex = load_texture(loader, path)            # фильтры (мипмапы+анизотропия) ставит load_texture
    tex.setWrapU(Texture.WM_repeat)
    tex.setWrapV(Texture.WM_repeat)
    tex.setMinfilter(Texture.FTLinearMipmapLinear)
    tex.setMagfilter(Texture.FTLinear)
    tex.setAnisotropicDegree(_assets_mod._ANISO)
    return tex


def build_city(parent, loader=None):
    """Построить статичную карту backrooms. Возвращает корневой NodePath.

    loader нужен для текстур пола/стен (backrooms_floor/backrooms_wall);
    без него (или без файлов) карта рисуется сплошными цветами палитры.
    """
    root = parent.attachNewNode("backrooms")

    floor_tex = _tiled_texture(loader, AC.BACKROOMS_FLOOR_TEXTURE)
    wall_tex = _tiled_texture(loader, AC.BACKROOMS_WALL_TEXTURE)

    # ковролин (пол) — с текстурой backrooms_floor, если она есть
    ground = make_box(2 * ARENA, 2 * ARENA, 0.4,
                      (1, 1, 1, 1) if floor_tex else CARPET, uv_scale=0.32)
    ground.setZ(-0.2)
    if floor_tex:
        ground.setTexture(floor_tex)
    ground.reparentTo(root)

    # периметральные стены (закрывают оба уровня)
    _build_perimeter(root, wall_tex)

    # стены-блоки нижнего уровня (комнаты-лабиринт)
    for i, (cx, cy, w, d) in enumerate(building_specs()):
        _build_wall_block(root, cx, cy, w, d, i, wall_tex)

    # гудящие люминесцентные панели: над нижним уровнем и над верхним
    _build_ceiling_lights(root, z=WALL_HEIGHT - 0.05, step=12.0, panel=4.0)
    _build_ceiling_lights(root, z=LEVEL2_Z + 9.0, step=14.0, panel=5.0)

    # платформы 2-го уровня
    for cx, cy, w, d in PLATFORMS:
        _build_platform(root, cx, cy, w, d)

    # прыжковые пады (на 2-й уровень)
    for cx, cy in JUMP_PADS:
        _build_jump_pad(root, cx, cy)

    # «арена» главного босса
    _build_boss_pad(root)

    # 4 угловых пьедестала для белых стаканов (ритуал BLACK KING)
    for cx, cy in CUP_SPOTS:
        _build_cup_pedestal(root, cx, cy)

    # карта статична — схлопываем сотни узлов в батчи (быстрее рендер)
    root.flattenStrong()
    return root


def _build_perimeter(root, wall_tex=None):
    t = 1.5
    H = LEVEL2_Z + 10.0                 # высокие стены — закрывают оба уровня
    for sx, sy, w, d in (
        (0, ARENA, 2 * ARENA, t),
        (0, -ARENA, 2 * ARENA, t),
        (ARENA, 0, t, 2 * ARENA),
        (-ARENA, 0, t, 2 * ARENA),
    ):
        wall = make_box(w, d, H, (1, 1, 1, 1) if wall_tex else WALLPAPER, uv_scale=0.4)
        wall.setPos(sx, sy, H / 2)
        if wall_tex:
            wall.setTexture(wall_tex)
        wall.reparentTo(root)
        base = make_box(w + 0.1, d + 0.1, 0.7, BASEBOARD)
        base.setPos(sx, sy, 0.35)
        base.reparentTo(root)


def _build_wall_block(root, cx, cy, w, d, i, wall_tex=None):
    H = WALL_HEIGHT
    if wall_tex:
        body = make_box(w, d, H, (1, 1, 1, 1), uv_scale=0.4)
        body.setTexture(wall_tex)
    else:
        body = make_box(w, d, H, WALLPAPER if i % 2 == 0 else WALLPAPER_DARK)
    body.setPos(cx, cy, H / 2)
    body.reparentTo(root)
    # плинтус по низу
    base = make_box(w + 0.3, d + 0.3, 0.7, BASEBOARD)
    base.setPos(cx, cy, 0.35)
    base.reparentTo(root)
    # тёмный карниз по верху: ПЕРЕКРЫВАЕТ верхнюю грань тела (поднят выше H), иначе
    # две совпадающие крышки z-fight'ят и крыша столба «мерцает» при вращении камеры
    cap = make_box(w + 0.2, d + 0.2, 0.5, WALLPAPER_DARK)
    cap.setPos(cx, cy, H - 0.12)          # верх карниза = H+0.13 (выше тела) -> нет совпадения
    cap.reparentTo(root)


def _build_ceiling_lights(root, z, step, panel):
    """Сетка светящихся люминесцентных панелей (full-bright) с тёмной рамкой."""
    n = int(ARENA / step)
    coords = [i * step for i in range(-n, n + 1)]
    for x in coords:
        for y in coords:
            frame = make_box(panel + 0.6, panel + 0.6, 0.3, LIGHT_FRAME)
            frame.setPos(x, y, z + 0.02)
            frame.reparentTo(root)
            light = make_box(panel, panel, 0.18, LIGHT_PANEL)
            light.setPos(x, y, z)
            _neon(light).reparentTo(root)


def _build_platform(root, cx, cy, w, d):
    th = 0.6
    top = LEVEL2_Z
    slab = make_box(w, d, th, PLATFORM_TOP)
    slab.setPos(cx, cy, top - th / 2)
    slab.reparentTo(root)
    # светящаяся кромка по периметру верхней грани
    for ex, ey, ew, ed in (
        (cx, cy + d / 2, w, 0.25),
        (cx, cy - d / 2, w, 0.25),
        (cx + w / 2, cy, 0.25, d),
        (cx - w / 2, cy, 0.25, d),
    ):
        edge = make_box(ew, ed, 0.18, PLATFORM_EDGE)
        edge.setPos(ex, ey, top + 0.02)
        _neon(edge).reparentTo(root)


def _build_jump_pad(root, cx, cy):
    disc = make_cylinder(JUMP_PAD_RADIUS + 0.2, 0.2, 24, (0.08, 0.12, 0.14, 1))
    disc.setPos(cx, cy, 0.12)
    disc.reparentTo(root)
    ring = make_cylinder(JUMP_PAD_RADIUS, 0.14, 24, JUMP_PAD)
    ring.setPos(cx, cy, 0.18)
    _neon(ring).reparentTo(root)
    core = make_cylinder(JUMP_PAD_RADIUS * 0.5, 0.22, 20, JUMP_PAD_CORE)
    core.setPos(cx, cy, 0.2)
    _neon(core).reparentTo(root)
    # светящаяся стрелка-«шеврон» вверх (приглашает прыгнуть)
    for k in range(3):
        chev = make_box(0.5, 0.5, 0.12, JUMP_PAD)
        chev.setPos(cx, cy, 0.6 + k * 0.5)
        _neon(chev).reparentTo(root)


def _build_cup_pedestal(root, cx, cy):
    """Тёмный пьедестал со светящимся кольцом — место под белый стакан."""
    base = make_box(2.2, 2.2, 0.9, (0.10, 0.09, 0.07, 1))
    base.setPos(cx, cy, 0.45)
    base.reparentTo(root)
    ring = make_cylinder(1.1, 0.12, 22, (0.85, 0.3, 0.95, 1))   # фиолетовое неоновое кольцо
    ring.setPos(cx, cy, 0.95)
    _neon(ring).reparentTo(root)


def _build_boss_pad(root):
    bx, by = BOSS_SPAWN
    disc = make_cylinder(6.2, 0.18, 28, (0.12, 0.10, 0.05, 1))
    disc.setPos(bx, by, 0.06)
    disc.reparentTo(root)
    ring = make_cylinder(6.6, 0.10, 28, (1.0, 0.85, 0.3, 1))
    ring.setPos(bx, by, 0.11)
    _neon(ring).reparentTo(root)
    inner = make_cylinder(5.4, 0.12, 28, (1.0, 0.55, 0.1, 1))
    inner.setPos(bx, by, 0.10)
    _neon(inner).reparentTo(root)


def build_spawn_pillar(parent, loader, font=None):
    """Витрина на спавне: 4 картинки на стенах параллелепипеда + надпись SWAGA."""
    root = parent.attachNewNode("spawn_pillar")

    W = D = 3.6          # ширина/глубина витрины
    H = 4.0              # высота стен
    base_z = 1.0         # верх постамента

    pedestal = make_box(W + 1.0, D + 1.0, 1.0, WALLPAPER_DARK)
    pedestal.setPos(0, 0, 0.5)
    pedestal.reparentTo(root)

    core = make_box(W - 0.2, D - 0.2, H - 0.05, (0.10, 0.09, 0.06, 1))
    core.setPos(0, 0, base_z + H / 2)
    core.reparentTo(root)

    cap = make_box(W + 0.3, D + 0.3, 0.25, WALLPAPER_DARK)
    cap.setPos(0, 0, base_z + H + 0.05)
    cap.reparentTo(root)

    # 4 картинки на боковых стенах
    texs = []
    for p in AC.SHOWCASE_TEXTURES:
        texs.append(load_texture(loader, p if texture_exists(p) else AC.LITVIN_TEXTURE))
    cm = CardMaker("showcase_wall")
    cm.setFrame(-W / 2, W / 2, 0, H)
    walls = [
        ((0, -D / 2 - 0.01, base_z), 0, texs[0]),
        ((0, D / 2 + 0.01, base_z), 180, texs[1]),
        ((W / 2 + 0.01, 0, base_z), 90, texs[2]),
        ((-W / 2 - 0.01, 0, base_z), 270, texs[3]),
    ]
    for pos, hrot, tex in walls:
        card = root.attachNewNode(cm.generate())
        card.setTexture(tex)
        card.setTwoSided(True)
        card.setPos(*pos)
        card.setH(hrot)
        _neon(card)

    # светящиеся рёбра по вертикальным углам
    for sx in (-1, 1):
        for sy in (-1, 1):
            edge = make_box(0.18, 0.18, H + 0.2, PLATFORM_EDGE)
            edge.setPos(sx * (W / 2 + 0.05), sy * (D / 2 + 0.05), base_z + H / 2)
            _neon(edge).reparentTo(root)
    trim = make_box(W + 0.5, D + 0.5, 0.12, JUMP_PAD)
    trim.setPos(0, 0, base_z + H + 0.2)
    _neon(trim).reparentTo(root)

    # надпись SWAGA
    tn = TextNode("swaga_sign")
    if font:
        tn.setFont(font)
    tn.setText("SWAGA")
    tn.setAlign(TextNode.ACenter)
    tn.setTextColor(1.0, 0.93, 0.55, 1)
    tn.setShadow(0.06, 0.06)
    tn.setShadowColor(0.22, 0.85, 1.0, 1)
    sign = root.attachNewNode(tn)
    sign.setScale(1.8)
    sign.setZ(6.4)
    sign.setBillboardPointEye()
    _neon(sign)

    have_any = texture_exists(AC.LITVIN_TEXTURE) or any(
        texture_exists(p) for p in AC.SHOWCASE_TEXTURES)
    if not have_any:
        hint = TextNode("showcase_hint")
        if font:
            hint.setFont(font)
        hint.setText("положи картинки в assets/textures/showcase_1..4.png")
        hint.setAlign(TextNode.ACenter)
        hint.setTextColor(1, 1, 0.4, 1)
        hnp = root.attachNewNode(hint)
        hnp.setScale(0.4)
        hnp.setZ(3.0)
        hnp.setBillboardPointEye()
        _neon(hnp)

    return root
