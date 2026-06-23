"""Процедурная генерация 3D-моделей из примитивов (без внешних .egg/.gltf).

Базовые примитивы: сфера и цилиндр (с нормалями для освещения).
Сборки: червь-игрок, таракан, пчела, босс «Папаня».
"""

import math

from panda3d.core import (Geom, GeomNode, GeomTriangles, GeomVertexData,
                          GeomVertexFormat, GeomVertexWriter, NodePath)

_FMT = GeomVertexFormat.getV3n3c4()
_FMT_UV = GeomVertexFormat.getV3n3c4t2()


def _finish(name, vdata, tris):
    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode(name)
    node.addGeom(geom)
    np = NodePath(node)
    np.setTwoSided(True)
    return np


def make_sphere(radius=1.0, lat=12, lon=16, color=(1, 1, 1, 1)):
    """UV-сфера с центром в начале координат."""
    vdata = GeomVertexData("sphere", _FMT, Geom.UHStatic)
    vw = GeomVertexWriter(vdata, "vertex")
    nw = GeomVertexWriter(vdata, "normal")
    cw = GeomVertexWriter(vdata, "color")
    tris = GeomTriangles(Geom.UHStatic)

    for i in range(lat + 1):
        theta = math.pi * i / lat          # 0..pi (полюс к полюсу)
        st, ct = math.sin(theta), math.cos(theta)
        for j in range(lon + 1):
            phi = 2 * math.pi * j / lon
            sp, cp = math.sin(phi), math.cos(phi)
            nx, ny, nz = st * cp, st * sp, ct
            vw.addData3(nx * radius, ny * radius, nz * radius)
            nw.addData3(nx, ny, nz)
            cw.addData4(*color)

    row = lon + 1
    for i in range(lat):
        for j in range(lon):
            a = i * row + j
            b = a + 1
            c = a + row
            d = c + 1
            tris.addVertices(a, c, b)
            tris.addVertices(b, c, d)
    return _finish("sphere", vdata, tris)


def make_uv_sphere(radius=1.0, lat=14, lon=18, color=(1, 1, 1, 1)):
    """UV-сфера с текстурными координатами (для наложения текстуры)."""
    vdata = GeomVertexData("uvsphere", _FMT_UV, Geom.UHStatic)
    vw = GeomVertexWriter(vdata, "vertex")
    nw = GeomVertexWriter(vdata, "normal")
    cw = GeomVertexWriter(vdata, "color")
    tw = GeomVertexWriter(vdata, "texcoord")
    tris = GeomTriangles(Geom.UHStatic)

    for i in range(lat + 1):
        theta = math.pi * i / lat
        st, ct = math.sin(theta), math.cos(theta)
        for j in range(lon + 1):
            phi = 2 * math.pi * j / lon
            sp, cp = math.sin(phi), math.cos(phi)
            nx, ny, nz = st * cp, st * sp, ct
            vw.addData3(nx * radius, ny * radius, nz * radius)
            nw.addData3(nx, ny, nz)
            cw.addData4(*color)
            tw.addData2(j / lon, 1.0 - i / lat)

    row = lon + 1
    for i in range(lat):
        for j in range(lon):
            a = i * row + j
            b = a + 1
            c = a + row
            d = c + 1
            tris.addVertices(a, c, b)
            tris.addVertices(b, c, d)
    return _finish("uvsphere", vdata, tris)


def make_slit(scale=1.0, texture=None):
    """ЩЕЛЬ: две ОКРУГЛЫЕ сферы, плотно прижатые друг к другу, с чёрной точкой
    в ложбинке между ними.

    Шары смещены по локальной оси X (тангента к стене), ложбинка идёт вертикально.
    «Перёд» модели — +Y; при setH(heading) повёрнут лицом в центр арены. Текстура
    (если задана) ложится ТОЛЬКО на шары — чёрная точка остаётся чёрной.
    """
    root = NodePath("slit")
    r = 0.6
    for sx in (-1, 1):
        ball = make_uv_sphere(1.0, 20, 24, (1, 1, 1, 1))  # ровный шар (не сплюснут)
        if texture is not None:
            ball.setTexture(texture, 1)
        _attach(root, ball, pos=(sx * r * 0.82, 0, 0), scale=(r, r, r))
    # чёрная точка между шарами (спереди, в ложбинке)
    dot = make_sphere(1.0, 12, 12, (0.02, 0.02, 0.02, 1))
    dot.setLightOff(1)
    _attach(root, dot, pos=(0, r * 0.62, 0), scale=(0.13, 0.18, 0.34))
    root.setScale(scale)
    return root


def make_cylinder(radius=1.0, height=1.0, segments=12, color=(1, 1, 1, 1)):
    """Цилиндр вдоль оси Z, центр в начале координат."""
    vdata = GeomVertexData("cyl", _FMT, Geom.UHStatic)
    vw = GeomVertexWriter(vdata, "vertex")
    nw = GeomVertexWriter(vdata, "normal")
    cw = GeomVertexWriter(vdata, "color")
    tris = GeomTriangles(Geom.UHStatic)
    hz = height / 2.0

    # боковая поверхность
    for j in range(segments + 1):
        phi = 2 * math.pi * j / segments
        cx, cy = math.cos(phi), math.sin(phi)
        for z in (-hz, hz):
            vw.addData3(cx * radius, cy * radius, z)
            nw.addData3(cx, cy, 0)
            cw.addData4(*color)
    for j in range(segments):
        a = j * 2
        b = a + 1
        c = a + 2
        d = a + 3
        tris.addVertices(a, c, b)
        tris.addVertices(b, c, d)

    # крышки
    base = (segments + 1) * 2
    for sign, nz in ((1, 1.0), (-1, -1.0)):
        center_idx = vw.getWriteRow()
        vw.addData3(0, 0, hz * sign)
        nw.addData3(0, 0, nz)
        cw.addData4(*color)
        ring_start = vw.getWriteRow()
        for j in range(segments + 1):
            phi = 2 * math.pi * j / segments
            vw.addData3(math.cos(phi) * radius, math.sin(phi) * radius, hz * sign)
            nw.addData3(0, 0, nz)
            cw.addData4(*color)
        for j in range(segments):
            a = ring_start + j
            b = ring_start + j + 1
            if sign > 0:
                tris.addVertices(center_idx, a, b)
            else:
                tris.addVertices(center_idx, b, a)
    return _finish("cyl", vdata, tris)


def make_truncated_cone(r_bottom=0.5, r_top=0.7, height=1.0, segments=18, color=(1, 1, 1, 1)):
    """Усечённый конус вдоль Z (для стаканчика): радиус снизу r_bottom, сверху r_top."""
    vdata = GeomVertexData("cone", _FMT, Geom.UHStatic)
    vw = GeomVertexWriter(vdata, "vertex")
    nw = GeomVertexWriter(vdata, "normal")
    cw = GeomVertexWriter(vdata, "color")
    tris = GeomTriangles(Geom.UHStatic)
    hz = height / 2.0
    for j in range(segments + 1):
        phi = 2 * math.pi * j / segments
        cx, cy = math.cos(phi), math.sin(phi)
        for r, z in ((r_bottom, -hz), (r_top, hz)):
            vw.addData3(cx * r, cy * r, z)
            nw.addData3(cx, cy, 0.3)
            cw.addData4(*color)
    for j in range(segments):
        a = j * 2
        tris.addVertices(a, a + 2, a + 1)
        tris.addVertices(a + 1, a + 2, a + 3)
    # дно (диск)
    base = vw.getWriteRow()
    vw.addData3(0, 0, -hz)
    nw.addData3(0, 0, -1)
    cw.addData4(*color)
    ring = vw.getWriteRow()
    for j in range(segments + 1):
        phi = 2 * math.pi * j / segments
        vw.addData3(math.cos(phi) * r_bottom, math.sin(phi) * r_bottom, -hz)
        nw.addData3(0, 0, -1)
        cw.addData4(*color)
    for j in range(segments):
        tris.addVertices(base, ring + j + 1, ring + j)
    return _finish("cone", vdata, tris)


def make_cup(scale=1.0):
    """Белый пластиковый стаканчик: усечённый конус + тёмная «пустота» внутри."""
    root = NodePath("cup")
    body = make_truncated_cone(0.32, 0.46, 0.95, 20, (0.95, 0.95, 0.96, 1))
    _attach(root, body, pos=(0, 0, 0.48))
    inner = make_truncated_cone(0.27, 0.41, 0.9, 20, (0.55, 0.55, 0.6, 1))
    _attach(root, inner, pos=(0, 0, 0.55))
    root.setScale(scale)
    return root


def _attach(parent, child, pos=(0, 0, 0), scale=(1, 1, 1), hpr=(0, 0, 0)):
    child.reparentTo(parent)
    child.setPos(*pos)
    child.setScale(*scale)
    child.setHpr(*hpr)
    return child


# ----------------------------------------------------------------------------
# Сборные модели
# ----------------------------------------------------------------------------

def make_worm(body_color=(0.3, 0.75, 0.35, 1), eye_color=(0.05, 0.05, 0.05, 1)):
    """Червь-игрок: вертикальное сегментированное тело, голова с глазами, hat_node."""
    root = NodePath("worm")
    segments = 6
    z = 0.35
    for i in range(segments):
        t = i / (segments - 1)
        r = 0.45 - 0.22 * t                # уменьшается к хвосту (низ)
        seg = make_sphere(1.0, 10, 12, body_color)
        # лёгкий градиент по телу
        shade = 1.0 - 0.15 * t
        seg.setColorScale(shade, shade, shade, 1)
        _attach(root, seg, pos=(0, 0, z), scale=(r, r, r))
        z += r * 1.4

    # голова — крупная сфера сверху
    head_r = 0.55
    head = make_sphere(1.0, 12, 16, body_color)
    head_z = z + head_r * 0.4
    _attach(root, head, pos=(0, 0, head_z), scale=(head_r, head_r, head_r))

    # глаза (смотрят вперёд, +Y)
    for sx in (-1, 1):
        eye = make_sphere(1.0, 8, 8, (1, 1, 1, 1))
        _attach(root, eye, pos=(sx * 0.22, head_r * 0.8, head_z + 0.12),
                scale=(0.16, 0.16, 0.16))
        pupil = make_sphere(1.0, 6, 6, eye_color)
        _attach(root, pupil, pos=(sx * 0.22, head_r * 0.95, head_z + 0.12),
                scale=(0.08, 0.08, 0.08))

    # точка крепления шляпы
    hat_node = root.attachNewNode("hat_node")
    hat_node.setPos(0, 0, head_z + head_r * 0.9)

    root.setPythonTag("hat_node", hat_node)
    return root


def make_cockroach(body_color=(0.28, 0.16, 0.1, 1), scale=1.0):
    """Таракан: 3 вытянутые сферы, 6 ног-цилиндров, 2 усика."""
    root = NodePath("cockroach")
    body = NodePath("body")
    body.reparentTo(root)

    # брюшко, грудь, голова (вдоль +Y)
    abdomen = make_sphere(1.0, 6, 8, body_color)
    _attach(body, abdomen, pos=(0, -0.35, 0.25), scale=(0.32, 0.5, 0.26))
    thorax = make_sphere(1.0, 6, 8, body_color)
    _attach(body, thorax, pos=(0, 0.15, 0.27), scale=(0.28, 0.32, 0.24))
    head = make_sphere(1.0, 6, 8, (body_color[0] * 0.8, body_color[1] * 0.8,
                                    body_color[2] * 0.8, 1))
    _attach(body, head, pos=(0, 0.5, 0.26), scale=(0.2, 0.2, 0.18))

    # 6 ног (тонкие цилиндры, наклонены наружу)
    leg_color = (0.12, 0.07, 0.05, 1)
    for side in (-1, 1):
        for k, y in enumerate((0.25, 0.0, -0.25)):
            leg = make_cylinder(0.03, 0.45, 4, leg_color)
            leg.reparentTo(body)
            leg.setPos(side * 0.28, y, 0.12)
            leg.setHpr(0, 0, side * 55)
    # усики (два сегмента цилиндра)
    for side in (-1, 1):
        a1 = make_cylinder(0.02, 0.3, 3, leg_color)
        a1.reparentTo(body)
        a1.setPos(side * 0.08, 0.6, 0.32)
        a1.setHpr(0, 60, side * 10)
        a2 = make_cylinder(0.018, 0.25, 3, leg_color)
        a2.reparentTo(body)
        a2.setPos(side * 0.14, 0.78, 0.45)
        a2.setHpr(0, 35, side * 25)

    root.setScale(scale)
    root.flattenStrong()
    return root


def make_smile_roach(scale=1.0):
    """Улыбающийся таракан: как обычный, но со светящимися красными глазами и
    аэрозольным баллончиком на спине."""
    root = NodePath("smile_roach")
    # тело — чуть темнее обычного таракана
    body = make_cockroach(body_color=(0.18, 0.10, 0.06, 1), scale=1.0)
    body.reparentTo(root)

    # красные светящиеся глаза (2 маленькие сферы на голове)
    eye_color = (1.0, 0.05, 0.05, 1)
    for side in (-1, 1):
        eye = make_sphere(1.0, 4, 6, eye_color)
        eye.reparentTo(root)
        eye.setScale(0.07, 0.07, 0.06)
        eye.setPos(side * 0.09, 0.56, 0.35)
        eye.setLightOff(1)   # full-bright красные глаза

    # маленький аэрозольный баллончик на спине (цилиндр + шар-крышка)
    can_body = make_cylinder(0.06, 0.22, 8, (0.7, 0.7, 0.72, 1))
    can_body.reparentTo(root)
    can_body.setPos(0, -0.15, 0.5)
    can_body.setHpr(0, 80, 0)
    can_top = make_sphere(1.0, 4, 6, (0.55, 0.55, 0.6, 1))
    can_top.reparentTo(root)
    can_top.setScale(0.07, 0.07, 0.06)
    can_top.setPos(0, -0.26, 0.58)

    root.setScale(scale)
    return root


def make_neon_ant(scale=1.0):
    """Синий неоновый муравей-стрелок: тело таракана + светящиеся орбы (full-bright)."""
    root = NodePath("neon_ant")
    body = make_cockroach(body_color=(0.16, 0.52, 1.0, 1), scale=1.0)
    body.reparentTo(root)
    # светящийся «реактор» на спине
    orb = make_sphere(1.0, 6, 8, (0.45, 0.92, 1.0, 1))
    _attach(root, orb, pos=(0, 0.0, 0.5), scale=(0.22, 0.3, 0.18))
    # светящиеся глаза
    for sx in (-1, 1):
        eye = make_sphere(1.0, 4, 6, (0.65, 1.0, 1.0, 1))
        _attach(root, eye, pos=(sx * 0.12, 0.62, 0.34), scale=(0.08, 0.08, 0.08))
    # светящиеся кончики усиков
    for sx in (-1, 1):
        tip = make_sphere(1.0, 4, 6, (0.5, 0.95, 1.0, 1))
        _attach(root, tip, pos=(sx * 0.16, 0.9, 0.5), scale=(0.06, 0.06, 0.06))
    root.setLightOff(1)
    root.setScale(scale)
    root.flattenStrong()
    return root


def make_bk_minion(scale=0.9):
    """Маленькая копия BLACK KING: тёмный фиолетовый таракан (full-bright свечение)."""
    root = make_cockroach(body_color=(0.08, 0.0, 0.18, 1), scale=scale)
    root.setLightOff(1)
    root.setColorScale(0.55, 0.0, 1.0, 1)
    return root


def make_wormchello_head(face_texture=None):
    """Голова ЧЕРВЯЧЕЛЛО КРЫТОЧЕЛЛО — большая телесного цвета сфера с причёской.

    face_texture: уже загруженная Texture или None. Если задана, натягивается
    так, что центр картинки = перёд головы (при heading=0 голова смотрит в +Y).
    """
    from panda3d.core import TextureStage
    root = NodePath("wormchello_head")
    flesh = (0.91, 0.72, 0.58, 1)
    head_r = 1.4

    # основная сфера головы
    head_np = make_uv_sphere(head_r, 14, 20, flesh)
    head_np.reparentTo(root)
    if face_texture:
        head_np.setTexture(face_texture)
        # сдвиг UV: U=0.25 = направление +Y (перёд) → попадает на центр текстуры (U=0.5)
        ts = TextureStage.getDefault()
        head_np.setTexOffset(ts, (0.25, 0.0))

    # причёска: ряд стренд-цилиндров на макушке с наклоном вперёд
    hair = (0.22, 0.14, 0.08, 1)
    strands = [
        # (x,  y,    z,   rx  rz  len)  — rx=наклон вперёд, rz=в стороны
        (0.00, 0.10, head_r * 0.88, -25,  0, 0.60),
        (0.30, 0.05, head_r * 0.82, -30, -12, 0.52),
        (-0.30, 0.05, head_r * 0.82, -30, 12, 0.52),
        (0.55, 0.0,  head_r * 0.72, -35, -22, 0.44),
        (-0.55, 0.0, head_r * 0.72, -35, 22, 0.44),
        (0.15, -0.15, head_r * 0.85, -20, -6, 0.56),
        (-0.15, -0.15, head_r * 0.85, -20, 6, 0.56),
    ]
    for (sx, sy, sz, rx, rz, slen) in strands:
        strand = make_cylinder(0.10, slen, 5, hair)
        strand.reparentTo(root)
        strand.setPos(sx, sy, sz)
        strand.setHpr(rz, rx, 0)
        strand.setLightOff(1)  # full-bright чтобы волосы были видны

    return root


def make_wormchello_segment(radius=1.0, color=(0.88, 0.68, 0.54, 1)):
    """Один сегмент тела Червячелло — слегка сплюснутая сфера телесного цвета."""
    np = make_sphere(radius, 8, 12, color)
    np.setScale(1.0, 1.0, 0.82)
    return np


def make_lina_sphere():
    """Светящаяся сфера ЛИНА — щит первой фазы ЧЕРВЯЧЕЛЛО КРЫТОЧЕЛЛО."""
    root = NodePath("lina_sphere")
    # ядро — яркий полный блик
    core = make_sphere(0.75, 14, 18, (0.25, 0.80, 1.0, 1.0))
    core.reparentTo(root)
    core.setLightOff(1)
    # внешняя оболочка чуть больше и темнее
    shell = make_sphere(1.05, 10, 14, (0.15, 0.55, 0.90, 1.0))
    shell.reparentTo(root)
    shell.setLightOff(1)
    return root


def make_boss(scale=3.0):
    """Босс «Папаня»: крупный таракан с золотой короной."""
    root = make_cockroach(body_color=(0.35, 0.2, 0.12, 1), scale=scale)
    crown = NodePath("crown")
    gold = (0.95, 0.82, 0.2, 1)
    band = make_cylinder(0.18, 0.12, 10, gold)
    _attach(crown, band, pos=(0, 0, 0))
    for k in range(5):
        phi = 2 * math.pi * k / 5
        spike = make_cylinder(0.03, 0.18, 4, gold)
        _attach(crown, spike, pos=(0.16 * math.cos(phi), 0.16 * math.sin(phi), 0.13))
    # корона над головой (голова таракана у +Y, чуть выше)
    crown.reparentTo(root)
    crown.setPos(0, 0.5, 0.55)
    return root


def make_bee(body_color=(0.95, 0.78, 0.15, 1)):
    """Пчела: тело-сфера, коническое жало сзади, два крыла."""
    root = NodePath("bee")
    body = make_sphere(1.0, 5, 7, body_color)
    _attach(root, body, scale=(0.2, 0.28, 0.2))
    stripe = make_sphere(1.0, 5, 7, (0.1, 0.1, 0.1, 1))
    _attach(root, stripe, pos=(0, -0.05, 0), scale=(0.205, 0.1, 0.205))
    sting = make_cylinder(0.04, 0.2, 3, (0.1, 0.1, 0.1, 1))
    _attach(root, sting, pos=(0, -0.32, 0), hpr=(0, 90, 0), scale=(0.6, 1, 0.6))
    for sx in (-1, 1):
        wing = make_sphere(1.0, 4, 6, (0.85, 0.9, 1.0, 0.6))
        wing.setTransparency(True)
        _attach(root, wing, pos=(sx * 0.18, 0.05, 0.12), scale=(0.18, 0.1, 0.04))
    root.flattenStrong()
    return root
