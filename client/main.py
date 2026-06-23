"""Клиент Roblox 2 (Panda3D, вид от первого лица).

Запуск:  python -m client.main --name Стёпа --host 127.0.0.1
"""

import argparse
import json as _json_mod
import math
import sys
import urllib.request as _urllib_req

from direct.gui.DirectGui import DirectEntry
from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from panda3d.core import (AmbientLight, AntialiasAttrib, AudioSound, CardMaker,
                          DirectionalLight, NodePath, TextNode,
                          TransparencyAttrib, Vec2, Vec3,
                          WindowProperties, loadPrcFileData)

from common import config as C
from common.citydata import (building_rects, in_any_building, resolve_collision,
                             support_z, on_jump_pad, CUP_SPOTS, WALL_HEIGHT)
from client.network import NetworkClient
from client.primitives import make_box
from client.procgen import (make_sphere, make_cockroach, make_bee, make_boss,
                            make_neon_ant, make_slit, make_cup, make_bk_minion)
from client.citymap import build_city, build_spawn_pillar, SKY
from client.ui import (MainMenu, PauseMenu, SettingsMenu, InfoScreen,
                       LoginScreen, RegisterScreen, KeyBindingsScreen,
                       DEFAULT_BINDINGS)
import client.assets as _assets_mod
from client.assets import load_sound, load_font, load_music, load_model, load_texture
from client.particles import ParticleSystem
from client import asset_config as AC
from direct.filter.CommonFilters import CommonFilters

def _load_gfx_quality() -> str:
    """Читает качество графики из client_settings.json ДО создания окна."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "client_settings.json")
    try:
        with open(path, encoding="utf-8") as _f:
            return _json_mod.load(_f).get("gfx_quality", "medium")
    except Exception:
        return "medium"


_GFX_QUALITY = _load_gfx_quality()


def _http_post(url: str, data: dict) -> dict:
    """Синхронный HTTP POST без внешних зависимостей."""
    try:
        payload = _json_mod.dumps(data).encode()
        req = _urllib_req.Request(url, payload, {"Content-Type": "application/json"})
        with _urllib_req.urlopen(req, timeout=8) as r:
            return _json_mod.loads(r.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}


loadPrcFileData("", "window-title SWAGA")
# качество графики: low / medium / high (читается из client_settings.json до создания окна)
if _GFX_QUALITY == "low":
    loadPrcFileData("", "sync-video false")
    loadPrcFileData("", "framebuffer-multisample 0")
    loadPrcFileData("", "multisamples 0")
    loadPrcFileData("", "texture-anisotropic-degree 1")
    loadPrcFileData("", "texture-scale 0.5")
elif _GFX_QUALITY == "medium":
    loadPrcFileData("", "sync-video true")
    loadPrcFileData("", "framebuffer-multisample 1")
    loadPrcFileData("", "multisamples 2")
    loadPrcFileData("", "texture-anisotropic-degree 4")
else:  # high
    loadPrcFileData("", "sync-video true")
    loadPrcFileData("", "framebuffer-multisample 1")
    loadPrcFileData("", "multisamples 4")
    loadPrcFileData("", "texture-anisotropic-degree 8")

_assets_mod._ANISO = {"low": 1, "medium": 4, "high": 8}.get(_GFX_QUALITY, 8)

MOUSE_SENS = 0.12  # дефолт (переопределяется self._mouse_sens из настроек)
# цвета червей в той же синтвейв-гамме (циан/розовый/фиолет/тил/сине-фиолет)
PLAYER_COLORS = [
    (0.16, 0.89, 0.91, 1), (1.00, 0.30, 0.55, 1), (0.62, 0.31, 0.87, 1),
    (0.45, 0.40, 0.95, 1), (0.20, 0.80, 0.72, 1), (0.95, 0.55, 0.85, 1),
]
# цвета дропа по типу (fallback-кубик, если нет модели)
DROP_COLORS = {
    "honey": (1.0, 0.78, 0.15, 1),       # мёд — янтарный
    "syrup": (0.55, 1.0, 0.15, 1),       # сироп — кислотно-зелёный
    "mayo": (0.97, 0.97, 0.92, 1),       # майонез — белый
    "lit_energy": (0.35, 0.95, 1.0, 1),  # LIT ENERGY — неоново-голубой
    "cup": (0.95, 0.95, 0.96, 1),        # белый пластиковый стакан
    "health": (0.95, 0.20, 0.25, 1),     # аптечка — красная
}


class WormModel:
    """Анимированный червь-игрок: тело-дуга от хвоста (стелется по земле) к голове
    с глазами. Плавные процедурные анимации покоя/ходьбы/прыжка и эмоций. Один и тот
    же риг используют и чужие аватары, и локальный игрок (чтобы видеть свои анимации).

    Иерархия: root (позиция/курс задаёт владелец) -> anim (анимационные повороты/
    масштаб) -> сегменты тела. Голова - последний сегмент, глаза - её дети.
    """

    N = 9

    def __init__(self, body_color=(0.3, 0.75, 0.35, 1), eye_color=(0.05, 0.05, 0.05, 1)):
        self.root = NodePath("worm")
        self.anim = self.root.attachNewNode("anim")
        self.segs = []
        self.base = []     # (x, y, z) базовая поза сегмента
        for i in range(self.N):
            s = i / (self.N - 1)                     # 0 хвост .. 1 голова
            y = -1.35 + 1.5 * s                      # хвост позади (-Y), голова спереди
            z = 0.16 + 1.7 * (s ** 1.45)             # хвост долго стелется, потом подъём
            r = 0.16 + 0.34 * math.sin(math.pi * (0.16 + 0.7 * s))  # тонкий хвост, тело потолще
            seg = make_sphere(1.0, 7, 10, body_color)
            shade = 0.82 + 0.18 * s
            seg.setColorScale(shade, shade, shade, 1)
            seg.reparentTo(self.anim)
            seg.setPos(0, y, z)
            seg.setScale(r)
            self.segs.append(seg)
            self.base.append((0.0, y, z))
        self.head = self.segs[-1]
        # глаза - дети головы (двигаются с её анимациями)
        for sx in (-1, 1):
            eye = make_sphere(1.0, 6, 8, (1, 1, 1, 1))
            eye.reparentTo(self.head)
            eye.setPos(sx * 0.42, 0.82, 0.28)
            eye.setScale(0.4)
            pupil = make_sphere(1.0, 4, 6, eye_color)
            pupil.reparentTo(self.head)
            pupil.setPos(sx * 0.42, 1.02, 0.28)
            pupil.setScale(0.2)
        self._t = 0.0
        self._sz = 1.0
        self._first_person = False

    def set_first_person(self, fp):
        """В виде от первого лица прячем голову+шею, чтобы не закрывали камеру,
        но тело/хвост остаются видимыми (игрок видит свои анимации)."""
        if fp == self._first_person:
            return
        self._first_person = fp
        for seg in self.segs[-2:]:
            seg.hide() if fp else seg.show()

    def update(self, dt, moving=False, on_ground=True, vz=0.0, emote=None, dead=False):
        if dead:
            self.root.hide()
            return
        self.root.show()
        self._t += dt
        t = self._t
        if emote == "dance":
            wave_speed, amp, lift = 13.0, 0.30, 0.12
        elif moving:
            wave_speed, amp, lift = 10.0, 0.16, 0.05
        else:
            wave_speed, amp, lift = 2.4, 0.05, 0.0     # покой: лёгкое «дыхание»
        N = len(self.segs)
        for i, seg in enumerate(self.segs):
            bx, by, bz = self.base[i]
            s = i / (N - 1)
            phase = t * wave_speed - s * 3.4           # бегущая волна хвост->голова
            sway = math.sin(phase) * amp * (0.3 + s)   # голова виляет сильнее
            bob = math.cos(phase) * amp * 0.5 * s + lift * math.sin(t * 3 + s * 2)
            seg.setPos(bx + sway, by, bz + bob)
        # прыжок: плавно вытягиваем тело по вертикали
        target_sz = 1.0 + max(-0.18, min(0.28, vz * 0.03)) if not on_ground else 1.0
        self._sz += (target_sz - self._sz) * min(1.0, 8 * dt)
        self.anim.setSz(self._sz)
        # эмоции (повороты anim-узла, не конфликтуют с курсом на root)
        r_t = h_t = z_t = 0.0
        p_head = 0.0
        if emote == "flex":
            r_t = 14 * math.sin(t * 9)                 # качается, «играет мышцами»
        elif emote == "dance":
            h_t = 20 * math.sin(t * 6)                 # вертится
            z_t = abs(math.sin(t * 6)) * 0.45          # подпрыгивает
        elif emote == "wave":
            p_head = 22 * math.sin(t * 7)              # голова кивает-машет
        cur_r, cur_h = self.anim.getR(), self.anim.getH()
        self.anim.setR(cur_r + (r_t - cur_r) * min(1.0, 10 * dt))
        self.anim.setH(cur_h + (h_t - cur_h) * min(1.0, 10 * dt))
        self.anim.setZ(self.anim.getZ() + (z_t - self.anim.getZ()) * min(1.0, 10 * dt))
        self.head.setP(self.head.getP() + (p_head - self.head.getP()) * min(1.0, 12 * dt))

    def set_body_color(self, color):
        """Сменить цвет тела (r, g, b) — применяется немедленно без пересборки геометрии."""
        r, g, b = color[0], color[1], color[2]
        for i, seg in enumerate(self.segs):
            s = i / (self.N - 1)
            shade = 0.82 + 0.18 * s
            seg.setColor(r * shade, g * shade, b * shade, 1)

    def destroy(self):
        self.root.removeNode()


class RemoteAvatar:
    """Визуальное представление другого игрока: анимированный червь + ник + HP + эмоция."""

    def __init__(self, parent, pid, name, font=None, color=None):
        body_color = tuple(color) + (1,) if color and len(color) == 3 else PLAYER_COLORS[pid % len(PLAYER_COLORS)]
        self.root = parent.attachNewNode(f"player{pid}")

        self.model = WormModel(body_color=body_color)
        self.model.root.reparentTo(self.root)

        # ник (цвет текста = цвет тела игрока)
        nr, ng, nb = body_color[:3]
        tn = TextNode(f"name{pid}")
        if font:
            tn.setFont(font)
        tn.setText(name)
        tn.setAlign(TextNode.ACenter)
        tn.setTextColor(nr, ng, nb, 1)
        tn.setCardColor(0, 0, 0, 0.55)
        tn.setCardAsMargin(0.2, 0.2, 0.1, 0.1)
        tn.setCardDecal(True)
        self.nametag = self.root.attachNewNode(tn)
        self.nametag.setScale(0.5)
        self.nametag.setZ(2.9)
        self.nametag.setBillboardPointEye()
        self.nametag.setLightOff(1)
        self.nametag.setDepthOffset(1)

        # HP-бар под ником (маленькая полоска здоровья, видна всем кроме самого игрока)
        from client.procgen import make_box as _mb
        self._hp_bar_root = self.root.attachNewNode(f"hpbar{pid}")
        self._hp_bar_root.setZ(2.55)
        self._hp_bar_root.setBillboardPointEye()
        self._hp_bar_root.setLightOff(1)
        self._hp_bar_root.setDepthOffset(1)
        bar_w = 1.1
        self._hp_bar_bg = _mb(bar_w, 0.001, 0.15, (0.18, 0.08, 0.08, 1))
        self._hp_bar_bg.reparentTo(self._hp_bar_root)
        self._hp_bar_fill = _mb(bar_w, 0.001, 0.15, (nr, ng, nb, 1))
        self._hp_bar_fill.reparentTo(self._hp_bar_root)
        self._hp_max_w = bar_w
        self._hp_frac = 1.0
        self._body_color = (nr, ng, nb)

        # подпись эмоции
        self.emote_tn = TextNode(f"emote{pid}")
        if font:
            self.emote_tn.setFont(font)
        self.emote_tn.setAlign(TextNode.ACenter)
        self.emote_tn.setTextColor(1, 1, 0.3, 1)
        self.emote_np = self.root.attachNewNode(self.emote_tn)
        self.emote_np.setScale(0.6)
        self.emote_np.setZ(3.4)
        self.emote_np.setBillboardPointEye()
        self.emote_np.hide()

        self._prev = None
        self._vis = None      # [x, y, z, h] — интерполированная визуальная позиция
        # параметры анимации, обновляемые по снапшоту и читаемые в lerp_step
        self._anim_moving = False
        self._anim_vz = 0.0
        self._anim_on_ground = True
        self._anim_emote = None
        self._anim_dead = False

    def update(self, snap, dt):
        x, y, z = snap["pos"]
        h = snap["h"]
        dead = bool(snap.get("dead"))
        if self._vis is None:
            self._vis = [x, y, z, h]
        self._tgt = (x, y, z, h)
        # вычислить параметры движения из дельты снапшотов
        moving, vz, on_ground = False, 0.0, True
        if self._prev is not None and dt > 0:
            dx, dy, dz = x - self._prev[0], y - self._prev[1], z - self._prev[2]
            moving = (dx * dx + dy * dy) > (0.02 * 0.02)
            vz = dz / dt
            on_ground = z <= 0.06 and abs(vz) < 1.0
        self._prev = (x, y, z)
        emote = snap.get("emote")
        self._anim_moving = moving
        self._anim_vz = vz
        self._anim_on_ground = on_ground
        self._anim_emote = emote
        self._anim_dead = dead
        # HP-бар
        hp = snap.get("hp", 100)
        max_hp = 100
        frac = max(0.0, min(1.0, hp / max_hp))
        if abs(frac - self._hp_frac) > 0.01:
            self._hp_frac = frac
            w = self._hp_max_w
            self._hp_bar_fill.setScale(max(1e-4, frac), 1, 1)
            self._hp_bar_fill.setX(-w / 2 + frac * w / 2)
        # эмоция и иммунитет
        if dead or not emote:
            self.emote_np.hide()
        else:
            label = {"flex": "ФЛЕКС!", "wave": "привет!", "dance": "ТАНЦЫ!"}.get(emote, emote)
            self.emote_tn.setText(label)
            self.emote_np.show()
        rimm = snap.get("rimm", 0.0) > 0
        if rimm:
            self.root.setTransparency(TransparencyAttrib.MAlpha)
            self.root.setAlphaScale(0.35)
        else:
            self.root.clearTransparency()
            self.root.setAlphaScale(1.0)

    def lerp_step(self, dt, speed=15.0):
        """Вызывать каждый кадр: плавное движение + анимация на полном FPS."""
        if self._vis is None or not hasattr(self, "_tgt"):
            return
        a = min(1.0, speed * dt)
        tx, ty, tz, th = self._tgt
        v = self._vis
        v[0] += (tx - v[0]) * a
        v[1] += (ty - v[1]) * a
        v[2] += (tz - v[2]) * a
        dh = th - v[3]
        while dh > 180: dh -= 360
        while dh < -180: dh += 360
        v[3] += dh * a
        self.root.setPos(v[0], v[1], v[2])
        self.root.setH(v[3])
        # анимация сегментов тела на полном FPS (не 30 Гц)
        self.model.update(dt,
                          moving=self._anim_moving,
                          on_ground=self._anim_on_ground,
                          vz=self._anim_vz,
                          emote=self._anim_emote,
                          dead=self._anim_dead)

    def destroy(self):
        self.root.removeNode()


class WorldBar:
    """3D-полоса прогресса над сущностью (билборд): рамка + заполняющаяся часть + подпись.

    Геометрия лежит в плоскости X-Z (ширина по X, высота по Z), тонкая по Y.
    setBillboardPointEye разворачивает её лицом к камере. Заполнение растёт слева.
    """

    def __init__(self, parent, label="", width=2.6, height=0.34,
                 fill_color=(1.0, 0.85, 0.2, 1), font=None):
        self.w = width
        self.root = parent.attachNewNode("worldbar")
        self.root.setBillboardPointEye()
        self.root.setLightOff(1)
        self.root.setTransparency(TransparencyAttrib.MAlpha)
        self.root.setDepthOffset(1)

        frame = make_box(width + 0.14, 0.04, height + 0.14, (0.04, 0.04, 0.05, 0.9))
        frame.reparentTo(self.root)
        frame.setDepthOffset(1)

        empty = make_box(width, 0.04, height, (0.22, 0.22, 0.25, 1))
        empty.reparentTo(self.root)
        empty.setY(-0.01)
        empty.setDepthOffset(2)

        self._fill_color = fill_color
        self.fill = make_box(width, 0.04, height, fill_color)
        self.fill.reparentTo(self.root)
        self.fill.setY(-0.02)
        self.fill.setDepthOffset(3)

        self.tn = TextNode("barlabel")
        if font:
            self.tn.setFont(font)
        self.tn.setAlign(TextNode.ACenter)
        self.tn.setTextColor(1, 1, 1, 1)
        self.tn.setText(label)
        self.label_np = self.root.attachNewNode(self.tn)
        self.label_np.setScale(0.42)
        self.label_np.setPos(0, -0.03, height / 2 + 0.28)
        self.label_np.setDepthOffset(3)
        self.set_fraction(0.0)

    def set_fraction(self, frac):
        f = max(0.0, min(1.0, frac))
        self.fill.setScale(max(1e-4, f), 1, 1)
        self.fill.setX(-self.w / 2 + f * self.w / 2)

    def set_label(self, text):
        self.tn.setText(text)

    def set_fill_color(self, color):
        self.fill.setColor(*color)

    def set_pos(self, x, y, z):
        self.root.setPos(x, y, z)

    def set_scale(self, s):
        self.root.setScale(s)

    def destroy(self):
        self.root.removeNode()


class Roblox2(ShowBase):
    def __init__(self, name, host, port, auth_server=""):
        super().__init__()
        self.player_name = name
        self.host = host
        self.port = port
        self.auth_token = ""           # JWT/token от auth-сервера
        self._auth_server = auth_server or C.AUTH_SERVER_URL.replace("http://", "")
        # загрузить настройки
        settings = self._load_settings()
        self.key_bindings = settings["keybindings"]
        if settings.get("auth_server"):
            self._auth_server = settings["auth_server"]
        self._saved_login    = settings.get("saved_login", "")
        self._saved_password = settings.get("saved_password", "")
        self._music_vol   = float(settings.get("music_vol", 0.5))
        self._sfx_vol     = float(settings.get("sfx_vol",   1.0))
        self._mouse_sens  = float(settings.get("mouse_sens", MOUSE_SENS))
        self.gfx_quality = _GFX_QUALITY  # уже применено в PRC до создания окна
        import random as _rnd
        # рандомный яркий цвет игрока — виден у всех; можно сменить в меню
        self.player_color = [round(_rnd.uniform(0.35, 1.0), 2),
                             round(_rnd.uniform(0.35, 1.0), 2),
                             round(_rnd.uniform(0.35, 1.0), 2)]
        self.my_id = None
        self.net = None
        self.world_built = False         # игровое состояние (HUD/ввод/частицы) построено
        self.world_scene_built = False   # геометрия карты построена (для фона меню тоже)
        self.state = "AUTH"         # AUTH / HUB / COMBAT / PAUSE / SETTINGS / FARM / SHOP
        self.phase = "-"
        self._settings_return = "HUB"
        # keys нужен до _build_game — _setup_game_input вызывается из настроек в меню
        self.keys = {k: False for k in ("forward", "backward", "left", "right", "jump")}
        self._fullscreen = False
        self._music = None          # музыка живёт уже в меню (не только в бою)
        self._music_path = None
        self._menu_cam_t = 0.0      # фаза прокрутки камеры на фоне меню

        self.setBackgroundColor(*SKY[:3])
        if self.gfx_quality != "low":
            self.render.setAntialias(AntialiasAttrib.MMultisample)   # MSAA на всю сцену
        self.disableMouse()
        self.camLens.setFov(85)          # широкий обзор (убираем эффект «зума»)
        self.camLens.setNear(0.2)
        self._go_native_fullscreen()     # по умолчанию - полный экран в родном разрешении
        self._setup_bloom()              # неоновое свечение (постэффект)
        self.default_font = self._load_font()    # системный (дефолт, есть кириллица)
        self.fonts = self._load_role_fonts()     # шрифты по элементам игры
        self.font = self.default_font            # запасной общий

        # карта строится сразу (НЕ подключаясь к серверу) — она же фон главного меню;
        # подключение к серверу происходит только при входе в фазу 1 (start_combat).
        self._build_world_scene()

        # бой
        self.weapon = "syrup"
        self.camera_mode = "first"   # вход от первого лица (C — переключить на 3-е)

        # экраны интерфейса
        self.login_screen    = LoginScreen(self)
        self.register_screen = RegisterScreen(self)
        self.main_menu       = MainMenu(self)
        self.settings_menu   = SettingsMenu(self)
        self.keybindings_screen = KeyBindingsScreen(self)
        self.pause_menu      = PauseMenu(self)
        self.farm_screen = InfoScreen(self, "УЛЕЙ - ФЕРМА (Фаза 3)", [
            "Здесь будут соты, пчёлы и ресурсы:",
            "зелёный сироп, майонез, мёд.",
            "(каркас фазы - экономика в разработке)",
        ])
        self.shop_screen = InfoScreen(self, "МАГАЗИН", [
            "Скины, шляпы и улучшения.",
            "(каркас - товары в разработке)",
        ])

        self.accept("escape", self._on_escape)
        self.taskMgr.add(self.update, "update")
        # Показываем экран входа (AUTH). Если авторизация отключена — сразу HUB.
        if not C.AUTH_ENABLED:
            self._enter_hub()
        elif self._saved_login and self._saved_password:
            # есть сохранённые данные — пробуем войти автоматически
            self._set_menu_blur(True)
            self._play_music(AC.MUSIC_HUB)
            self.taskMgr.doMethodLater(0.05, self._auto_login_task, "auto_login")
        else:
            self.login_screen.show()
            self._set_menu_blur(True)
            self._play_music(AC.MUSIC_HUB)

    # ---------- загрузка/сохранение настроек ----------------------------------------
    def _load_settings(self) -> dict:
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "client_settings.json")
        defaults = {
            "keybindings": dict(DEFAULT_BINDINGS),
            "auth_server": C.AUTH_SERVER_URL.replace("http://", ""),
            "saved_login": "",
            "saved_password": "",
            "music_vol": 0.5,
            "sfx_vol": 1.0,
            "mouse_sens": MOUSE_SENS,
            "gfx_quality": "medium",
        }
        try:
            with open(path, encoding="utf-8") as f:
                saved = _json_mod.load(f)
            if "keybindings" in saved:
                merged = dict(DEFAULT_BINDINGS)
                merged.update(saved["keybindings"])
                saved["keybindings"] = merged
            defaults.update(saved)
        except Exception:
            pass
        return defaults

    def _save_settings(self):
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "client_settings.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                _json_mod.dump({
                    "keybindings": self.key_bindings,
                    "auth_server": self._auth_server,
                    "saved_login": self._saved_login,
                    "saved_password": self._saved_password,
                    "music_vol": self._music_vol,
                    "sfx_vol": self._sfx_vol,
                    "mouse_sens": self._mouse_sens,
                    "gfx_quality": getattr(self, "_pending_gfx_quality", self.gfx_quality),
                }, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # ---------- авторизация --------------------------------------------------------
    def _auto_login_task(self, task):
        """Фоновая попытка автоматического входа с сохранёнными данными."""
        result = _http_post(
            f"http://{self._auth_server}/login",
            {"login": self._saved_login, "password": self._saved_password},
        )
        if result.get("ok"):
            self.auth_token  = result.get("token", "")
            self.player_name = result.get("nick", self._saved_login)
            self.main_menu.set_nick(self.player_name)
            self._enter_hub()
        else:
            # токен устарел или сервер недоступен — показать экран входа
            self.login_screen.show()
        return task.done

    def do_logout(self):
        """Разлогин: стереть сохранённые данные и вернуться на экран входа."""
        self._saved_login = ""
        self._saved_password = ""
        self.auth_token = ""
        self._save_settings()
        self.goto_hub()        # сначала сброс состояния игры
        self._hide_all_screens()
        self.login_screen.show()
        self._set_menu_blur(True)

    def apply_audio_settings(self, music_vol: float, sfx_vol: float):
        """Применить уровни громкости (0.0–1.0) и сохранить."""
        self._music_vol = max(0.0, min(1.0, music_vol))
        self._sfx_vol   = max(0.0, min(1.0, sfx_vol))
        if self._music and hasattr(self._music, "setVolume"):
            self._music.setVolume(self._music_vol)
        # немедленно обновить все играющие loop-звуки
        if hasattr(self, "_worm_step_snd") and self._worm_step_snd:
            self._worm_step_snd.setVolume(0.5 * self._sfx_vol)
        if hasattr(self, "_roach_step_snd") and self._roach_step_snd:
            self._roach_step_snd.setVolume(self._sfx_vol)
        if hasattr(self, "_roach_laugh_snd") and self._roach_laugh_snd:
            self._roach_laugh_snd.setVolume(self._sfx_vol)
        if hasattr(self, "_bee_snd") and self._bee_snd:
            self._bee_snd.setVolume(0.55 * self._sfx_vol)
        self._save_settings()

    def _enter_hub(self):
        """Перейти в хаб после успешной авторизации (или при AUTH_ENABLED=False)."""
        self.state = "HUB"
        self._hide_all_screens()
        self.main_menu.show()
        self._set_menu_blur(True)
        self._play_music(AC.MUSIC_HUB)

    def do_login(self, login: str, password: str, auth_server: str):
        self._auth_server = auth_server.strip()
        url = f"http://{self._auth_server}/login"
        result = _http_post(url, {"login": login, "password": password})
        if result.get("ok"):
            self.auth_token  = result.get("token", "")
            self.player_name = result.get("nick", login)
            self._saved_login    = login
            self._saved_password = password
            self._save_settings()
            self.main_menu.set_nick(self.player_name)
            self._enter_hub()
        else:
            self.login_screen.show_error(result.get("error", "Ошибка подключения к auth-серверу"))

    def do_register(self, login: str, nick: str, password: str, auth_server: str):
        self._auth_server = auth_server.strip()
        url = f"http://{self._auth_server}/register"
        result = _http_post(url, {"login": login, "nick": nick, "password": password})
        if result.get("ok"):
            # автоматический вход после регистрации
            self.do_login(login, password, auth_server)
        else:
            self.register_screen.show_error(result.get("error", "Ошибка регистрации"))

    def open_keybindings(self):
        self.settings_menu.hide()
        self.keybindings_screen.show()

    # ---------- построение игровой сцены (лениво, один раз) ----------
    def _build_game(self):
        if self.world_built:
            return
        self._build_world_scene()   # геометрия карты (уже построена для фона меню)

        self.pos = Vec3(0, -14, 0)   # спавн на площади перед столбом SWAGA
        self.vz = 0.0
        self.heading = 0.0
        self.pitch = 0.0
        self.on_ground = True

        self.keys = {k: False for k in ("forward", "backward", "left", "right", "jump")}
        self.mouse_look = True
        self.chat_active = False

        self.remote = {}
        self.ant_nodes = {}
        self._ant_target = {}        # aid -> [x, y, z]  — цель из снапшота
        self._ant_vis = {}           # aid -> [x, y, z]  — текущая визуальная позиция
        self._ant_prev = {}
        self._ant_immune_prev = {}   # aid -> bool, кэш alpha-состояния
        self.neon_ant_nodes = {}     # nid -> NodePath (синие стрелки)
        self._neon_target = {}       # nid -> [x, y, z, h]
        self._neon_vis = {}          # nid -> [x, y, z, h]
        self._neon_hp_bars = {}      # nid -> WorldBar
        self._neon_immune_prev = {}  # nid -> bool
        self.ant_shot_nodes = {}     # asid -> NodePath (шкибиди-зелье)
        self.neon_alive = 0
        self.shot_nodes = {}
        self.bee_nodes = {}
        self.drop_nodes = {}     # did -> NodePath
        self.boss_shot_nodes = {}  # bsid -> NodePath
        self.slit_nodes = {}       # sid -> NodePath (ЩЕЛЬ)
        self.slit_bars = {}        # sid -> WorldBar (визуальная шкала над щелью)
        self.slit_time = 0.0       # сколько секунд осталось на событие щелей
        self._slit_music_on = False  # играет ли сейчас музыка события щелей
        self._slit_prev_frac = {}    # sid -> прошлая доля заполнения (для звука calm)
        self._slit_calm_snd = None   # звук удовлетворения щели (переигрывается по окончании)
        self._roach_laugh_snd = None  # ржач тараканов во время щели (по окончании предыдущего)
        self.boss_node = None
        self._boss_is_model = False
        self.boss2_node = None
        self._boss2_is_model = False
        self.boss2_bar = None
        self.boss2_info = None
        self.smile_roach_nodes = {}   # sid -> NodePath
        self._smile_immune_prev = {}  # sid -> bool, кэш alpha-состояния
        # ЧЕРВЯЧЕЛЛО КРЫТОЧЕЛЛО
        self.wormchello_info = None
        self._wc_head_node = None     # голова (всегда один узел)
        self._wc_seg_nodes = []       # сегменты тела (список NodePath)
        self.wc_bar = None            # WorldBar HP
        self.worm_shot_nodes = {}     # wsid -> NodePath
        self._wc_hole_nodes = []      # 4 тёмных диска нор (кат-сцена)
        self._wc_lina_nodes = []      # 4 сферы ЛИНА
        self._wc_lina_bars = []       # WorldBar над каждой сферой
        self._prev_wc_hp = 0
        self._wc_roar_cd = 0.0       # кулдаун реплик
        self._wc_pos_interp = [0.0, 0.0, -4.0]   # интерполяция позиции
        self._wc_h_interp = 0.0                   # интерполяция heading
        self._wc_night_alpha = 0.0
        self._wc_lina_pulse_t = 0.0  # таймер пульса сфер
        self._wc_cutscene = False    # идёт ли кат-сцена прямо сейчас
        self._wc_cutscene_t = -1.0   # таймер кат-сцены (<0 = неактивна)
        self._wc_cs_lina_shown = False
        self._wc_cs_holes_shown = False
        self._wc_cs_announced = False
        self._wc_aerial_t = 0.0      # время в AERIAL (для анимации роста)
        self._wc_anim_t = 0.0        # общий таймер процедурных анимаций
        self.bk_boss_node = None
        self._bk_is_model = False
        self.bk_boss_bar = None
        self.bk_minion_nodes = {}   # mid -> NodePath
        self._bkm_target = {}       # mid -> [x, y, z]
        self._bkm_vis = {}          # mid -> [x, y, z]
        # визуальные позиции боссов (для плавного lerp между снапшотами)
        self._boss_vis = None        # [x, y, z, h] или None
        self._boss2_vis = None       # [x, y, z, h] или None
        self._bk_boss_vis = None     # [x, y, z, h] или None
        self.bk_boss_info = None
        self._bk_hit_cd = 0.0
        self._prev_bk_hp = C.BLACK_KING_HP
        # кат-сцена BLACK KING (появление)
        self._bk_cutscene = False
        self._bk_cutscene_t = 0.0
        self._bk_cup_nodes = []     # 4 вращающихся стакана (только в кат-сцене)
        # кат-сцена смерти BLACK KING
        self._bk_death_cs = False   # активна ли кат-сцена смерти
        self._bk_death_t = 0.0      # таймер кат-сцены
        self._bk_death_node = None  # узел модели для погружения в пол
        self._bk_death_pos = (0.0, 0.0)  # позиция гибели
        self._bk_filter_keep = False  # держать фильтр активным после конца кат-сцены (до вспышки)
        self._pending_use_lit = False  # use_lit отправлен, ждём подтверждения сервера
        # анимация погружения при bk_wipe (игроки умерли во время BK)
        self._bk_wipe_sinking = []  # [(NodePath, x, y, z_start)]
        self._bk_wipe_t = 0.0
        # фаза 2 BLACK KING
        self.bk_shot_nodes = {}        # bksid -> NodePath (фиолетовые лазеры)
        self.bk_lc_nodes = {}          # cid -> NodePath (ожившие стаканы)
        self.bk_cup_shot_nodes = {}    # csid -> NodePath (зелёные замедляющие)
        self._bk_syrup_timer = 0.0     # таймер частиц сиропа из угловых стаканов
        self.chat_lines = []
        self._notices = []          # [(node, timer, duration)]
        self._state_accum = 0.0
        self._building_rects = building_rects(pad=0.0)
        self._cam_wall_rects = building_rects(pad=0.4)  # для коллизии камеры
        self._3p_shoot_dir = None  # (fx,fy,fz) — направление стрельбы в 3-м лице
        self.wave = 0
        self.alive_ants = 0
        self.boss_info = None
        self._bosses_alive = 0      # счётчик живых боссов текущей волны
        self._boss_spawn_count = 0  # сколько боссов пришло в этой волне
        self.is_dead = False
        self._respawn_immune = False  # неуязвимость после возрождения (из снапшота)
        self.boss_bar = None       # WorldBar — шкала Уважения над боссом
        self.lit_energy = 0        # запас LIT ENERGY (из снапшота)
        self.bee_time = 0.0        # сколько секунд ещё доступны пчёлы (из снапшота)
        self.player_slow = 0.0     # остаток замедления от газа босса (из снапшота)
        self.cups = 0              # белые стаканы в руках (из снапшота)
        self.cup_spots = [False] * 4   # заняты ли 4 угловых пьедестала
        self.cup_spot_nodes = []   # узлы стаканов на пьедесталах
        self.black_king = False
        self.firing = False        # ЛКМ зажата (струя)
        self._fire_accum = 0.0
        self._spray_start_snd = None
        self._spray_loop_snd = None
        self._spray_loop_task = None

        # звук (музыка инициализируется в __init__ и играет уже в меню)
        self._worm_step_snd = None
        self._roach_step_snd = None
        self._neon_step_snd = None
        self._smile_step_snd = None
        self._bee_snd = None
        self._prev_hp = C.PLAYER_MAX_HP
        self._prev_boss_respect = 0
        self._hurt_cd = 0.0          # антиспам звука урона
        self._boss_hit_cd = 0.0
        self._boss_voice_at = 0.0    # когда следующая реплика босса

        # локальный червь (анимированный — игрок видит и свои анимации тоже)
        _pc = self.player_color
        self.local_worm = WormModel(body_color=(_pc[0], _pc[1], _pc[2], 1))
        self.local_worm.root.reparentTo(self.render)
        # отброс взрывом босса (горизонтальный импульс, затухает) + тряска камеры
        self.knockback = Vec3(0, 0, 0)
        self._shake_amp = 0.0

        # партиклы (струи, смерть тараканов)
        _pmax = {"low": 60, "medium": 100, "high": 150}.get(self.gfx_quality, 150)
        self.particles = ParticleSystem(self.render, max_particles=_pmax)

        self._setup_game_input()
        self._setup_hud()
        self.world_built = True
        # подключение к серверу делает start_combat() через _connect() — НЕ здесь

    def _connect(self):
        """Подключиться к серверу и войти в игру (только при входе в фазу 1)."""
        self.my_id = None
        self._prev_hp = C.PLAYER_MAX_HP
        self._prev_boss_respect = 0
        self.net = NetworkClient(self.host, self.port)
        self.net.start()
        self.net.send({"t": "join", "name": self.player_name,
                       "token": self.auth_token, "color": self.player_color})
        self._play_oneshot(AC.SFX_JOIN_PHASE1)   # звук входа на сервер

    def _disconnect(self):
        """Отключиться от сервера и убрать всех сетевых сущностей со сцены."""
        if self.net:
            self.net.stop()
            self.net = None
        self.my_id = None
        self._clear_entities()

    def _clear_entities(self):
        """Удалить узлы игроков/врагов/снарядов/дропа (после отключения)."""
        if not self.world_built:
            return
        for av in self.remote.values():
            av.destroy()
        self.remote.clear()
        for d in (self.ant_nodes, self.neon_ant_nodes, self.ant_shot_nodes,
                  self.shot_nodes, self.bee_nodes, self.drop_nodes,
                  self.boss_shot_nodes, self.slit_nodes, self.smile_roach_nodes,
                  self.worm_shot_nodes):
            for n in d.values():
                n.removeNode()
            d.clear()
        for bar in self._neon_hp_bars.values():
            bar.destroy()
        self._neon_hp_bars.clear()
        for bar in self.slit_bars.values():
            bar.destroy()
        self.slit_bars.clear()
        self._slit_prev_frac.clear()
        self.slit_time = 0.0
        self._ant_prev.clear()
        if self.boss_node is not None:
            self.boss_node.removeNode()
            self.boss_node = None
        if self.boss_bar is not None:
            self.boss_bar.destroy()
            self.boss_bar = None
        if self.boss2_node is not None:
            self.boss2_node.removeNode()
            self.boss2_node = None
        if self.boss2_bar is not None:
            self.boss2_bar.destroy()
            self.boss2_bar = None
        self._clear_wormchello_nodes()
        if self.bk_boss_node is not None:
            self.bk_boss_node.removeNode()
            self.bk_boss_node = None
        if self.bk_boss_bar is not None:
            self.bk_boss_bar.destroy()
            self.bk_boss_bar = None
        for n in self.bk_minion_nodes.values():
            n.removeNode()
        self.bk_minion_nodes.clear()
        self.bk_boss_info = None
        self._prev_bk_hp = C.BLACK_KING_HP
        self._bk_cutscene = False
        self._bk_cutscene_t = 0.0
        for n in self._bk_cup_nodes:
            n.removeNode()
        self._bk_cup_nodes = []
        for n in self.bk_shot_nodes.values():
            n.removeNode()
        self.bk_shot_nodes.clear()
        for n in self.bk_lc_nodes.values():
            n.removeNode()
        self.bk_lc_nodes.clear()
        for n in self.bk_cup_shot_nodes.values():
            n.removeNode()
        self.bk_cup_shot_nodes.clear()
        if hasattr(self, "_bk_night_overlay") and self._bk_night_overlay:
            self._bk_night_overlay.setColor(0.05, 0.0, 0.12, 0)
            self._bk_night_overlay.hide()
        self._bk_night_alpha = 0.0
        self._bk_filter_keep = False
        if hasattr(self, "_wc_night_overlay") and self._wc_night_overlay:
            self._wc_night_overlay.setColor(0.08, 0.0, 0.18, 0)
            self._wc_night_overlay.hide()
        self._wc_night_alpha = 0.0
        self._wc_cutscene = False
        for n in self.cup_spot_nodes:
            n.removeNode()
        self.cup_spot_nodes = []
        self.cup_spots = [False] * 4
        self.cups = 0
        self.black_king = False
        self.wave = 0
        self.alive_ants = 0
        self.neon_alive = 0
        self.boss_info = None
        self.is_dead = False

    # ---------- переходы между состояниями / фазами ----------
    def _hide_all_screens(self):
        for s in (self.login_screen, self.register_screen, self.main_menu,
                  self.pause_menu, self.settings_menu, self.keybindings_screen,
                  self.farm_screen, self.shop_screen):
            s.hide()

    def start_combat(self):
        if not C.AUTH_ENABLED:
            self.player_name = self.main_menu.get_name()
        self._hide_all_screens()
        self._build_game()
        if self.net is None:             # подключение к серверу — при входе в фазу 1
            self._connect()
        self.state = "COMBAT"
        self.phase = "ТРАВЛЯ"
        self._set_menu_blur(False)       # в бою — чёткая картинка
        self.hud_root.show()
        self._set_mouse_captured(True)
        # музыка по текущей фазе мира (учитываем BLACK KING и босса)
        if self.black_king:
            self._play_music(AC.MUSIC_BLACK_KING)
        elif self.boss_info or self.boss2_info:
            self._play_music(AC.MUSIC_BOSS)
        else:
            self._play_music(AC.MUSIC_PHASE1)

    def resume(self):
        self.pause_menu.hide()
        self.state = "COMBAT"
        self._set_menu_blur(False)       # снять размытие паузы
        self.hud_root.show()
        self._set_mouse_captured(True)

    def pause(self):
        # мультиплеер НЕ останавливаем — мир продолжает жить, просто размываем фон
        self.state = "PAUSE"
        self._set_mouse_captured(False)
        self.firing = False
        self._stop_spray_sound()
        self.chat_active = False
        if hasattr(self, "entry"):
            self.entry.hide()
        self.hud_root.hide()
        self._set_menu_blur(True)        # размыть мир за меню паузы
        self.pause_menu.show()

    def goto_hub(self):
        self._hide_all_screens()
        if self.world_built:
            self.hud_root.hide()
            self.firing = False
            self._stop_spray_sound()
            self._stop_step_loops()
            # остановить все SFX (голоса боссов, щелевые звуки и т.д.)
            for _mgr in getattr(self, 'sfxManagerList', []):
                try: _mgr.stopAllSounds()
                except Exception: pass
            # немедленно скрыть экран смерти и красный эффект урона
            self._death_alpha = 0.0
            self.death_overlay.hide()
            self._hurt_alpha = 0.0
            self._hurt_vignette.hide()
            self._bee_vignette.hide()
            self._bee_vign_t = 0.0
        # мгновенно убрать все уведомления
        for _entry in getattr(self, '_notices', []):
            try: _entry[0].removeNode()
            except Exception: pass
        self._notices = []
        # очистить туториал
        for attr in ("_tut_overlay", "_tut_black"):
            node = getattr(self, attr, None)
            if node:
                try: node.destroy()
                except Exception:
                    try: node.removeNode()
                    except Exception: pass
                setattr(self, attr, None)
        if getattr(self, "_tut_scene_root", None):
            try: self._tut_scene_root.removeNode()
            except Exception: pass
            self._tut_scene_root = None
        if getattr(self, "_arena_root", None):
            self._arena_root.show()
        self._tut_world = None
        self._tut_victory_t = 0.0
        self.my_id = 0
        self.setBackgroundColor(*SKY[:3])
        self._disconnect()               # выход в меню = отключение от сервера
        self.state = "HUB"
        self.phase = "-"
        self._set_mouse_captured(False)
        self._set_menu_blur(True)        # вернуть размытый фон меню
        self._play_music(AC.MUSIC_HUB)   # вернуть музыку меню
        self.main_menu.show()

    # tutorial methods

    def start_tutorial(self):
        self._hide_all_screens()
        self._build_game()
        if hasattr(self, "_arena_root"):
            self._arena_root.hide()
        self._build_tutorial_scene()
        self.setBackgroundColor(0.02, 0.02, 0.04, 1)
        self.state = "TUTORIAL"
        self.phase = "ОБУЧЕНИЕ"
        self._set_menu_blur(False)
        self.hud_root.show()
        self._set_mouse_captured(True)
        self._slit_music_on = False
        self._play_music(AC.MUSIC_TUTORIAL)
        self._tut_init()

    def _build_tutorial_scene(self):
        from panda3d.core import AmbientLight, DirectionalLight, Texture
        W = 4.0; H = 4.5; L = 90.0
        CY = L / 2
        root = self.render.attachNewNode("tut_scene")
        self._tut_scene_root = root
        floor_tex = load_texture(self.loader, AC.BACKROOMS_FLOOR_TEXTURE)
        wall_tex  = load_texture(self.loader, AC.BACKROOMS_WALL_TEXTURE)
        for t in (floor_tex, wall_tex):
            if t:
                t.setWrapU(Texture.WMRepeat); t.setWrapV(Texture.WMRepeat)
        def box(w_, d_, h_, x, y, z, col, tex=None, uv=0.25):
            n = make_box(w_, d_, h_, col, uv_scale=uv)
            n.reparentTo(root); n.setPos(x, y, z)
            if tex: n.setTexture(tex)
            return n
        box(W*2, L, 0.15,  0, CY, -0.075, (0.80, 0.75, 0.50, 1), floor_tex, 0.25)
        box(0.2,  L, H,   -W, CY,  H/2,   (0.85, 0.80, 0.57, 1), wall_tex,  0.25)
        box(0.2,  L, H,    W, CY,  H/2,   (0.85, 0.80, 0.57, 1), wall_tex,  0.25)
        box(W*2, L, 0.15,  0, CY,  H+0.075, (0.60, 0.57, 0.38, 1))
        box(W*2, 0.2, H,   0, -0.1,    H/2, (0.70, 0.65, 0.44, 1))
        box(W*2, 0.2, H,   0, L+0.1,   H/2, (0.50, 0.47, 0.30, 1))
        for iy in range(5, int(L), 10):
            p = box(W*1.1, 1.8, 0.08, 0, iy, H-0.04, (1.0, 0.97, 0.82, 1))
            p.setLightOff(1)
        for side in (-1, 1):
            strip = box(0.08, L, 0.18, side*(W-0.08), CY, 0.09, (0.25, 0.55, 1.0, 1))
            strip.setLightOff(1)
        al = AmbientLight("tut_amb"); al.setColor((0.55, 0.52, 0.38, 1))
        aln = root.attachNewNode(al); root.setLight(aln)
        dl = DirectionalLight("tut_dir"); dl.setColor((0.7, 0.65, 0.48, 1))
        dln = root.attachNewNode(dl); dln.setHpr(10, -55, 0)
        root.setLight(dln)

    def _tut_init(self):
        import time as _time
        from server.world import World
        from direct.gui.DirectGui import DirectFrame, DirectLabel
        self.pos = Vec3(0.0, 2.0, 0.0)
        self.vz = 0.0; self.heading = 0.0; self.pitch = 0.0
        self.on_ground = True; self.weapon = 'syrup'
        self.hp = C.PLAYER_MAX_HP
        self._tut_step = 0; self._tut_timer = 0.0
        self._tut_particle_t = 0.0
        self._tut_last_pos_x = self.pos.x
        self._tut_last_pos_y = self.pos.y
        self._tut_look_start_h = 0.0
        self._tut_ant_was_alive = False
        self._tut_neon_was_alive = False
        self._tut_victory_t = 0.0
        self._tut_kill_pos = [0.0, 28.0, 0.0]
        self._tut_gas_held_t = 0.0
        self._tut_world = World()
        self.my_id = 1
        self._tut_world.add_player(1, 'Tutorial')
        self._tut_world._wave_pending = False
        self._tut_world.next_wave_at = 1e12
        self._tut_world.next_slit_at = 1e12   # запрет авто-спавна щелей
        p = self._tut_world.players[1]
        p.touch_inv_until = _time.time() + 1e9
        if hasattr(self, '_tut_overlay') and self._tut_overlay:
            try: self._tut_overlay.destroy()
            except Exception:
                try: self._tut_overlay.removeNode()
                except Exception: pass
        # градиентная полоса: снизу непрозрачная, сверху прозрачная
        from panda3d.core import PNMImage, CardMaker, PandaNode as _PNode
        grad = PNMImage(4, 64, 4)
        for _y in range(64):
            _a = (_y / 63.0) ** 0.55 * 0.90
            for _x in range(4):
                grad.setXel(_x, _y, 0, 0, 0)
                grad.setAlpha(_x, _y, _a)
        from panda3d.core import Texture as _Tex
        grad_tex = _Tex("tut_grad")
        grad_tex.load(grad)
        grad_tex.setWrapU(_Tex.WMClamp)
        grad_tex.setWrapV(_Tex.WMClamp)
        tut_root = self.aspect2d.attachNewNode(_PNode("tut_ui"))
        cm = CardMaker("tut_bar")
        cm.setFrame(-2.1, 2.1, -1.02, -0.58)
        bar_np = tut_root.attachNewNode(cm.generate())
        bar_np.setTexture(grad_tex)
        bar_np.setTransparency(TransparencyAttrib.MAlpha)
        bar_np.setBin("fixed", 44)
        bar_np.setDepthTest(False); bar_np.setDepthWrite(False)
        from panda3d.core import TextNode as _TN
        self._tut_text_node = _TN("tut_text")
        self._tut_text_node.setAlign(_TN.ACenter)
        self._tut_text_node.setWordwrap(54)
        _f = self.fonts.get('ui')
        if _f: self._tut_text_node.setFont(_f)
        self._tut_text_np = tut_root.attachNewNode(self._tut_text_node)
        self._tut_text_np.setScale(0.078)
        self._tut_text_np.setPos(0, 0, -0.83)
        self._tut_text_np.setColorScale(1, 1, 0.65, 1)
        self._tut_text_np.setBin("fixed", 45)
        self._tut_text_np.setDepthTest(False); self._tut_text_np.setDepthWrite(False)
        self._tut_overlay = tut_root
        self._tut_black = DirectFrame(
            frameColor=(0, 0, 0, 0), frameSize=(-2, 2, -2, 2),
            pos=(0, 0, 0), parent=self.aspect2d, sortOrder=100,
        )
        self._tut_black.hide()
        self._tut_steps = [
            ('walk',       'Иди вперёд по коридору! WASD — движение, мышь — обзор.'),
            ('gas',        'Удерживай Shift — активируй ГАЗ и беги в два раза быстрее!'),
            ('look',       'Теперь оглянись назад — осмотрись вокруг.'),
            ('ant',        'ТАРАКАН! Зажми ЛКМ — стреляй сиропом [1]!'),
            ('pickup_lit', 'Подбери LIT ENERGY — подойди к светящемуся предмету!'),
            ('neon',       'СИНИЙ СТРЕЛОК! Нажми [3] — активируй пчёл, затем ЛКМ!'),
            ('pickup_heal','Отлично! Подбери аптечку.'),
            ('mayo',       'ЩЕЛЬ на стене! Нажми [2] — выбери МАЙОНЕЗ.'),
            ('slit',       'Зажми ЛКМ рядом со ЩЕЛЬЮ — заливай её майонезом!'),
        ]
        self._tut_set_step(0)

    def _tut_set_step(self, idx):
        import time as _time
        from server.world import Ant, NeonAnt, Slit
        self._tut_step = idx
        if idx >= len(self._tut_steps):
            return
        self._tut_text_node.setText(self._tut_steps[idx][1])
        w = self._tut_world; now = _time.time()
        step_key = self._tut_steps[idx][0]
        if step_key == 'look':
            self._tut_look_start_h = self.heading
        elif step_key == 'ant':
            # один таракан прямо перед игроком в коридоре
            spawn_y = max(self.pos.y + 12, 22.0)
            aid = w._next_ant_id; w._next_ant_id += 1
            a = Ant(aid, (0.0, spawn_y)); w.ants[aid] = a
            self._tut_ant_was_alive = True
            self._play_oneshot(AC.SFX_COCKROACH_STEP, volume=0.5)
        elif step_key == 'neon':
            # один синий стрелок чуть дальше по коридору
            spawn_y = max(self.pos.y + 14, 36.0)
            nid = w._next_neon_id; w._next_neon_id += 1
            na = NeonAnt(nid, now); na.pos = [0.0, spawn_y, 0.0]; w.neon_ants[nid] = na
            self._tut_neon_was_alive = True
        elif step_key == 'slit':
            sid = w._next_slit_id; w._next_slit_id += 1
            sl = Slit(sid, [3.8, 52.0, C.PLAYER_HEIGHT * 0.5], [-1.0, 0.0])
            w.slits[sid] = sl
            w.slit_event_active = True
            w.slit_deadline = now + 3600.0
            w.events.append({'t': 'event', 'kind': 'slit_spawn', 'count': 1, 'time': 30.0})
            self._play_oneshot(AC.SFX_SLIT_SPAWN, volume=1.0)

    def _tut_build_snapshot(self):
        import time as _time
        w = self._tut_world; now = _time.time()
        pl = w.players.get(1)
        return {
            'players':    {'1': pl.snapshot()} if pl else {},
            'ants':       [a.snapshot() for a in w.ants.values()],
            'neon_ants':  [na.snapshot() for na in w.neon_ants.values()],
            'ant_shots':  [s.snapshot() for s in w.ant_shots.values()],
            'shots':      [s.snapshot() for s in w.shots.values()],
            'bees':       [b.snapshot() for b in w.bees.values()],
            'drops':      [[did, d['pos'][0], d['pos'][1], d['kind']]
                           for did, d in w.drops.items()],
            'boss':       None,
            'bshots':     [],
            'slits':      [s.snapshot() for s in w.slits.values()],
            'slit_time':  round(max(0, w.slit_deadline - now), 1)
                          if w.slit_event_active else 0.0,
            'wave': 0, 'alive': len(w.ants), 'neon': len(w.neon_ants),
            'cup_spots': [False]*4, 'black_king': False,
            'bk_boss': None, 'bk_minions': [], 'bk_shots': [],
            'bk_living_cups': [], 'bk_cup_shots': [],
        }

    def _tut_update(self, dt):
        if self.state != 'TUTORIAL' or not hasattr(self, '_tut_world'):
            return
        import time as _time
        if self._tut_victory_t > 0:
            self._tut_victory_t -= dt
            alpha = min(1.0, 1.0 - self._tut_victory_t / 1.2)
            self._tut_black['frameColor'] = (0, 0, 0, alpha)
            if self._tut_victory_t <= 0:
                self.goto_hub()
            return
        # коридор: клэмп позиции игрока внутри стен (W=4.0, L=90.0)
        self.pos.x = max(-3.7, min(3.7, self.pos.x))
        self.pos.y = max(0.1, min(89.5, self.pos.y))
        w = self._tut_world
        self._tut_particle_t += dt
        if self._tut_particle_t > 0.10:
            self._tut_particle_t = 0.0
            import random as _r
            for side in (-3.5, 3.5):
                self.particles.burst(
                    [side, self.pos.y + _r.uniform(-4, 22), _r.uniform(0.3, 4.0)],
                    count=2, color=(0.22, 0.52, 1.0, 1), speed=0.35,
                    size=0.10, life=2.8, grav=0.0, spread=0.18, up=0.0,
                    vel_add=((-0.55 if side > 0 else 0.55), 0.0, 0.14),
                )
        w.set_state(1, [self.pos.x, self.pos.y, self.pos.z], self.heading, self.pitch)
        self._tut_timer += dt
        w.update(dt)
        # восстановить инварианты — wipe/волны не должны появляться
        w._wave_pending = False
        w.next_wave_at = 1e12
        w.next_slit_at = 1e12
        pl = w.players.get(1)
        if pl:
            pl.dead = False
            pl.hp = C.PLAYER_MAX_HP
            pl.touch_inv_until = _time.time() + 1e9
        # клэмп врагов внутри коридора
        for a in w.ants.values():
            a.pos[0] = max(-3.5, min(3.5, a.pos[0]))
            a.pos[1] = max(0.5, min(89.0, a.pos[1]))
        for na in w.neon_ants.values():
            na.pos[0] = max(-3.5, min(3.5, na.pos[0]))
            na.pos[1] = max(0.5, min(89.0, na.pos[1]))
        for ev in w.events:
            kind = ev.get('kind')
            if kind == 'ant_killed':
                self._play_oneshot(AC.SFX_COCKROACH_DEATH, volume=0.8)
                p2 = ev.get('pos', [0, 28])
                pos = [p2[0], p2[1], 0.5]
                self._tut_kill_pos = pos[:]
                self.particles.burst(pos, count=12, color=(0.9, 0.5, 0.0, 1),
                    speed=4.0, size=0.25, life=0.7, grav=-5.0, spread=1.2, up=0.5)
            elif kind == 'neon_ant_killed':
                self._play_oneshot(AC.SFX_COCKROACH_DEATH, volume=0.9)
                p2 = ev.get('pos', [0, 44])
                pos = [p2[0], p2[1], 0.5]
                self._tut_kill_pos = pos[:]
                self.particles.burst(pos, count=14, color=(0.3, 0.7, 1.0, 1),
                    speed=4.5, size=0.22, life=0.8, grav=-4.0, spread=1.1, up=0.6)
            elif kind == 'slit_calmed':
                self._play_oneshot(AC.SFX_SLIT_CALM, volume=1.0)
            elif kind == 'slit_defeated':
                self._play_oneshot(AC.SFX_SLIT_DEFEATED, volume=1.0)
                self._flash_screen()
                self._shake(0.18)
                self._tut_overlay.hide()
                self._tut_black.show()
                self._tut_black['frameColor'] = (0, 0, 0, 0)
                self._tut_victory_t = 1.6
                w.events.clear()
                return
            elif kind == 'pickup':
                if ev.get('drop') != 'lit_energy':
                    self._play_oneshot(AC.SFX_PICKUP, volume=1.0)
        w.events.clear()
        step_key = (self._tut_steps[self._tut_step][0]
                    if self._tut_step < len(self._tut_steps) else '_done')
        if self._tut_ant_was_alive and not w.ants:
            self._tut_ant_was_alive = False
            w.drops.clear()  # убрать случайные дропы сервера
            did = w._next_drop_id; w._next_drop_id += 1
            w.drops[did] = {'pos': list(self._tut_kill_pos), 'kind': 'lit_energy'}
        if self._tut_neon_was_alive and not w.neon_ants:
            self._tut_neon_was_alive = False
            w.drops.clear()  # убрать случайные дропы сервера
            did = w._next_drop_id; w._next_drop_id += 1
            w.drops[did] = {'pos': list(self._tut_kill_pos), 'kind': 'health'}
        snap = self._tut_build_snapshot()
        self._apply_snapshot(snap)
        moved = math.hypot(self.pos.x - self._tut_last_pos_x,
                           self.pos.y - self._tut_last_pos_y)
        self._tut_last_pos_x = self.pos.x
        self._tut_last_pos_y = self.pos.y
        h_delta = abs(((self.heading - self._tut_look_start_h) + 180) % 360 - 180)
        pl = w.players.get(1)
        player_lit = (pl.lit_energy if pl else 0)
        if step_key == 'walk' and self.pos.y > 14 and moved > 0.01:
            self._tut_next()
        elif step_key == 'gas':
            if self.keys.get("gas", False):
                self._tut_gas_held_t += dt
                if self._tut_gas_held_t >= 1.2:
                    self._tut_next()
            else:
                self._tut_gas_held_t = 0.0
        elif step_key == 'look' and h_delta > 80:
            self._tut_next()
        elif step_key == 'ant' and not w.ants and not self._tut_ant_was_alive:
            self._tut_next()
        elif step_key == 'pickup_lit' and (player_lit > 0 or self.bee_time > 0):
            self._tut_next()
        elif step_key == 'neon' and not w.neon_ants and not self._tut_neon_was_alive:
            self._tut_next()
        elif step_key == 'pickup_heal' and not w.drops and self._tut_timer > 0.5:
            self._tut_next()
        elif step_key == 'mayo' and self.weapon == 'mayo':
            self._tut_next()

    def _tut_next(self):
        self._tut_timer = 0.0
        self._play_oneshot(AC.SFX_TUT_STEP, volume=0.85)
        next_idx = self._tut_step + 1
        if next_idx < len(self._tut_steps):
            self._tut_set_step(next_idx)

    def goto_farm(self):
        self._hide_all_screens()
        self.state = "FARM"
        self.farm_screen.show()

    def goto_shop(self):
        self._hide_all_screens()
        self.state = "SHOP"
        self.shop_screen.show()

    def open_settings(self):
        self._settings_return = self.state
        self.main_menu.hide()
        self.pause_menu.hide()
        self.keybindings_screen.hide()
        self.state = "SETTINGS"
        self.settings_menu.show()

    def close_settings(self):
        self.settings_menu.hide()
        self.keybindings_screen.hide()
        if self._settings_return == "PAUSE":
            self.state = "PAUSE"
            self.pause_menu.show()
        else:
            self.state = "HUB"
            self.main_menu.show()

    def apply_video_settings(self, w, h, fullscreen):
        self._fullscreen = fullscreen
        if not hasattr(self.win, "requestProperties"):
            return
        props = WindowProperties()
        props.setFullscreen(False)
        props.setUndecorated(fullscreen)
        if fullscreen:
            props.setOrigin(0, 0)
        props.setSize(w, h)
        self.win.requestProperties(props)

    def set_gfx_quality(self, quality: str):
        """Сохранить качество графики в файл настроек (применится после перезапуска)."""
        self._pending_gfx_quality = quality
        self._save_settings()

    def quit_game(self):
        if self.net:
            self.net.stop()
        self.userExit()

    # ---------- окно / постэффекты ----------
    def _go_native_fullscreen(self):
        # безрамочное окно = OBS-совместимый «полный экран» (не эксклюзивный режим)
        from panda3d.core import GraphicsWindow
        if not isinstance(self.win, GraphicsWindow):
            return
        try:
            w = self.pipe.getDisplayWidth()
            h = self.pipe.getDisplayHeight()
            if w <= 0 or h <= 0:
                return
            props = WindowProperties()
            props.setFullscreen(False)
            props.setUndecorated(True)
            props.setOrigin(0, 0)
            props.setSize(w, h)
            self.win.requestProperties(props)
            self._fullscreen = True
        except Exception:
            pass

    def _setup_bloom(self):
        if self.gfx_quality == "low":
            self.filters = None
            return
        # неоновое свечение: bloom по ярким (full-bright) неон-элементам
        try:
            self.filters = CommonFilters(self.win, self.cam)
            if self.gfx_quality == "medium":
                self.filters.setBloom(blend=(0.3, 0.4, 0.3, 0.0), mintrigger=0.6,
                                      maxtrigger=1.0, desat=0.05, intensity=1.0, size="small")
            else:
                self.filters.setBloom(blend=(0.3, 0.4, 0.3, 0.0), mintrigger=0.55,
                                      maxtrigger=1.0, desat=0.1, intensity=1.5, size="medium")
        except Exception:
            self.filters = None

    def _set_menu_blur(self, on):
        if self.gfx_quality == "low" or not self.filters:
            return
        # лёгкое размытие 3D-сцены за меню (на GUI/aspect2d не влияет)
        try:
            self.filters.setBlurSharpen(0.62 if on else 1.0)  # <1 = размытие, 1 = чётко
        except Exception:
            pass

    def _shake(self, amp):
        """Тряхнуть камеру (взрыв/победа). Амплитуда затухает в _apply_camera."""
        self._shake_amp = max(getattr(self, "_shake_amp", 0.0), amp)

    def _flash_screen(self, color=(1, 1, 1, 1), duration=1.6, hold=0.35):
        """Ослепляющая вспышка на весь экран: держит полную яркость `hold` секунд,
        затем плавно (ease-out) гаснет за оставшееся время. Поверх всего GUI."""
        cm = CardMaker("flash")
        cm.setFrameFullscreenQuad()
        np = self.render2d.attachNewNode(cm.generate())
        np.setTransparency(TransparencyAttrib.MAlpha)
        np.setColor(*color)
        np.setBin("fixed", 1000)
        np.setDepthTest(False)
        np.setDepthWrite(False)
        st = {"t": 0.0}
        fade = max(0.01, duration - hold)

        def _fade(task):
            st["t"] += globalClock.getDt()
            if st["t"] <= hold:
                k = 1.0
            else:
                k = max(0.0, 1.0 - (st["t"] - hold) / fade) ** 0.6   # дольше держит яркость
            np.setColor(color[0], color[1], color[2], color[3] * k)
            if st["t"] >= duration:
                np.removeNode()
                return task.done
            return task.cont

        self.taskMgr.add(_fade, "flash_fade")

    def _make_vignette_texture(self, color, size=128):
        """Текстура-вигнет: прозрачный центр, цветное свечение по краям экрана."""
        from panda3d.core import PNMImage, Texture
        img = PNMImage(size, size)
        img.addAlpha()
        r, g, b = color[0], color[1], color[2]
        for y in range(size):
            for x in range(size):
                u = abs(x / (size - 1) * 2 - 1)
                v = abs(y / (size - 1) * 2 - 1)
                edge = max(u, v)                       # квадратный вигнет (по краям)
                a = max(0.0, (edge - 0.55) / 0.45) ** 1.5
                img.setXel(x, y, r, g, b)
                img.setAlpha(x, y, min(1.0, a))
        tex = Texture("vignette")
        tex.load(img)
        return tex

    def _update_overlays(self, dt):
        # плавное затемнение при смерти
        target = 0.72 if self.is_dead else 0.0
        self._death_alpha += (target - self._death_alpha) * min(1.0, 4.0 * dt)
        if self._death_alpha > 0.01:
            self.death_overlay.show()
            self.death_overlay.setColor(0, 0, 0, self._death_alpha)
            self.death_node.setText("ВЫ ПОГИБЛИ\nреспаун на спавне...")
            self.death_node.setTextColor(1.0, 0.3, 0.4, min(1.0, self._death_alpha / 0.6))
        else:
            self.death_overlay.hide()
        # зеленоватый вигнет в зоне газа папани
        vt = 1.0 if self.player_slow > 0 else 0.0
        self._vign_alpha += (vt - self._vign_alpha) * min(1.0, 6.0 * dt)
        if self._vign_alpha > 0.01:
            self.vignette.show()
            self.vignette.setColor(1, 1, 1, min(0.65, self._vign_alpha))
        else:
            self.vignette.hide()
        # красный вигнет по краям при уроне
        self._hurt_alpha = max(0.0, self._hurt_alpha - dt * 2.8)
        if self._hurt_alpha > 0.01:
            self._hurt_vignette.show()
            self._hurt_vignette.setColor(1, 1, 1, self._hurt_alpha)
        else:
            self._hurt_vignette.hide()
        # голубой пульсирующий вигнет + гул пчёл пока активен LIT ENERGY
        if self.bee_time > 0:
            self._bee_vign_t += dt
            pulse = 0.22 + 0.10 * math.sin(self._bee_vign_t * 3.5)
            self._bee_vignette.show()
            self._bee_vignette.setColor(1, 1, 1, pulse)
            self._set_loop("_bee_snd", AC.SFX_BEE_LOOP, True)
            if self._bee_snd:
                self._bee_snd.setVolume(0.55 * self._sfx_vol)
        else:
            self._bee_vignette.hide()
            self._bee_vign_t = 0.0
            self._set_loop("_bee_snd", AC.SFX_BEE_LOOP, False)

    def _apply_blast_knockback(self, pos):
        """Отброс ЛОКАЛЬНОГО игрока от взрыва босса (игрок авторитетен над позицией)."""
        if not self.world_built or self.is_dead:
            return
        dx = self.pos.x - pos[0]
        dy = self.pos.y - pos[1]
        d = math.hypot(dx, dy)
        r = C.BOSS_EXPLOSION_RADIUS
        if d >= r:
            return
        f = C.BOSS_KNOCKBACK * (1.0 - d / r)
        if d > 0.01:
            ux, uy = dx / d, dy / d
        else:
            import random
            ang = random.uniform(0, 2 * math.pi)
            ux, uy = math.cos(ang), math.sin(ang)
        self.knockback += Vec3(ux * f, uy * f, 0)
        self.vz = max(self.vz, f * 0.7)     # подкидывает вверх сильнее
        self.on_ground = False
        self._shake(min(0.7, f * 0.05))

    # ---------- ресурсы ----------
    def _load_font(self):
        import os
        from panda3d.core import Filename
        for path in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf",
                     r"C:\Windows\Fonts\tahoma.ttf", r"C:\Windows\Fonts\calibri.ttf"):
            if not os.path.exists(path):
                continue
            try:
                f = self.loader.loadFont(str(Filename.fromOsSpecific(path)))
            except Exception:
                continue
            if f and f.isValid():
                f.setPixelsPerUnit(64)
                return f
        return None  # запасной вариант - встроенный шрифт (без кириллицы)

    def _load_role_fonts(self):
        roles = {
            "title": AC.FONT_TITLE, "ui": AC.FONT_UI, "hud": AC.FONT_HUD,
            "chat": AC.FONT_CHAT, "world": AC.FONT_WORLD,
        }
        return {r: (load_font(self.loader, p) or self.default_font)
                for r, p in roles.items()}

    def _font(self, tn, role="hud"):
        f = self.fonts.get(role) or self.default_font
        if f:
            tn.setFont(f)
        return tn

    # ---------- сцена ----------
    def _setup_lights(self):
        # backrooms: ровный тёплый флуоресцентный свет (жёлтый ambient + мягкий сверху)
        amb = AmbientLight("amb")
        amb.setColor((0.62, 0.56, 0.40, 1))
        self.render.setLight(self.render.attachNewNode(amb))
        ceil = DirectionalLight("ceil")
        ceil.setColor((0.34, 0.31, 0.24, 1))
        cnp = self.render.attachNewNode(ceil)
        cnp.setHpr(-20, -80, 0)        # почти отвесно сверху (как от ламп на потолке)
        self.render.setLight(cnp)

    def _build_world(self):
        self._arena_root = self.render.attachNewNode("arena_root")
        build_city(self._arena_root, self.loader)
        build_spawn_pillar(self._arena_root, self.loader, self.font)

    def _build_world_scene(self):
        """Построить геометрию карты (свет + город). Без сети — годится и для фона меню."""
        if self.world_scene_built:
            return
        self._setup_lights()
        self._build_world()
        self.world_scene_built = True

    def _update_menu_background(self, dt):
        """Медленно прокручивать камеру над картой — живой фон главного меню."""
        if not self.world_scene_built or self.state != "HUB":
            return
        self._menu_cam_t += dt * 0.05
        a = self._menu_cam_t
        r = 30.0
        self.camera.setPos(math.cos(a) * r, math.sin(a) * r, 17.0)
        self.camera.lookAt(0, 0, 4.5)

    # ---------- ввод ----------
    def _setup_game_input(self):
        """Регистрирует обработчики ввода по текущим key_bindings. Можно вызывать повторно."""
        kb = self.key_bindings
        # снимаем ВСЕ ранее зарегистрированные клавиши:
        # и дефолтные, и любые нестандартные из прошлых биндингов
        _old = set(getattr(self, "_bound_keys", []))
        _new = set(kb.values())
        for k in _old | _new | {"w","a","s","d","space","lshift","rshift","shift",
                                  "q","r","c","f","g","v","enter","1","2","3"}:
            self.ignore(k)
            self.ignore(f"{k}-up")
        self._bound_keys = list(_new)

        def _bind_move(action):
            key = kb.get(action, "")
            if key:
                self.accept(key,              self._set_key, [action, True])
                self.accept(f"{key}-up",      self._set_key, [action, False])
                # Panda3D добавляет "shift-" к клавишам пока удерживается Shift
                self.accept(f"shift-{key}",     self._set_key, [action, True])
                self.accept(f"shift-{key}-up",  self._set_key, [action, False])

        _bind_move("forward"); _bind_move("backward")
        _bind_move("left");    _bind_move("right")
        _bind_move("jump")

        self.accept("mouse1",          self._on_fire_down)
        self.accept("mouse1-up",       self._on_fire_up)
        self.accept("shift-mouse1",    self._on_fire_down)   # Shift зажат — стрельба не блокируется
        self.accept("shift-mouse1-up", self._on_fire_up)
        w1 = kb.get("weapon1", "1"); w2 = kb.get("weapon2", "2"); w3 = kb.get("weapon3", "3")
        self.accept(w1,          self._set_weapon, ["syrup"])
        self.accept(w2,          self._set_weapon, ["mayo"])
        self.accept(w3,          self._set_weapon, ["hive"])
        self.accept(f"shift-{w1}", self._set_weapon, ["syrup"])  # Shift зажат — смена оружия
        self.accept(f"shift-{w2}", self._set_weapon, ["mayo"])
        self.accept(f"shift-{w3}", self._set_weapon, ["hive"])
        gas_key = kb.get("gas", "lshift")
        self.accept(gas_key,          self._set_key, ["gas", True])
        self.accept(gas_key + "-up",  self._set_key, ["gas", False])

        def _cycle_weapon(step):
            _weapons = ["syrup", "mayo", "hive"]
            cur = self.weapon if self.weapon in _weapons else "syrup"
            idx = _weapons.index(cur)
            # пропустить hive если нет LIT ENERGY и пчёлы не активны
            for _ in range(len(_weapons)):
                idx = (idx + step) % len(_weapons)
                nxt = _weapons[idx]
                if nxt != "hive" or self.bee_time > 0 or self.lit_energy > 0:
                    break
            self._set_weapon(_weapons[idx])

        self.accept("wheel_up",         lambda: _cycle_weapon(-1))
        self.accept("wheel_down",       lambda: _cycle_weapon(+1))
        self.accept("shift-wheel_up",   lambda: _cycle_weapon(-1))
        self.accept("shift-wheel_down", lambda: _cycle_weapon(+1))

        self.accept(kb.get("ult",  "q"),      self._ultimate)
        self.accept(kb.get("place_cup", "r"), self._place_cup)
        self.accept(kb.get("camera", "c"),    self._toggle_camera)
        # читы для GODBLESSER (не в настройках управления)
        self.accept("9", self._god_toggle)
        self.accept("8", self._god_lit_energy)
        self.accept("7", self._god_wave11)
        self.accept(kb.get("emote1", "f"), lambda: self._emote("flex"))
        self.accept(kb.get("emote2", "g"), lambda: self._emote("dance"))
        self.accept(kb.get("emote3", "v"), lambda: self._emote("wave"))
        self.accept(kb.get("chat", "enter"), self._toggle_chat)
        # оконные горячие клавиши (всегда)
        self.accept("alt-enter", self._toggle_fullscreen)
        self.accept("control-z", self._minimize)

    def _set_key(self, k, v):
        self.keys[k] = v

    # ---------- окно ----------
    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        props = WindowProperties()
        props.setFullscreen(False)
        if self._fullscreen:
            di = self.pipe.getDisplayInformation()
            w = di.getDisplayModeWidth(0) if (di and di.getTotalDisplayModes() > 0) else self.pipe.getDisplayWidth()
            h = di.getDisplayModeHeight(0) if (di and di.getTotalDisplayModes() > 0) else self.pipe.getDisplayHeight()
            props.setUndecorated(True)
            props.setOrigin(0, 0)
            props.setSize(w, h)
        else:
            props.setUndecorated(False)
            props.setSize(1280, 720)
        self.win.requestProperties(props)

    def _minimize(self):
        props = WindowProperties()
        props.setMinimized(True)
        self.win.requestProperties(props)

    def _on_escape(self):
        if self.state == "COMBAT":
            if self.chat_active:
                self._close_chat()
            else:
                self.pause()
        elif self.state == "SETTINGS":
            self.close_settings()
        elif self.state in ("FARM", "SHOP", "TUTORIAL"):
            self.goto_hub()
        elif self.state == "PAUSE":
            self.resume()
        # из HUB по Esc не выходим - выход через кнопку «Выход»

    def _set_mouse_captured(self, captured):
        if hasattr(self.win, "requestProperties"):
            props = WindowProperties()
            props.setCursorHidden(captured)
            props.setMouseMode(WindowProperties.M_absolute)
            self.win.requestProperties(props)
        self.mouse_look = captured
        if captured:
            self._recenter_mouse()

    # ---------- HUD / чат ----------
    def _hud_text(self, name, x, z, scale, align, color, card=0.0):
        tn = self._font(TextNode(name))
        tn.setAlign(align)
        tn.setTextColor(*color)
        if card:
            tn.setCardColor(0, 0, 0, card)
            tn.setCardAsMargin(0.3, 0.3, 0.2, 0.2)
        np = self.hud_root.attachNewNode(tn)
        np.setScale(scale)
        np.setPos(x, 0, z)
        return tn

    def _hud_icon(self, x, z, color, size=0.038):
        cm = CardMaker("hudicon")
        cm.setFrame(-1, 1, -1, 1)
        np = self.hud_root.attachNewNode(cm.generate())
        np.setTransparency(TransparencyAttrib.MAlpha)
        np.setColor(*color)
        np.setScale(size)
        np.setPos(x, 0, z)
        return np

    def _setup_hud(self):
        self.hud_root = self.aspect2d.attachNewNode("hud_root")

        # прицел (центр)
        self.crosshair = self._font(TextNode("cross"))
        self.crosshair.setText("+")
        self.crosshair.setAlign(TextNode.ACenter)
        self.crosshair.setTextColor(1, 1, 1, 0.9)
        self.hud_root.attachNewNode(self.crosshair).setScale(0.08)

        # метка фазы (верх-центр) + предупреждение о щелях под ней
        self.phase_node = self._hud_text("phase", 0, 0.92, 0.05, TextNode.ACenter,
                                         (0.55, 1.0, 1.0, 1), card=0.4)
        self.slit_node = self._hud_text("slit", 0, 0.80, 0.058, TextNode.ACenter,
                                        (1.0, 0.45, 0.55, 1), card=0.45)

        # HP — крупно, низ-слева, с красной иконкой
        self._hud_icon(-1.24, -0.86, (0.95, 0.25, 0.25, 1), 0.05)
        self.hp_node = self._hud_text("hp", -1.17, -0.875, 0.072, TextNode.ALeft,
                                      (1, 1, 1, 1))

        # Очки/смерти — верх-слева
        self._hud_icon(-1.28, 0.9, (1.0, 0.85, 0.3, 1))
        self.score_node = self._hud_text("score", -1.21, 0.885, 0.05, TextNode.ALeft,
                                         (0.96, 0.93, 0.82, 1))

        # Онлайн — верх-справа
        self.online_node = self._hud_text("online", 1.28, 0.885, 0.045, TextNode.ARight,
                                          (0.7, 0.9, 1.0, 1))

        # Иконка текущего оружия — одна большая карточка, низ-справа
        _wix, _wiz = 1.21, -0.80
        self._w_icon_bg = self._hud_icon(_wix, _wiz + 0.03, (0.1, 0.1, 0.1, 0.65), size=0.095)
        self._w_icon_textures = {
            "syrup": load_texture(self.loader, AC.ICON_SYRUP_TEXTURE),
            "mayo":  load_texture(self.loader, AC.ICON_MAYONEZ_TEXTURE),
            "hive":  load_texture(self.loader, AC.ICON_HONEY_TEXTURE),
        }
        self._w_icon_colors = {
            "syrup": (0.35, 1.0,  0.45, 1),
            "mayo":  (0.97, 0.97, 0.78, 1),
            "hive":  (1.0,  0.75, 0.1,  1),
        }
        self._w_label   = self._hud_text("w_name", _wix, _wiz - 0.120, 0.052,
                                         TextNode.ACenter, (1, 1, 1, 1))
        self._w_key_node = self._hud_text("w_key",  _wix, _wiz + 0.115, 0.030,
                                          TextNode.ACenter, (0.6, 0.6, 0.6, 1))
        self._w_prev = None
        # вспомогательный текст: LIT ENERGY / таймер / стаканы
        self.weapon_node = self._hud_text("weapon_extra", 1.28, -0.96, 0.038,
                                          TextNode.ARight, (1, 1, 1, 1))
        # центральная подсказка: поставить стакан (появляется рядом с прицелом)
        self.cup_hint_node = self._hud_text("cup_hint", 0, -0.18, 0.048,
                                            TextNode.ACenter, (1.0, 0.9, 0.4, 1), card=0.38)

        self.chat_node = self._hud_text("chat", -1.3, -0.45, 0.042, TextNode.ALeft,
                                        (1, 1, 1, 1), card=0.30)
        # подсказка управления убрана из HUD — настраивается в Настройки -> Управление

        # затемнение экрана при смерти (поверх всего) + текст
        cm = CardMaker("deathdark")
        cm.setFrameFullscreenQuad()
        self.death_overlay = self.render2d.attachNewNode(cm.generate())
        self.death_overlay.setTransparency(TransparencyAttrib.MAlpha)
        self.death_overlay.setColor(0, 0, 0, 0)
        self.death_overlay.setBin("fixed", 50)
        self.death_overlay.setDepthTest(False)
        self.death_overlay.setDepthWrite(False)
        self.death_overlay.hide()
        self.death_node = self._font(TextNode("death"))
        self.death_node.setAlign(TextNode.ACenter)
        self.death_node.setTextColor(1.0, 0.3, 0.4, 1)
        dnp = self.death_overlay.attachNewNode(self.death_node)
        dnp.setScale(0.10)
        dnp.setBin("fixed", 51)
        self._death_alpha = 0.0

        # тёмно-фиолетовый ночной фильтр всего экрана (фаза BLACK KING)
        self._bk_night_alpha = 0.0
        cm_bk = CardMaker("bk_night")
        cm_bk.setFrameFullscreenQuad()
        self._bk_night_overlay = self.render2d.attachNewNode(cm_bk.generate())
        self._bk_night_overlay.setTransparency(TransparencyAttrib.MAlpha)
        self._bk_night_overlay.setColor(0.05, 0.0, 0.12, 0)
        self._bk_night_overlay.setBin("fixed", 20)   # под оверлеями смерти/вспышки
        self._bk_night_overlay.setDepthTest(False)
        self._bk_night_overlay.setDepthWrite(False)
        self._bk_night_overlay.hide()

        # тёмно-фиолетовый фильтр Червячелло (немного другой оттенок — глубже)
        self._wc_night_alpha = 0.0
        cm_wc = CardMaker("wc_night")
        cm_wc.setFrameFullscreenQuad()
        self._wc_night_overlay = self.render2d.attachNewNode(cm_wc.generate())
        self._wc_night_overlay.setTransparency(TransparencyAttrib.MAlpha)
        self._wc_night_overlay.setColor(0.08, 0.0, 0.18, 0)
        self._wc_night_overlay.setBin("fixed", 18)   # под BK фильтром
        self._wc_night_overlay.setDepthTest(False)
        self._wc_night_overlay.setDepthWrite(False)
        self._wc_night_overlay.hide()

        # зеленоватый вигнет по краям при замедлении газом папани
        self._vign_alpha = 0.0
        vt = self._make_vignette_texture((0.35, 0.95, 0.4))
        cm2 = CardMaker("vign")
        cm2.setFrameFullscreenQuad()
        self.vignette = self.render2d.attachNewNode(cm2.generate())
        self.vignette.setTexture(vt)
        self.vignette.setTransparency(TransparencyAttrib.MAlpha)
        self.vignette.setColor(1, 1, 1, 0)
        self.vignette.setBin("fixed", 40)
        self.vignette.setDepthTest(False)
        self.vignette.setDepthWrite(False)
        self.vignette.hide()

        # красный вигнет по краям при получении урона
        self._hurt_alpha = 0.0
        hurt_tex = self._make_vignette_texture((0.95, 0.08, 0.08))
        cm3 = CardMaker("hurt_vign")
        cm3.setFrameFullscreenQuad()
        self._hurt_vignette = self.render2d.attachNewNode(cm3.generate())
        self._hurt_vignette.setTexture(hurt_tex)
        self._hurt_vignette.setTransparency(TransparencyAttrib.MAlpha)
        self._hurt_vignette.setColor(1, 1, 1, 0)
        self._hurt_vignette.setBin("fixed", 42)
        self._hurt_vignette.setDepthTest(False)
        self._hurt_vignette.setDepthWrite(False)
        self._hurt_vignette.hide()

        # голубой вигнет по краям пока активен LIT ENERGY (пчёлы)
        bee_tex = self._make_vignette_texture((0.10, 0.72, 1.0))
        cm4 = CardMaker("bee_vign")
        cm4.setFrameFullscreenQuad()
        self._bee_vignette = self.render2d.attachNewNode(cm4.generate())
        self._bee_vignette.setTexture(bee_tex)
        self._bee_vignette.setTransparency(TransparencyAttrib.MAlpha)
        self._bee_vignette.setColor(1, 1, 1, 0)
        self._bee_vignette.setBin("fixed", 41)
        self._bee_vignette.setDepthTest(False)
        self._bee_vignette.setDepthWrite(False)
        self._bee_vignette.hide()
        self._bee_vign_t = 0.0

        entry_kw = dict(
            text="", scale=0.05, command=self._send_chat,
            width=30, focusInCommand=lambda: None, parent=self.hud_root,
            pos=(-0.9, 0, -0.45), initialText="", numLines=1,
            frameColor=(0, 0, 0, 0.6), text_fg=(1, 1, 1, 1),
        )
        chat_font = self.fonts.get("chat") or self.default_font
        if chat_font:
            entry_kw["text_font"] = chat_font
        self.entry = DirectEntry(**entry_kw)
        self.entry.hide()

    def _toggle_chat(self):
        if self.state != "COMBAT" or self.chat_active:
            return  # только открывает; закрытие — через _send_chat
        self.chat_active = True
        self._set_mouse_captured(False)
        self.entry.show()
        self.entry.enterText("")
        self.entry["focus"] = 1

    def _close_chat(self):
        self.chat_active = False
        self.entry.hide()
        self.entry["focus"] = 0
        self._set_mouse_captured(True)

    def _send_chat(self, text):
        text = (text or "").strip()
        if text and self.net:
            self.net.send({"t": "chat", "msg": text})
        self._close_chat()

    def _add_chat_line(self, line):
        self.chat_lines.append(line)
        self.chat_lines = self.chat_lines[-8:]
        self.chat_node.setText("\n".join(self.chat_lines))

    def _show_notice(self, text, color=(1.0, 0.88, 0.45, 1.0), duration=3.5):
        """Кратковременное уведомление по центру экрана, плавно исчезает."""
        if not self.world_built:
            return
        tn = TextNode("notice")
        tn.setText(text)
        tn.setAlign(TextNode.ACenter)
        fnt = self.fonts.get("hud") or self.default_font
        if fnt:
            tn.setFont(fnt)
        np = self.aspect2d.attachNewNode(tn)
        np.setScale(0.060)
        np.setTransparency(TransparencyAttrib.MAlpha)
        np.setColorScale(*color)
        np.setBin("fixed", 50)
        self._notices.append([np, duration, duration])
        # пересчитать позиции (снизу вверх)
        self._restack_notices()

    def _restack_notices(self):
        base_z = -0.28
        for i, entry in enumerate(self._notices):
            entry[0].setPos(0, 0, base_z + i * 0.090)

    def _update_notices(self, dt):
        alive = []
        for entry in self._notices:
            np, timer, duration = entry
            timer -= dt
            entry[1] = timer
            fade_start = min(0.6, duration * 0.25)
            if timer <= 0:
                np.removeNode()
            else:
                if timer < fade_start:
                    np.setColorScale(np.getColorScale()[0],
                                     np.getColorScale()[1],
                                     np.getColorScale()[2],
                                     timer / fade_start)
                alive.append(entry)
        changed = len(alive) != len(self._notices)
        self._notices = alive
        if changed:
            self._restack_notices()

    # ---------- действия ----------
    def _can_fire(self):
        if self.state == "TUTORIAL" and hasattr(self, '_tut_steps'):
            step = (self._tut_steps[self._tut_step][0]
                    if self._tut_step < len(self._tut_steps) else '_done')
            if step == 'pickup_lit':
                return False
            if step == 'neon' and self.weapon != 'hive':
                return False  # нельзя стрелять до выбора пчёл
        return self.state in ("COMBAT", "TUTORIAL") and not self.chat_active and not self.is_dead

    def _on_fire_down(self):
        if not self._can_fire():
            return
        if self.weapon == "hive":
            if self.bee_time <= 0:
                # первый выстрел — активация LIT ENERGY
                if self.lit_energy <= 0:
                    self._show_notice("Нужна LIT ENERGY  выбей её с тараканов",
                                      color=(0.9, 0.6, 0.1, 1), duration=2.5)
                    return
                if self.state == "TUTORIAL" and hasattr(self, "_tut_world") and self._tut_world:
                    self._tut_world.use_lit_energy(1)
                elif self.net:
                    self.net.send({"t": "use_lit"})
                    self._pending_use_lit = True
                self.bee_time = C.BEE_WINDOW
                self._show_notice("LIT ENERGY потрачено  пчёлы активны!",
                                  color=(0.4, 0.82, 1.0, 1), duration=2.5)
                self._play_oneshot(AC.SFX_LIT_ENERGY, volume=0.9)
            self._emit_projectile()
            return
        self.firing = True                     # сироп/майонез - струя при зажатии
        self._fire_accum = C.SPRAY_COOLDOWN    # первая капля сразу
        self._start_spray_sound()

    def _on_fire_up(self):
        self.firing = False
        self._stop_spray_sound()

    def _emit_projectile(self):
        if not self._can_fire():
            return
        import random
        if self.camera_mode == "third" and self._3p_shoot_dir:
            fx, fy, fz = self._3p_shoot_dir
        else:
            rad_h = math.radians(self.heading)
            rad_p = math.radians(self.pitch)
            fx = -math.sin(rad_h) * math.cos(rad_p)
            fy = math.cos(rad_h) * math.cos(rad_p)
            fz = math.sin(rad_p)
        if self.weapon in ("syrup", "mayo"):   # разброс капель = вид струи/спрея
            s = C.PROJECTILE_SPREAD
            fx += random.uniform(-s, s)
            fy += random.uniform(-s, s)
            fz += random.uniform(-s, s)
        origin = [self.pos.x, self.pos.y, self.pos.z + 1.8]
        if self.state == "TUTORIAL" and hasattr(self, "_tut_world"):
            self._tut_world.shoot(1, origin, [fx, fy, fz], self.weapon)
        elif self.net:
            self.net.send({"t": "shoot", "pos": origin, "dir": [fx, fy, fz],
                           "weapon": self.weapon})
        # всплеск жидкости у «дула» (только струи)
        if self.weapon in ("syrup", "mayo"):
            muzzle = [self.pos.x + fx * 1.2, self.pos.y + fy * 1.2, self.pos.z + 1.8 + fz]
            col = (0.97, 0.97, 0.95, 1) if self.weapon == "mayo" else (0.45, 1.0, 0.55, 1)
            self.particles.burst(muzzle, count=2, color=col, speed=2.5,
                                 size=0.14, life=0.35, grav=-6.0, spread=0.6, up=0.4)

    # --- общие звуковые помощники ---
    def _play_oneshot(self, path, volume=1.0, rate=1.0):
        snd = load_sound(self.loader, path, loop=False)
        if snd:
            snd.setVolume(volume * self._sfx_vol)
            snd.setPlayRate(rate)   # питч/скорость (для рандомного питча)
            snd.play()

    def _vol_for_dist(self, dist, max_dist=55.0, min_vol=0.04):
        """Громкость окружения по расстоянию: ближе -> громче."""
        return max(min_vol, min(1.0, 1.0 - dist / max_dist))

    def _vol_at(self, x, y, **kw):
        return self._vol_for_dist(math.hypot(x - self.pos.x, y - self.pos.y), **kw)

    def _play_music(self, path):
        if self._music_path == path and self._music:
            return
        new = load_music(self.loader, path, loop=True)
        if new is None:
            return  # нет файла трека - не глушим текущую музыку
        if self._music:
            self._music.stop()
        self._music = new
        self._music_path = path
        self._music.setVolume(self._music_vol)
        self._music.play()

    def _update_slit_music(self):
        """Во время события щелей играет своя музыка: первые 15с — обычная тревога,
        последние SLIT_FINAL_PHASE секунд — финальная. После события — вернуть фон.
        BLACK KING имеет приоритет и не даёт переключить свою тему."""
        if self.state == "TUTORIAL":
            return
        if self.black_king and self.bk_boss_info:
            # фаза BLACK KING: не переключать музыку сцен ЩЕЛИ поверх темы BLACK KING
            self._slit_music_on = self.slit_time > 0.0
            return
        if self.wormchello_info:
            # фаза ЧЕРВЯЧЕЛЛО: не перебивать его тему
            self._slit_music_on = self.slit_time > 0.0
            return
        active = self.slit_time > 0.0
        if active:
            if self.slit_time <= C.SLIT_FINAL_PHASE:
                self._play_music(AC.MUSIC_SLIT_FINAL)
            else:
                self._play_music(AC.MUSIC_SLIT)
        elif self._slit_music_on:
            # событие завершилось — вернуть музыку фазы/босса
            self._play_music(AC.MUSIC_BOSS if (self.boss_info or self.boss2_info) else AC.MUSIC_PHASE1)
        self._slit_music_on = active

    def _stop_music(self):
        if self._music:
            self._music.stop()
        self._music = None
        self._music_path = None

    def _set_loop(self, attr, path, want):
        """Включить/выключить зацикленный ambient-звук (шаги червя/тараканов)."""
        cur = getattr(self, attr)
        if want and cur is None:
            s = load_sound(self.loader, path, loop=True)
            if s:
                s.play()
                setattr(self, attr, s)
        elif not want and cur is not None:
            cur.stop()
            setattr(self, attr, None)

    def _stop_step_loops(self):
        self._set_loop("_worm_step_snd", AC.SFX_WORM_STEP, False)
        self._set_loop("_roach_step_snd", AC.SFX_COCKROACH_STEP, False)
        self._set_loop("_neon_step_snd", AC.SFX_NEON_ANT_STEP, False)
        self._set_loop("_smile_step_snd", AC.SFX_SMILE_STEP, False)
        self._set_loop("_roach_laugh_snd", AC.SFX_COCKROACH_LAUGH, False)
        self._set_loop("_bee_snd", AC.SFX_BEE_LOOP, False)

    # --- звук струи: START один раз, затем зацикленный LOOP ---
    def _spray_paths(self):
        if self.weapon == "mayo":
            return AC.SFX_SHOOT_MAYONEZ_START, AC.SFX_SHOOT_MAYONEZ_LOOP
        return AC.SFX_SHOOT_SYRUP_START, AC.SFX_SHOOT_SYRUP_LOOP

    def _start_spray_sound(self):
        self._stop_spray_sound()
        start_path, loop_path = self._spray_paths()
        self._spray_loop_snd = load_sound(self.loader, loop_path, loop=True)
        start_snd = load_sound(self.loader, start_path, loop=False)
        self._spray_start_snd = start_snd
        if start_snd:
            start_snd.play()
            delay = start_snd.length() or 0.0
            if delay > 0.01 and self._spray_loop_snd:
                # включить луп ровно после окончания стартового звука
                self._spray_loop_task = self.taskMgr.doMethodLater(
                    delay, self._begin_spray_loop, "spray_loop")
            elif self._spray_loop_snd:
                self._spray_loop_snd.play()
        elif self._spray_loop_snd:
            self._spray_loop_snd.play()

    def _begin_spray_loop(self, task):
        if self.firing and self._spray_loop_snd:
            self._spray_loop_snd.play()
        self._spray_loop_task = None
        return task.done

    def _stop_spray_sound(self):
        if self._spray_loop_task is not None:
            self.taskMgr.remove(self._spray_loop_task)
            self._spray_loop_task = None
        if self._spray_start_snd:
            self._spray_start_snd.stop()
            self._spray_start_snd = None
        if self._spray_loop_snd:
            self._spray_loop_snd.stop()
            self._spray_loop_snd = None

    def _set_weapon(self, weapon):
        if self.state not in ("COMBAT", "TUTORIAL"):
            return
        # пчёлы (улей) — доступны только если есть LIT ENERGY или уже активны
        if weapon == "hive" and self.bee_time <= 0 and self.lit_energy <= 0:
            self._show_notice("Нужна LIT ENERGY  выбей её с тараканов", color=(0.9, 0.6, 0.1, 1), duration=2.5)
            return
        if weapon != self.weapon:
            _sfx = {
                "syrup": AC.SFX_WEAPON_SYRUP,
                "mayo":  AC.SFX_WEAPON_MAYO,
                "hive":  AC.SFX_WEAPON_HIVE,
            }
            self._play_oneshot(_sfx.get(weapon, AC.SFX_WEAPON_SELECT), volume=0.7)
        self.weapon = weapon
        names = {"syrup": "Распылитель сиропа", "mayo": "Майонезная пушка",
                 "hive": "Улей-пчёлы (LIT ENERGY)"}
        pass  # смена оружия видна в HUD
        # струя завязана на тип оружия - поправим звук/режим при смене
        if self.firing:
            if weapon == "hive":
                self.firing = False
                self._stop_spray_sound()
            else:
                self._start_spray_sound()   # сменить луп на нужную жидкость

    def _god_toggle(self):
        if self.state != "COMBAT" or not self.net:
            return
        if self.player_name == "GODBLESSER":
            self.net.send({"t": "god_toggle"})

    def _god_lit_energy(self):
        if self.state != "COMBAT" or not self.net:
            return
        if self.player_name == "GODBLESSER":
            self.net.send({"t": "god_lit"})

    def _god_wave11(self):
        if self.state != "COMBAT" or not self.net:
            return
        if self.player_name == "GODBLESSER":
            self.net.send({"t": "god_wave11"})

    def _ultimate(self):
        if self.state != "COMBAT" or self.chat_active or self.is_dead or not self.net:
            return
        self.net.send({"t": "ult"})

    def _place_cup(self):
        if self.state != "COMBAT" or self.chat_active or self.is_dead or not self.net:
            return
        if self.cups <= 0:
            self._show_notice("Нет стаканов  выбей босса!", color=(0.9, 0.6, 0.1, 1), duration=2.0)
            return
        self.net.send({"t": "place_cup"})

    def _toggle_camera(self):
        if self.state not in ("COMBAT", "TUTORIAL"):
            return
        self.camera_mode = "first" if self.camera_mode == "third" else "third"
        label = "от первого лица" if self.camera_mode == "first" else "от третьего лица"
        pass  # переключение камеры — понятно без надписи

    def _emote(self, emote):
        if self.state != "COMBAT" or self.chat_active or not self.net:
            return
        self.net.send({"t": "emote", "emote": emote, "pet": "worm"})

    # ---------- мышь ----------
    def _has_pointer(self):
        # offscreen-буфер не поддерживает указатель/свойства окна
        return hasattr(self.win, "getProperties") and self.win.getProperties().getForeground()

    def _recenter_mouse(self):
        if self._has_pointer():
            self.win.movePointer(0, self.win.getXSize() // 2, self.win.getYSize() // 2)

    def _mouse_look(self):
        if not self.mouse_look or not self._has_pointer():
            return
        md = self.win.getPointer(0)
        cx, cy = self.win.getXSize() // 2, self.win.getYSize() // 2
        if self.win.movePointer(0, cx, cy):
            dx = md.getX() - cx
            dy = md.getY() - cy
            self.heading -= dx * self._mouse_sens
            self.pitch = max(-60, min(80, self.pitch - dy * self._mouse_sens))

    # ---------- главный цикл ----------
    def update(self, task):
        dt = globalClock.getDt()
        self._last_dt = dt
        # пока есть подключение, мир продолжает жить — даже в паузе/настройках
        # (мультиплеер не замораживается; пауза лишь размывает фон и снимает управление)
        live = self.world_built and self.net is not None
        if not live:
            if self.state == "TUTORIAL" and self.world_built:
                # туториал — без сети, свой цикл
                controllable_tut = not self._bk_cutscene and not self._bk_death_cs
                if controllable_tut:
                    self._mouse_look()
                    self._update_firing(dt)
                self.particles.update(dt)
                if controllable_tut:
                    self._move(dt)
                self._apply_camera(dt)
                self._update_overlays(dt)
                self._update_notices(dt)
                self._update_hud()
                self._tut_update(dt)
                _tut_moving = (not self.is_dead and not self.chat_active
                               and self.on_ground
                               and any(self.keys[k] for k in ("forward","backward","left","right")))
                self._set_loop("_worm_step_snd", AC.SFX_WORM_STEP, _tut_moving)
                if self._worm_step_snd is not None:
                    self._worm_step_snd.setVolume(0.5 * self._sfx_vol)
                return Task.cont
            self._update_menu_background(dt)   # живой фон меню (без подключения)
            return Task.cont

        if self.net.error:
            self._add_chat_line(f"[СЕТЬ] {self.net.error}")
            self.net.error = None

        controllable = (self.state == "COMBAT") and not self._bk_cutscene and not self._wc_cutscene
        if controllable:
            self._mouse_look()
            self._update_firing(dt)
        self._update_audio(dt)
        self.particles.update(dt)
        if controllable:
            self._move(dt)
        elif self.state == "PAUSE" and self.world_built and not self.on_ground:
            # пауза не должна останавливать физику — продолжаем гравитацию
            self.vz += C.GRAVITY * dt
            self.pos.z += self.vz * dt
            gz = support_z(self.pos.x, self.pos.y, self.pos.z)
            if self.vz <= 0 and self.pos.z <= gz:
                self.pos.z = gz
                self.vz = 0.0
                self.on_ground = True
        self._update_bk_cutscene(dt)
        self._update_wc_filter(dt)
        self._update_bk_death_cutscene(dt)
        self._update_bk_wipe(dt)
        self._update_notices(dt)
        if not self._bk_cutscene and not self._bk_death_cs and not self._wc_cutscene:
            self._apply_camera(dt)
        # сироп льётся из угловых стаканов во время фазы BLACK KING
        if self.black_king and not self._bk_cutscene:
            self._bk_syrup_timer -= dt
            if self._bk_syrup_timer <= 0:
                self._bk_syrup_timer = 0.12
                import random as _sr
                for cx, cy in CUP_SPOTS:
                    for _ in range(3):
                        ang = _sr.uniform(0, 6.28)
                        spd = _sr.uniform(2.0, 5.0)
                        self.particles.burst(
                            [cx, cy, 1.2], count=1,
                            color=(0.35, 1.0, 0.15, 1), speed=spd, size=0.22,
                            life=0.9, grav=-8.0, spread=1.0, up=0.6)
        self._process_network(dt)      # снапшоты приходят и применяются всегда
        self._update_remotes(dt)
        if self.world_built:
            self._interpolate_entities(dt)  # плавное движение каждый кадр
        if controllable:
            self._send_state(dt)
        self._update_hud()
        self._update_overlays(dt)
        return Task.cont

    def _update_audio(self, dt):
        import time as _t
        import random
        self._hurt_cd = max(0.0, self._hurt_cd - dt)
        self._boss_hit_cd = max(0.0, self._boss_hit_cd - dt)
        slit_active = self.slit_time > 0.0
        # шаги червя - пока движется по земле (в паузе/меню — нет)
        moving = (self.state == "COMBAT" and not self.is_dead and not self.chat_active
                  and self.on_ground and any(self.keys[k] for k in ("forward","backward","left","right")))
        self._set_loop("_worm_step_snd", AC.SFX_WORM_STEP, moving)
        # шаги тараканов - пока есть живые (но во время щели они стоят и ржут)
        self._set_loop("_roach_step_snd", AC.SFX_COCKROACH_STEP,
                       self.alive_ants > 0 and not slit_active)
        if self._roach_step_snd is not None and self.ant_nodes:
            nd = min(math.hypot(n.getX() - self.pos.x, n.getY() - self.pos.y)
                     for n in self.ant_nodes.values())
            self._roach_step_snd.setVolume(self._vol_for_dist(nd, max_dist=35.0) * self._sfx_vol)
        if self._worm_step_snd is not None:
            self._worm_step_snd.setVolume(0.5 * self._sfx_vol)
        # шаги неоновых муравьёв
        self._set_loop("_neon_step_snd", AC.SFX_NEON_ANT_STEP,
                       bool(self.neon_ant_nodes))
        if self._neon_step_snd is not None and self.neon_ant_nodes:
            nd2 = min(math.hypot(n.getX() - self.pos.x, n.getY() - self.pos.y)
                      for n in self.neon_ant_nodes.values())
            self._neon_step_snd.setVolume(self._vol_for_dist(nd2, max_dist=30.0) * self._sfx_vol)
        # шаги зелёных тараканов
        self._set_loop("_smile_step_snd", AC.SFX_SMILE_STEP,
                       bool(self.smile_roach_nodes))
        if self._smile_step_snd is not None and self.smile_roach_nodes:
            nd3 = min(math.hypot(n.getX() - self.pos.x, n.getY() - self.pos.y)
                      for n in self.smile_roach_nodes.values())
            self._smile_step_snd.setVolume(self._vol_for_dist(nd3, max_dist=30.0) * self._sfx_vol)
        # ржач тараканов: следующий звук смеха ПОСЛЕ того, как доиграл предыдущий
        if slit_active and self.alive_ants > 0:
            if self._roach_laugh_snd is None:
                self._roach_laugh_snd = load_sound(self.loader, AC.SFX_COCKROACH_LAUGH)
            s = self._roach_laugh_snd
            if s is not None:
                vol = 1.0
                if self.ant_nodes:
                    nd = min(math.hypot(n.getX() - self.pos.x, n.getY() - self.pos.y)
                             for n in self.ant_nodes.values())
                    vol = self._vol_for_dist(nd, max_dist=35.0)
                s.setVolume(vol * self._sfx_vol)
                if s.status() != AudioSound.PLAYING:
                    s.play()
        elif self._roach_laugh_snd is not None:
            self._roach_laugh_snd.stop()
        # случайные реплики Папани (громкость по дистанции до босса)
        if self.boss_info:
            now = _t.time()
            if now >= self._boss_voice_at:
                voices = [v for v in AC.SFX_BOSS_VOICES]
                if voices:
                    bx, by = self.boss_info["pos"][0], self.boss_info["pos"][1]
                    self._play_oneshot(random.choice(voices), volume=self._vol_at(bx, by))
                self._boss_voice_at = now + random.uniform(4.0, 9.0)
        else:
            self._boss_voice_at = 0.0
        # звуки Червячелло: периодический рёв
        self._wc_roar_cd = max(0.0, self._wc_roar_cd - dt)
        if self.wormchello_info and self._wc_roar_cd <= 0:
            wc_state = self.wormchello_info.get("state", "UNDERGROUND")
            if wc_state != "UNDERGROUND":
                self._play_oneshot(AC.SFX_WORMCHELLO_ROAR)
                self._wc_roar_cd = random.uniform(6.0, 12.0)
        # звук попадания по BLACK KING
        self._bk_hit_cd = max(0.0, self._bk_hit_cd - dt)
        if self.bk_boss_info:
            cur_hp = self.bk_boss_info.get("hp", C.BLACK_KING_HP)
            if cur_hp < self._prev_bk_hp - 0.5 and self._bk_hit_cd <= 0:
                bkp = self.bk_boss_info["pos"]
                self._play_oneshot(AC.SFX_BLACK_KING_HIT, volume=self._vol_at(bkp[0], bkp[1]))
                self._bk_hit_cd = 0.2
            self._prev_bk_hp = cur_hp
        else:
            self._prev_bk_hp = C.BLACK_KING_HP

    def _update_firing(self, dt):
        # пока ЛКМ зажата - выпускаем капли струи с частотой SPRAY_COOLDOWN
        if self.is_dead or self.chat_active:
            if self.firing:
                self._on_fire_up()
            return
        if not self.firing or self.weapon not in ("syrup", "mayo"):
            return
        self._fire_accum += dt
        while self._fire_accum >= C.SPRAY_COOLDOWN:
            self._fire_accum -= C.SPRAY_COOLDOWN
            self._emit_projectile()

    def _move(self, dt):
        if self.chat_active or self.is_dead:
            move = Vec2(0, 0)
        else:
            rad = math.radians(self.heading)
            fwd = Vec2(-math.sin(rad), math.cos(rad))
            right = Vec2(math.cos(rad), math.sin(rad))
            move = Vec2(0, 0)
            if self.keys["forward"]:
                move += fwd
            if self.keys["backward"]:
                move -= fwd
            if self.keys["right"]:
                move += right
            if self.keys["left"]:
                move -= right
            if move.lengthSquared() > 0:
                move.normalize()

        gas_held = (self.keys.get("gas", False)
                    and self.state in ("COMBAT", "TUTORIAL")
                    and not self.chat_active)
        speed = C.PLAYER_SPEED * (C.GAS_MULT if gas_held else 1.0)
        if self.player_slow > 0:        # газ босса замедляет
            speed *= C.BOSS_GAS_SLOW_FACTOR
        self.pos.x += move.x * speed * dt
        self.pos.y += move.y * speed * dt

        # отброс от взрыва босса (горизонтальный импульс, плавно затухает — несёт далеко)
        if self.knockback.lengthSquared() > 0.001:
            self.pos.x += self.knockback.x * dt
            self.pos.y += self.knockback.y * dt
            self.knockback *= max(0.0, 1.0 - 3.5 * dt)
        else:
            self.knockback.set(0, 0, 0)

        # опора под ногами: пол (0) либо верх платформы 2-го уровня
        # в туториале всегда ровный пол на Z=0, арена-функции не применяются
        if self.state == "TUTORIAL":
            ground_z = 0.0
        else:
            ground_z = support_z(self.pos.x, self.pos.y, self.pos.z)

        # прыжок и гравитация (джамп-пад имеет приоритет над обычным прыжком)
        if (self.state != "TUTORIAL" and self.on_ground and ground_z <= 0.01
                and not self.chat_active
                and on_jump_pad(self.pos.x, self.pos.y)):
            self.vz = C.JUMP_PAD_BOOST          # подбрасывает на верхний уровень
            self.on_ground = False
        elif self.keys["jump"] and self.on_ground and not self.chat_active and not self.is_dead:
            self.vz = C.PLAYER_JUMP
            self.on_ground = False
        self.vz += C.GRAVITY * dt
        self.pos.z += self.vz * dt
        if self.vz <= 0 and self.pos.z <= ground_z:
            self.pos.z = ground_z               # приземление на пол/платформу
            self.vz = 0
            self.on_ground = True
        else:
            self.on_ground = False

        if self.state == "TUTORIAL":
            # коридор: клэмп делается в _tut_update; арена-стены не применяются
            pass
        else:
            lim = C.WORLD_SIZE - 1
            self.pos.x = max(-lim, min(lim, self.pos.x))
            self.pos.y = max(-lim, min(lim, self.pos.y))
            # коллизии со стенами (выталкивание наружу); на верхнем кольце (z>стен) не толкает
            self.pos.x, self.pos.y = resolve_collision(
                self.pos.x, self.pos.y, self._building_rects, radius=0.6, z=self.pos.z)

    def _apply_camera(self, dt):
        rad_h = math.radians(self.heading)

        # анимировать локального червя (свои анимации видны и в 1-м, и в 3-м лице)
        first = (self.camera_mode == "first")
        self.local_worm.set_first_person(first)
        self.local_worm.root.setPos(self.pos.x, self.pos.y, self.pos.z)
        self.local_worm.root.setH(self.heading)
        moving = (not self.is_dead and not self.chat_active
                  and any(self.keys[k] for k in ("forward","backward","left","right")))
        emote = (getattr(self, "_my_snapshot", None) or {}).get("emote")
        self.local_worm.update(dt, moving=moving, on_ground=self.on_ground,
                               vz=self.vz, emote=emote, dead=self.is_dead)
        if getattr(self, "_respawn_immune", False):
            self.local_worm.root.setTransparency(TransparencyAttrib.MAlpha)
            self.local_worm.root.setAlphaScale(0.35)
        else:
            self.local_worm.root.clearTransparency()
            self.local_worm.root.setAlphaScale(1.0)

        # тряска камеры (взрывы/победа над щелью) — затухает
        sx = sy = sz = 0.0
        if self._shake_amp > 0.001:
            import random
            a = self._shake_amp
            sx = random.uniform(-a, a)
            sy = random.uniform(-a, a)
            sz = random.uniform(-a, a)
            self._shake_amp = max(0.0, self._shake_amp - 2.2 * dt)   # дольше трясёт

        if first:
            self.camera.setPos(self.pos.x + sx, self.pos.y + sy, self.pos.z + 1.9 + sz)
            self.camera.setHpr(self.heading, self.pitch, 0)
            return

        # вид от третьего лица - орбита позади и сверху червя
        focus_z = self.pos.z + 2.2
        elev = min(math.radians(75), math.radians(self.pitch + 16))  # наклон сверху
        dist = 11.0
        fwd_x, fwd_y = -math.sin(rad_h), math.cos(rad_h)   # «вперёд»
        horiz = dist * math.cos(elev)
        camx = self.pos.x - fwd_x * horiz
        camy = self.pos.y - fwd_y * horiz
        camz = max(1.2, focus_z + dist * math.sin(elev))

        # коллизия камеры со стенами: бинарный поиск по лучу игрок→камера
        wall_rects = getattr(self, "_cam_wall_rects", None)
        if wall_rects and camz < WALL_HEIGHT and in_any_building(camx, camy, wall_rects):
            px, py = self.pos.x, self.pos.y
            lo, hi = 0.05, 1.0
            for _ in range(7):
                mid_t = (lo + hi) / 2
                mx = px + (camx - px) * mid_t
                my = py + (camy - py) * mid_t
                if in_any_building(mx, my, wall_rects):
                    hi = mid_t
                else:
                    lo = mid_t
            camx = px + (camx - px) * lo
            camy = py + (camy - py) * lo
            camz = max(1.2, focus_z + lo * dist * math.sin(elev))

        # направление стрельбы в 3-м лице = куда смотрит камера (из камеры к точке фокуса)
        _dx = self.pos.x - camx
        _dy = self.pos.y - camy
        _dz = focus_z - camz
        _dlen = math.sqrt(_dx * _dx + _dy * _dy + _dz * _dz) or 1.0
        self._3p_shoot_dir = (_dx / _dlen, _dy / _dlen, _dz / _dlen)

        self.camera.setPos(camx + sx, camy + sy, camz + sz)
        self.camera.lookAt(self.pos.x, self.pos.y, focus_z)

    def _send_state(self, dt):
        self._state_accum += dt
        if self._state_accum >= 1.0 / 20:  # 20 апдейтов/сек
            self._state_accum = 0.0
            self.net.send({
                "t": "state",
                "pos": [self.pos.x, self.pos.y, self.pos.z],
                "h": self.heading, "p": self.pitch,
            })

    def _process_network(self, dt):
        for msg in self.net.poll():
            t = msg.get("t")
            if t == "welcome":
                self.my_id = msg["id"]
                self._show_notice(f"Добро пожаловать! ID: {self.my_id}",
                                  color=(0.6, 0.9, 0.6, 1), duration=3.0)
            elif t == "snapshot":
                self._latest_snapshot = msg
                self._apply_snapshot(msg)
            elif t == "chat":
                self._add_chat_line(f"{msg.get('name','?')}: {msg.get('msg','')}")
            elif t == "event":
                self._handle_event(msg)

    def _handle_event(self, msg):
        _CAUSE_NAMES = {
            "ant": "таракан", "neon_ant": "неоновый муравей", "smile": "зелёный таракан",
            "boss": "Папаня", "wormchello": "ЧЕРВЯЧЕЛЛО", "black_king": "BLACK KING",
            "bk_minion": "копия BLACK KING", "slit": "ЩЕЛЬ", "player": None, "unknown": None,
        }
        kind = msg.get("kind")
        if kind == "splash":
            self._add_chat_line(f"{msg.get('by')} убил {msg.get('victim')} сиропом!")
        elif kind == "ant_killed":
            import random
            pos = msg.get("pos")
            vol = 1.0
            if pos:
                self.particles.burst([pos[0], pos[1], 0.4], count=10,
                                     color=(0.55, 1.0, 0.1, 1), speed=5.0,
                                     size=0.2, life=0.6, grav=-12.0, spread=1.0, up=1.0)
                vol = self._vol_at(pos[0], pos[1])     # тише, если далеко
            self._play_oneshot(AC.SFX_COCKROACH_DEATH, volume=vol,
                               rate=random.uniform(0.8, 1.3))   # рандомный питч
        elif kind == "pickup":
            drop = msg.get("drop", "ресурс")
            if msg.get("by") == self.player_name:
                if drop == "lit_energy":
                    self._show_notice("LIT ENERGY подобран!  нажми [3] - активируй пчёл!",
                                      color=(0.4, 0.82, 1.0, 1))
                elif drop == "cup":
                    self._show_notice("СТАКАН подобран!  неси в угол карты  [R] - поставить",
                                      color=(1.0, 0.88, 0.45, 1))
                self._play_oneshot(AC.SFX_PICKUP)
                col = DROP_COLORS.get(drop, (1, 1, 1, 1))
                self.particles.burst([self.pos.x, self.pos.y, 1.0], count=8,
                                     color=col, speed=3.5, size=0.16, life=0.5,
                                     grav=-6.0, spread=0.8, up=1.0)
        elif kind == "lit_used":
            if msg.get("by") == self.player_name:
                self._show_notice(f"ПЧЁЛЫ АКТИВНЫ  {int(msg.get('time', 12))}с!",
                                  color=(0.4, 0.82, 1.0, 1), duration=2.5)
                # SFX_LIT_ENERGY уже сыгран в _set_weapon — не дублировать
        elif kind == "cup_placed":
            self._show_notice(f"Стакан поставлен  {msg.get('count', '?')}/4",
                              color=(1.0, 0.88, 0.45, 1), duration=2.5)
            self._play_oneshot(AC.SFX_PICKUP, rate=0.7)
        elif kind == "black_king_spawn":
            import random as _r
            self._show_notice("=== BLACK KING ПРОБУЖДАЕТСЯ! ===",
                              color=(0.7, 0.0, 1.0, 1), duration=5.0)
            self._play_oneshot(AC.SFX_BLACK_KING_SPAWN)
            self._play_music(AC.MUSIC_BLACK_KING)  # сразу задать тему кат-сцены
            # телепортировать локального игрока на спавн
            self.pos.set(_r.uniform(-5, 5), _r.uniform(-20, -14), 0.0)
            self.vz = 0.0
            self.on_ground = True
            # запустить кат-сцену
            self._bk_cutscene = True
            self._bk_cutscene_t = 0.0
            self.firing = False
            self._stop_spray_sound()
            # 4 стакана для кат-сцены (появятся во время вращения)
            for n in self._bk_cup_nodes:
                n.removeNode()
            self._bk_cup_nodes = []
            for _ in range(4):
                cn = make_cup()
                cn.reparentTo(self.render)
                cn.hide()
                self._bk_cup_nodes.append(cn)
        elif kind == "bk_defeated":
            self._show_notice(f"BLACK KING ПОВЕРЖЕН!  {msg.get('by')} стал легендой!  +50 всем!",
                              color=(1.0, 0.85, 0.1, 1), duration=6.0)
            self._play_oneshot(AC.SFX_BLACK_KING_DEATH)
            # взрыв частиц на месте каждого миньона перед их исчезновением
            for mid, mnode in list(self.bk_minion_nodes.items()):
                if mnode and not mnode.isEmpty():
                    mp = mnode.getPos()
                    self.particles.burst([mp.x, mp.y, mp.z + 0.5], count=14,
                                        color=(0.5, 0.0, 1.0, 1), speed=5.0,
                                        size=0.4, life=1.0, grav=-3.0, spread=1.5, up=0.8)
            pos = msg.get("pos", [0.0, 0.0])
            self._start_bk_death_cutscene(pos[0], pos[1])
        elif kind == "bk_wipe":
            self._show_notice("ВАЙП  BLACK KING уходит...  волна возобновится",
                              color=(1.0, 0.2, 0.2, 1), duration=5.0)
            self._start_bk_wipe_sink(msg)
            self._play_music(AC.MUSIC_PHASE1)
        elif kind == "bk_voice":
            import random as _r
            voices = [v for v in AC.SFX_BLACK_KING_VOICES]
            if voices:
                bkp = self.bk_boss_info["pos"] if self.bk_boss_info else None
                vol = self._vol_at(bkp[0], bkp[1]) if bkp else 1.0
                self._play_oneshot(_r.choice(voices), volume=max(0.85, vol))
        elif kind == "bk_phase2":
            self._show_notice("BLACK KING ВЗБЕСИЛСЯ!  ФАЗА 2: ЛАЗЕРЫ + СТАКАНЫ!",
                              color=(0.85, 0.0, 1.0, 1), duration=5.0)
            self._flash_screen((0.6, 0.0, 1.0, 1), duration=1.4, hold=0.3)
            self._shake(0.8)
            phase2_snd = AC.SFX_BLACK_KING_PHASE2
            import os as _os
            self._play_oneshot(
                phase2_snd if _os.path.exists(phase2_snd) else AC.SFX_BLACK_KING_SPAWN,
                volume=0.85)
        elif kind == "bk_shoot":
            pos = msg.get("pos", [0, 0, 2.5])
            self.particles.burst(pos, count=6, color=(0.7, 0.0, 1.0, 1), speed=5.0,
                                 size=0.2, life=0.35, grav=-1.0, spread=0.6, up=0.4)
        elif kind == "bk_shot_hit":
            pos = msg.get("pos", [0, 0, 1])
            self.particles.burst(pos, count=12, color=(0.8, 0.0, 1.0, 1), speed=7.0,
                                 size=0.25, life=0.5, grav=-8.0, spread=1.0, up=1.0)
            self._play_oneshot(AC.SFX_BLACK_KING_HIT, volume=self._vol_at(pos[0], pos[1]))
        elif kind == "bk_cup_shoot":
            pos = msg.get("pos", [0, 0, 1.5])
            self.particles.burst(pos, count=4, color=(0.3, 1.0, 0.2, 1), speed=3.0,
                                 size=0.18, life=0.3, grav=-1.0, spread=0.5, up=0.3)
            self._play_oneshot(AC.SFX_BK_CUP_SHOOT,
                               volume=self._vol_at(pos[0], pos[1]) * 0.7)
        elif kind == "bk_cup_hit":
            pos = msg.get("pos", [0, 0, 1])
            self.particles.burst(pos, count=8, color=(0.25, 1.0, 0.3, 1), speed=5.0,
                                 size=0.22, life=0.5, grav=-6.0, spread=1.0, up=0.8)
        elif kind == "bk_minion_spawn":
            pass  # тихо — визуально появляются из под босса
        elif kind == "bk_minion_killed":
            import random as _r
            pos = msg.get("pos", [0, 0])
            self.particles.burst([pos[0], pos[1], 0.5], count=10,
                                 color=(0.55, 0.0, 1.0, 1), speed=5.0, size=0.2,
                                 life=0.5, grav=-8.0, spread=1.0, up=1.0)
            self._play_oneshot(AC.SFX_COCKROACH_DEATH, volume=self._vol_at(pos[0], pos[1]),
                               rate=1.5)
        elif kind == "wipe":
            self._show_notice("ВАЙП  все погибли  начинаем с волны 1!",
                              color=(1.0, 0.2, 0.2, 1), duration=4.0)
            self._play_music(AC.MUSIC_PHASE1)
        elif kind == "wormchello_spawn":
            self._wormchello_cutscene(msg)
        elif kind == "wormchello_shoot":
            pos = msg.get("pos", [0, 0, 2])
            self._play_oneshot(AC.SFX_WORMCHELLO_SHOOT, volume=self._vol_at(pos[0], pos[1]))
            self.particles.burst([pos[0], pos[1], pos[2]], count=4,
                                 color=(0.9, 0.6, 0.3, 1), speed=6.0,
                                 size=0.2, life=0.35, grav=-5.0, spread=0.5, up=0.5)
        elif kind == "wormchello_hit":
            pos = msg.get("pos", [0, 0, 2])
            self.particles.burst([pos[0], pos[1], pos[2]], count=8,
                                 color=(0.95, 0.55, 0.2, 1), speed=5.0,
                                 size=0.28, life=0.5, grav=-7.0, spread=1.0, up=0.7)
        elif kind == "wormchello_phase2":
            self._show_notice("ЧЕРВЯЧЕЛЛО - ФАЗА 2!", color=(1.0, 0.45, 0.1, 1), duration=3.0)
            self._flash_screen((1.0, 0.6, 0.2, 1), 0.5)
            self._play_oneshot(AC.SFX_WORMCHELLO_PHASE2)
        elif kind == "wormchello_defeated":
            by = msg.get("by", "?")
            self._show_notice(f"ЧЕРВЯЧЕЛЛО ПОБЕЖДЁН! (+{50} очков)", color=(0.95, 0.8, 0.2, 1), duration=5.0)
            self._flash_screen((1.0, 0.9, 0.4, 1), 0.8)
            self._shake(0.6)
            self._play_oneshot(AC.SFX_WORMCHELLO_DEATH)
            self._play_music(AC.MUSIC_PHASE1)
        elif kind == "wormchello_minions":
            n = msg.get("count", 3)
            self._show_notice(f"Червячелло вызывает {n} тараканов!", color=(0.9, 0.5, 0.1, 1), duration=2.0)
        elif kind == "wormchello_lina_hit":
            pos = msg.get("pos", [0, 0, 5])
            self.particles.burst(pos, count=20,
                                 color=(0.25, 0.80, 1.0, 1), speed=6.0,
                                 size=0.35, life=0.8, grav=-5.0, spread=1.4, up=0.8)
            # если все сферы мертвы — сообщение о снятии щита
            wc = self.wormchello_info
            if wc:
                lina = wc.get("lina", [])
                remaining = sum(1 for d in lina if len(d) > 1 and d[1])
                if remaining <= 1:  # эта сфера последняя
                    self._show_notice("Щит снят! Атакуй ЧЕРВЯЧЕЛЛО!", color=(1.0, 0.6, 0.1, 1), duration=3.5)
            self._shake(0.3)
        elif kind == "smile_roach_killed":
            pos = msg.get("pos", [0, 0])
            self.particles.burst([pos[0], pos[1], 0.4], count=10,
                                 color=(0.7, 0.1, 0.1, 1), speed=4.5, size=0.22,
                                 life=0.5, grav=-8.0, spread=1.0, up=0.9)
            self._play_oneshot(AC.SFX_COCKROACH_DEATH, volume=self._vol_at(pos[0], pos[1]),
                               rate=0.9)
        elif kind == "smile_spray":
            pos = msg.get("pos", [0, 0, 0])
            # аэрозольное облако (жёлтоватое, медленно оседает)
            for _ in range(2):
                self.particles.burst([pos[0], pos[1], 1.0], count=8,
                                     color=(0.9, 0.85, 0.2, 1), speed=3.5, size=0.35,
                                     life=1.8, grav=-0.5, spread=1.2, up=0.6)
        elif kind == "boss_gas":
            pos = msg.get("pos", [0, 0])
            # облако едкого зелёного дыма ГАЗЗЗ
            for _ in range(3):
                self.particles.burst([pos[0], pos[1], 1.2], count=10,
                                     color=(0.55, 0.95, 0.35, 1), speed=5.0, size=0.45,
                                     life=1.4, grav=-1.0, spread=1.0, up=0.5)
        elif kind == "death":
            victim = msg.get("victim", "?")
            cause_key = msg.get("cause", "unknown")
            cause_name = _CAUSE_NAMES.get(cause_key)
            if cause_name:
                self._add_chat_line(f"{victim} убит: {cause_name}")
            else:
                self._add_chat_line(f"{victim} погиб")
        elif kind == "mob_attack":
            mob = msg.get("mob")
            if mob == "ant":
                self._play_oneshot(AC.SFX_ANT_ATTACK, volume=0.9)
            elif mob == "smile":
                self._play_oneshot(AC.SFX_SMILE_ATTACK, volume=0.9)
        elif kind == "wave":
            self._show_notice(f"ВОЛНА {msg.get('wave')}  тараканов: {msg.get('count')}",
                              color=(1.0, 0.65, 0.1, 1), duration=3.0)
        elif kind == "boss_spawn":
            if msg.get("double"):
                self._bosses_alive = 2
                self._boss_spawn_count = 2
                self._show_notice(
                    "ДВА ПАПАНИ!  ДЕЛАЙ ГАЗ!  Поливай обоих сиропом - копи Уважение!",
                    color=(1.0, 0.15, 0.0, 1), duration=7.0)
            else:
                self._bosses_alive = 1
                self._boss_spawn_count = 1
                self._show_notice("ПАПАНЯ ВЫШЕЛ!  Поливай сиропом - копи Уважение!",
                                  color=(1.0, 0.4, 0.1, 1), duration=5.0)
            self._play_oneshot(AC.SFX_BOSS_SPAWN)
            self._play_music(AC.MUSIC_BOSS)
        elif kind == "boss_defeated":
            self._play_oneshot(AC.SFX_BOSS_DEATH)
            self._bosses_alive = max(0, self._bosses_alive - 1)
            by = msg.get("by", "?")
            if self._bosses_alive > 0:
                self._show_notice(
                    f"ОДИН ПАПАНЯ ПОВЕРЖЕН!  {by} уважил!  Добей второго!",
                    color=(1.0, 0.85, 0.1, 1), duration=5.0)
            else:
                if self._boss_spawn_count > 1:
                    self._show_notice(
                        f"ОБА ПАПАНИ ПОВЕРЖЕНЫ!  {by} добил последнего!",
                        color=(1.0, 0.85, 0.1, 1), duration=5.0)
                else:
                    self._show_notice(
                        f"ПАПАНЯ ПОВЕРЖЕН!  {by} уважил его!",
                        color=(1.0, 0.85, 0.1, 1), duration=5.0)
                self._play_music(AC.MUSIC_PHASE1)
        elif kind == "boss_throw":
            pos = msg.get("pos", [0, 0, 2.5])
            self._play_oneshot(AC.SFX_BOSS_THROW, volume=self._vol_at(pos[0], pos[1]))
            self.particles.burst(pos, count=10, color=(1.0, 0.5, 0.1, 1), speed=4.0,
                                 size=0.2, life=0.4, grav=-3.0, spread=0.9, up=0.6)
        elif kind == "boss_explode":
            pos = msg.get("pos", [0, 0, 0])
            self._play_oneshot(AC.SFX_EXPLOSION, volume=self._vol_at(pos[0], pos[1]))
            # большой взрыв
            self.particles.burst([pos[0], pos[1], pos[2] + 0.3], count=26,
                                 color=(1.0, 0.45, 0.1, 1), speed=9.0, size=0.32,
                                 life=0.8, grav=-10.0, spread=1.0, up=1.0)
            self.particles.burst([pos[0], pos[1], pos[2] + 0.3], count=12,
                                 color=(1.0, 0.85, 0.3, 1), speed=5.0, size=0.22,
                                 life=0.6, grav=-6.0, spread=1.0, up=0.8)
            self._apply_blast_knockback(pos)
        elif kind == "ultimate":
            self._show_notice(f"{msg.get('by')}: УЛЬТ  тараканы замерли!",
                              color=(0.4, 1.0, 0.9, 1), duration=3.5)
        elif kind == "neon_wave":
            self._show_notice(f"СИНИЕ МУРАВЬИ!  стрелков: {msg.get('count')}",
                              color=(0.4, 0.82, 1.0, 1), duration=4.0)
        elif kind == "neon_shoot":
            pos = msg.get("pos", [0, 0, 1.1])
            self.particles.burst([pos[0], pos[1], pos[2]], count=6,
                                 color=(0.4, 0.82, 1.0, 1), speed=3.0, size=0.16,
                                 life=0.35, grav=-2.0, spread=0.7, up=0.4)
            self._play_oneshot(AC.SFX_SKIBIDI_SHOOT, volume=self._vol_at(pos[0], pos[1]))
        elif kind == "neon_ant_killed":
            import random
            pos = msg.get("pos")
            vol = 1.0
            if pos:
                self.particles.burst([pos[0], pos[1], 0.6], count=16,
                                     color=(0.3, 0.75, 1.0, 1), speed=6.0, size=0.22,
                                     life=0.7, grav=-10.0, spread=1.0, up=1.0)
                self.particles.burst([pos[0], pos[1], 0.6], count=8,
                                     color=(0.7, 0.97, 1.0, 1), speed=3.5, size=0.16,
                                     life=0.5, grav=-5.0, spread=1.0, up=0.8)
                vol = self._vol_at(pos[0], pos[1])
            self._play_oneshot(AC.SFX_COCKROACH_DEATH, volume=vol,
                               rate=random.uniform(1.2, 1.6))   # выше питч = «электронная» смерть
        elif kind == "slit_spawn":
            t = int(msg.get("time", C.SLIT_TIME_LIMIT))
            self._show_notice(
                f"ЩЕЛЬ!  Залей МАЙОНЕЗОМ (2)  {t}с иначе все умрут!",
                color=(1.0, 0.3, 0.5, 1), duration=5.0)
            self._play_oneshot(AC.SFX_SLIT_SPAWN)
        elif kind == "slit_calmed":
            pos = msg.get("pos", [0, 0, 1])
            self.particles.burst([pos[0], pos[1], pos[2]], count=14,
                                 color=(1.0, 0.95, 0.7, 1), speed=4.0, size=0.2,
                                 life=0.6, grav=-6.0, spread=1.0, up=0.8)
            self._show_notice("Щель удовлетворена!", color=(1.0, 0.88, 0.45, 1), duration=2.0)
            # звук успокаивания (calm) идёт В ПРОЦЕССЕ заполнения (см. _apply_snapshot)
        elif kind == "slit_defeated":
            # оглушающий и ОСЛЕПЛЯЮЩИЙ взрыв победы над щелью
            self._show_notice("ВСЕ ЩЕЛИ ПОВЕРЖЕНЫ!  Победа!", color=(1.0, 0.85, 0.1, 1), duration=4.0)
            self._play_oneshot(AC.SFX_SLIT_DEFEATED, volume=1.0)
            self._flash_screen((1, 1, 1, 1), duration=2.0, hold=0.5)
            self._shake(0.9)
            p = [self.pos.x, self.pos.y, self.pos.z + 1.0]
            self.particles.burst(p, count=60, color=(1.0, 0.95, 0.6, 1), speed=18.0,
                                 size=0.45, life=1.3, grav=-6.0, spread=1.0, up=1.0)
            self.particles.burst(p, count=40, color=(1.0, 1.0, 1.0, 1), speed=11.0,
                                 size=0.34, life=1.0, grav=-4.0, spread=1.0, up=0.95)
            self.particles.burst(p, count=22, color=(1.0, 0.8, 0.3, 1), speed=6.0,
                                 size=0.5, life=1.5, grav=-2.0, spread=1.0, up=0.7)
        elif kind == "slit_failed":
            self._show_notice("Не успели...  щель поглотила всех!", color=(1.0, 0.1, 0.1, 1), duration=4.0)
        elif kind == "slit_dismissed":
            # Щель убрана из-за появления Червячелло — сбрасываем состояние немедленно
            self.slit_time = 0.0
            # ноды и музыка щели очистятся через ближайший снапшот автоматически
        elif kind == "skibidi_hit":
            pos = msg.get("pos", [0, 0, 0])
            self.particles.burst([pos[0], pos[1], pos[2] + 0.2], count=14,
                                 color=(0.32, 0.72, 1.0, 1), speed=5.0, size=0.22,
                                 life=0.5, grav=-8.0, spread=1.0, up=0.7)
            self.particles.burst([pos[0], pos[1], pos[2] + 0.2], count=6,
                                 color=(0.7, 0.95, 1.0, 1), speed=2.5, size=0.16,
                                 life=0.4, grav=-4.0, spread=1.0, up=0.5)
            self._play_oneshot(AC.SFX_SKIBIDI_HIT, volume=self._vol_at(pos[0], pos[1]))

    def _apply_snapshot(self, msg):
        # игроки
        seen = set()
        for pid_str, snap in msg.get("players", {}).items():
            pid = int(pid_str)
            if pid == self.my_id:
                self._my_snapshot = snap
                was_dead = self.is_dead
                self.is_dead = bool(snap.get("dead"))
                # при respawn — принять позицию с сервера, иначе игрок остаётся на месте смерти
                if was_dead and not self.is_dead:
                    sp = snap.get("pos", [self.pos.x, self.pos.y, self.pos.z])
                    self.pos.x, self.pos.y, self.pos.z = sp[0], sp[1], sp[2]
                    self.vz = 0.0
                    self.on_ground = True
                hp = snap.get("hp", self._prev_hp)
                if (hp < self._prev_hp - 0.5 and not self.is_dead
                        and self._hurt_cd <= 0):
                    self._play_oneshot(AC.SFX_PLAYER_HURT)
                    self._hurt_cd = 0.5
                    self._hurt_alpha = 0.75
                self._prev_hp = hp
                self.lit_energy = snap.get("lit", 0)
                self._respawn_immune = snap.get("rimm", 0.0) > 0
                server_bee = snap.get("bees", 0.0)
                if server_bee > 0:
                    self._pending_use_lit = False  # сервер подтвердил активацию пчёл
                self.bee_time = server_bee
                self.player_slow = snap.get("slow", 0.0)
                self.cups = snap.get("cups", 0)
                # пчёлы кончились — вернуть сироп
                # не сбрасывать если: ждём подтверждения сервера ИЛИ есть LIT ENERGY (выстрел активирует)
                if (self.weapon == "hive" and self.bee_time <= 0
                        and not self._pending_use_lit and self.lit_energy <= 0):
                    self.weapon = "syrup"
                continue
            seen.add(pid)
            if pid not in self.remote:
                snap_color = snap.get("color")
                self.remote[pid] = RemoteAvatar(self.render, pid, snap["name"],
                                                self.fonts.get("world"),
                                                color=snap_color)
            self.remote[pid].update(snap, globalClock.getDt())
        for pid in list(self.remote):
            if pid not in seen:
                self.remote[pid].destroy()
                del self.remote[pid]

        # метаданные волн/босса
        self.wave = msg.get("wave", self.wave)
        self.alive_ants = msg.get("alive", 0)
        self.neon_alive = msg.get("neon", 0)
        self.boss_info = msg.get("boss")
        self.boss2_info = msg.get("boss2")
        self._last_smile_roaches = msg.get("smile_roaches", [])
        self.wormchello_info = msg.get("wormchello")
        self._last_wshots = msg.get("wshots", [])
        prev_bk = self.black_king
        self.black_king = bool(msg.get("black_king"))
        # при переподключении (black_king_spawn не придёт снова) — сразу включить музыку
        if self.black_king and not prev_bk and not self._bk_cutscene:
            self._play_music(AC.MUSIC_BLACK_KING)
        self.bk_boss_info = msg.get("bk_boss")
        # рендер BLACK KING
        self._update_bk_rendering()
        # копии BLACK KING
        seen_bkm = set()
        for m in msg.get("bk_minions", []):
            mid, mx, my, mz = m
            seen_bkm.add(mid)
            node = self.bk_minion_nodes.get(mid)
            if node is None:
                node = self._make_bk_minion_node()
                node.reparentTo(self.render)
                self.bk_minion_nodes[mid] = node
                self._bkm_vis[mid] = [mx, my, mz]
            self._bkm_target[mid] = [mx, my, mz]
        for mid in list(self.bk_minion_nodes):
            if mid not in seen_bkm:
                self.bk_minion_nodes[mid].removeNode()
                del self.bk_minion_nodes[mid]
                self._bkm_target.pop(mid, None)
                self._bkm_vis.pop(mid, None)

        # фиолетовые лазеры BLACK KING (фаза 2)
        flying_mode = self.bk_boss_info.get("flying", False) if self.bk_boss_info else False
        seen_bks = set()
        for bks in msg.get("bk_shots", []):
            bksid, sx, sy, sz = bks
            seen_bks.add(bksid)
            node = self.bk_shot_nodes.get(bksid)
            if node is None:
                node = make_sphere(0.42, 8, 8, (0.6, 0.0, 1.0, 1))
                node.setScale(1.5, 0.4, 1.5)   # плоский диск — вращение заметно
                node.setLightOff(1)
                node.reparentTo(self.render)
                self.bk_shot_nodes[bksid] = node
            node.setPos(sx, sy, sz)
            if flying_mode:
                node.setH(node.getH() + 18)  # ~540°/s при 30Hz — хаотичное вращение
            self.particles.burst([sx, sy, sz], count=1, color=(0.7, 0.0, 1.0, 1),
                                 speed=1.5, size=0.22, life=0.3, grav=-0.5, spread=0.4, up=0.1)
        for bksid in list(self.bk_shot_nodes):
            if bksid not in seen_bks:
                self.bk_shot_nodes[bksid].removeNode()
                del self.bk_shot_nodes[bksid]

        # ожившие стаканы (фаза 2): ползут по серверной позиции, зелёное свечение
        seen_lc = set()
        for lc in msg.get("bk_living_cups", []):
            cid, cx, cy = lc
            seen_lc.add(cid)
            node = self.bk_lc_nodes.get(cid)
            if node is None:
                node = make_cup()
                node.setLightOff(1)
                node.setColorScale(0.3, 1.0, 0.4, 1)
                node.reparentTo(self.render)
                self.bk_lc_nodes[cid] = node
            node.setPos(cx, cy, 0.0)
            node.setH((node.getH() + 2.0) % 360)   # медленное вращение вокруг оси
            # зелёный пар
            self.particles.burst([cx, cy, 1.0], count=1, color=(0.35, 1.0, 0.2, 1),
                                 speed=1.2, size=0.28, life=0.9, grav=-0.3, spread=0.6, up=0.5)
        for cid in list(self.bk_lc_nodes):
            if cid not in seen_lc:
                self.bk_lc_nodes[cid].removeNode()
                del self.bk_lc_nodes[cid]

        # зелёные замедляющие снаряды ожившего стакана
        seen_cs = set()
        for cs in msg.get("bk_cup_shots", []):
            csid, sx, sy, sz = cs
            seen_cs.add(csid)
            node = self.bk_cup_shot_nodes.get(csid)
            if node is None:
                node = make_sphere(0.30, 8, 8, (0.25, 1.0, 0.35, 1))
                node.setLightOff(1)
                node.reparentTo(self.render)
                self.bk_cup_shot_nodes[csid] = node
            node.setPos(sx, sy, sz)
            self.particles.burst([sx, sy, sz], count=1, color=(0.3, 1.0, 0.2, 1),
                                 speed=1.2, size=0.18, life=0.3, grav=-0.2, spread=0.3, up=0.1)
        for csid in list(self.bk_cup_shot_nodes):
            if csid not in seen_cs:
                self.bk_cup_shot_nodes[csid].removeNode()
                del self.bk_cup_shot_nodes[csid]

        # стаканы на 4 угловых пьедесталах (показываем поставленные)
        spots = msg.get("cup_spots", self.cup_spots)
        if spots != self.cup_spots or not self.cup_spot_nodes:
            self._update_cup_spots(spots)
        self.cup_spots = spots

        # тараканы (волнами появляются и исчезают)
        seen_ants = set()
        for ant in msg.get("ants", []):
            aid, ax, ay, az = ant[0], ant[1], ant[2], ant[3]
            ant_immune = ant[4] if len(ant) > 4 else 0
            seen_ants.add(aid)
            node = self.ant_nodes.get(aid)
            if node is None:
                node = make_cockroach(scale=1.1)
                node.reparentTo(self.render)
                self.ant_nodes[aid] = node
                # мгновенный снап при спавне
                self._ant_vis[aid] = [ax, ay, az]
            # обновить цель — фактический setPos происходит в _interpolate_entities
            self._ant_target[aid] = [ax, ay, az]
            _ai = bool(ant_immune)
            if self._ant_immune_prev.get(aid) != _ai:
                self._ant_immune_prev[aid] = _ai
                if _ai:
                    node.setTransparency(TransparencyAttrib.MAlpha)
                    node.setAlphaScale(0.35)
                else:
                    node.setTransparency(TransparencyAttrib.MNone)
                    node.setAlphaScale(1.0)
        for aid in list(self.ant_nodes):
            if aid not in seen_ants:
                self.ant_nodes[aid].removeNode()
                del self.ant_nodes[aid]
                self._ant_target.pop(aid, None)
                self._ant_vis.pop(aid, None)
                self._ant_prev.pop(aid, None)
                self._ant_immune_prev.pop(aid, None)

        # синие неоновые муравьи-стрелки (светятся, появляются после 3-й волны)
        seen_neon = set()
        for na in msg.get("neon_ants", []):
            nid, nx, ny, nh = na[:4]
            hp = na[4] if len(na) > 4 else C.NEON_ANT_HP
            neon_immune = na[5] if len(na) > 5 else 0
            seen_neon.add(nid)
            node = self.neon_ant_nodes.get(nid)
            if node is None:
                node = make_neon_ant(scale=1.15)
                node.reparentTo(self.render)
                self.neon_ant_nodes[nid] = node
                bar = WorldBar(self.render, label="", width=0.8, height=0.14,
                               fill_color=(0.2, 0.6, 1.0, 1),
                               font=self.fonts.get("world"))
                self._neon_hp_bars[nid] = bar
                # мгновенный снап при спавне
                self._neon_vis[nid] = [nx, ny, 0.0, nh]
            # цель для интерполяции (setPos/setH — в _interpolate_entities каждый кадр)
            self._neon_target[nid] = [nx, ny, 0.0, nh]
            # HP-бар обновляем по снапшоту (без интерполяции — он не движется)
            if nid in self._neon_hp_bars:
                bar = self._neon_hp_bars[nid]
                vis = self._neon_vis.get(nid, [nx, ny, 0.0, nh])
                bar.set_pos(vis[0], vis[1], 2.4)
                bar.set_fraction(hp / C.NEON_ANT_HP)
            _ni = bool(neon_immune)
            if self._neon_immune_prev.get(nid) != _ni:
                self._neon_immune_prev[nid] = _ni
                if _ni:
                    node.setTransparency(TransparencyAttrib.MAlpha)
                    node.setAlphaScale(0.35)
                else:
                    node.setTransparency(TransparencyAttrib.MNone)
                    node.setAlphaScale(1.0)
        for nid in list(self.neon_ant_nodes):
            if nid not in seen_neon:
                self.neon_ant_nodes[nid].removeNode()
                del self.neon_ant_nodes[nid]
                self._neon_target.pop(nid, None)
                self._neon_vis.pop(nid, None)
                self._neon_immune_prev.pop(nid, None)
                if nid in self._neon_hp_bars:
                    self._neon_hp_bars[nid].destroy()
                    del self._neon_hp_bars[nid]

        # «шкибиди-зелье» - синие неоновые снаряды муравьёв (+ светящийся трейл)
        seen_ashots = set()
        for ash in msg.get("ant_shots", []):
            asid, sx, sy, sz = ash
            seen_ashots.add(asid)
            node = self.ant_shot_nodes.get(asid)
            if node is None:
                node = make_box(0.4, 0.4, 0.4, (0.30, 0.72, 1.0, 1))
                node.setLightOff(1)
                node.reparentTo(self.render)
                self.ant_shot_nodes[asid] = node
            node.setPos(sx, sy, sz)
            node.setH((node.getH() + 16) % 360)
            self.particles.burst([sx, sy, sz], count=1, color=(0.35, 0.78, 1.0, 1),
                                 speed=1.4, size=0.2, life=0.45, grav=-0.5, spread=0.5, up=0.25)
        for asid in list(self.ant_shot_nodes):
            if asid not in seen_ashots:
                self.ant_shot_nodes[asid].removeNode()
                del self.ant_shot_nodes[asid]

        # снаряды (сироп - зелёный, майонез - белый)
        seen_shots = set()
        for shot in msg.get("shots", []):
            sid, sx, sy, sz, kind = shot
            seen_shots.add(sid)
            node = self.shot_nodes.get(sid)
            if node is None:
                color = (0.97, 0.97, 0.95, 1) if kind == 1 else (0.45, 1.0, 0.55, 1)
                size = 0.22 + (sid % 3) * 0.04   # лёгкий разнобой = капли жидкости
                node = make_box(size, size, size, color)
                node.reparentTo(self.render)
                self.shot_nodes[sid] = node
            node.setPos(sx, sy, sz)
        for sid in list(self.shot_nodes):
            if sid not in seen_shots:
                self.shot_nodes[sid].removeNode()
                del self.shot_nodes[sid]

        # пчёлы
        seen_bees = set()
        for bee in msg.get("bees", []):
            bid, bx, by, bz = bee
            seen_bees.add(bid)
            node = self.bee_nodes.get(bid)
            if node is None:
                node = make_bee()
                node.reparentTo(self.render)
                self.bee_nodes[bid] = node
            node.setPos(bx, by, bz)
        for bid in list(self.bee_nodes):
            if bid not in seen_bees:
                self.bee_nodes[bid].removeNode()
                del self.bee_nodes[bid]

        # дроп с тараканов (светящиеся кубики-ресурсы)
        import time as _t
        bob = math.sin(_t.time() * 4) * 0.15
        seen_drops = set()
        for drop in msg.get("drops", []):
            did, dx, dy, kind = drop
            seen_drops.add(did)
            node = self.drop_nodes.get(did)
            if node is None:
                node = self._make_drop_node(kind)
                node.reparentTo(self.render)
                self.drop_nodes[did] = node
            node.setPos(dx, dy, 0.6 + bob)
            node.setH((node.getH() + 2) % 360)
        for did in list(self.drop_nodes):
            if did not in seen_drops:
                self.drop_nodes[did].removeNode()
                del self.drop_nodes[did]

        # взрывные снаряды босса (+ огненный трейл)
        seen_bshots = set()
        for bs in msg.get("bshots", []):
            bsid, sx, sy, sz = bs
            seen_bshots.add(bsid)
            node = self.boss_shot_nodes.get(bsid)
            if node is None:
                node = make_box(0.6, 0.6, 0.6, (1.0, 0.35, 0.1, 1))
                node.setLightOff(1)
                node.reparentTo(self.render)
                self.boss_shot_nodes[bsid] = node
            node.setPos(sx, sy, sz)
            self.particles.burst([sx, sy, sz], count=1, color=(1.0, 0.5, 0.1, 1),
                                 speed=1.2, size=0.18, life=0.4, grav=-1.0, spread=0.4, up=0.2)
        for bsid in list(self.boss_shot_nodes):
            if bsid not in seen_bshots:
                self.boss_shot_nodes[bsid].removeNode()
                del self.boss_shot_nodes[bsid]

        # ЩЕЛИ — настенный враг (шкала наполняется майонезом; визуальная полоса)
        self.slit_time = msg.get("slit_time", 0.0)
        seen_slits = set()
        any_filling = False
        fill_pos = None
        for sl in msg.get("slits", []):
            sid, sx, sy, sz, sh, frac, calmed = sl
            seen_slits.add(sid)
            node = self.slit_nodes.get(sid)
            if node is None:
                tex = load_texture(self.loader, AC.SLIT_TEXTURE)
                node = make_slit(scale=1.6, texture=tex)
                node.reparentTo(self.render)
                self.slit_nodes[sid] = node
                bar = WorldBar(self.render, label="ЩЕЛЬ", width=3.0, height=0.4,
                               fill_color=(1.0, 0.85, 0.35, 1),
                               font=self.fonts.get("world"))
                self.slit_bars[sid] = bar
            node.setPos(sx, sy, sz)
            node.setH(sh)
            # звук успокаивания повторяется, пока шкала растёт (в процессе)
            prev = self._slit_prev_frac.get(sid, 0.0)
            if not calmed and frac > prev + 1e-4:
                any_filling = True
                fill_pos = (sx, sy)
            self._slit_prev_frac[sid] = frac
            # шкалу выносим ПЕРЕД стеной (вдоль нормали щели = её «вперёд») и выше
            hr = math.radians(sh)
            fx, fy = -math.sin(hr), math.cos(hr)
            bar = self.slit_bars.get(sid)
            if bar:
                bar.set_pos(sx + fx * 1.4, sy + fy * 1.4, sz + 2.2)
                bar.set_fraction(frac)
            if calmed:
                node.setColorScale(0.45, 1.0, 0.55, 1)
                if bar:
                    bar.set_label("ЩЕЛЬ повержена")
                    bar.set_fill_color((0.4, 1.0, 0.5, 1))
            else:
                import time as _t
                pulse = 0.75 + 0.25 * math.sin(_t.time() * 6)
                node.setColorScale(1.0, pulse, pulse, 1)
                if bar:
                    bar.set_label(f"ЩЕЛЬ - майонез! {int(frac * 100)}%")
        for sid in list(self.slit_nodes):
            if sid not in seen_slits:
                self.slit_nodes[sid].removeNode()
                del self.slit_nodes[sid]
                self._slit_prev_frac.pop(sid, None)
                bar = self.slit_bars.pop(sid, None)
                if bar:
                    bar.destroy()
        # звук удовлетворения щели: при попадании, но только если предыдущий уже доиграл
        if any_filling:
            if self._slit_calm_snd is None:
                self._slit_calm_snd = load_sound(self.loader, AC.SFX_SLIT_CALM)
            s = self._slit_calm_snd
            if s is not None and s.status() != AudioSound.PLAYING:
                s.setVolume(self._vol_at(fill_pos[0], fill_pos[1]) if fill_pos else 1.0)
                s.play()

        # музыка события щелей (первые 20с / последние 10с — разная)
        self._update_slit_music()

        # босс «Папаня» с плавающей визуальной шкалой Уважения над головой
        if self.boss_info:
            if self.boss_node is None:
                self.boss_node = self._make_boss_node()
                self.boss_node.reparentTo(self.render)
                self.boss_bar = WorldBar(self.render, label="ПАПАНЯ", width=3.4,
                                         height=0.44, fill_color=(1.0, 0.85, 0.2, 1),
                                         font=self.fonts.get("world"))
                bx0, by0, bz0 = self.boss_info["pos"]
                h0 = self.boss_info.get("h", 0.0)
                if self._boss_is_model: h0 += AC.BOSS_MODEL_YAW
                self._boss_vis = [bx0, by0, bz0, h0]
            # только данные HUD — позиция/ориентация lerp'ится в _interpolate_entities
            r, mx = self.boss_info["respect"], self.boss_info["max"]
            self.boss_bar.set_fraction(r / mx if mx else 0.0)
            ph = self.boss_info.get("phase", 1)
            self.boss_bar.set_label(f"ПАПАНЯ ({ph} фаза) - {r}/{mx}")
            bx, by, bz = (self._boss_vis or self.boss_info["pos"])[:3]
            if ph == 2:
                self.particles.burst([bx, by, bz + 1.0], count=2,
                                     color=(0.5, 0.92, 0.32, 1), speed=2.2,
                                     size=0.5, life=1.6, grav=-0.6, spread=1.0, up=0.7)
            if r > self._prev_boss_respect and self._boss_hit_cd <= 0:
                self._play_oneshot(AC.SFX_BOSS_HIT, volume=self._vol_at(bx, by))
                self._boss_hit_cd = 0.25
            self._prev_boss_respect = r
        elif self.boss_node is not None:
            self.boss_node.removeNode()
            self.boss_node = None
            if self.boss_bar is not None:
                self.boss_bar.destroy()
                self.boss_bar = None
            self._boss_vis = None
            self._prev_boss_respect = 0

        # второй Папаня (только на волне 9)
        if self.boss2_info:
            if self.boss2_node is None:
                old_flag = self._boss_is_model
                self.boss2_node = self._make_boss_node()
                self._boss2_is_model = self._boss_is_model
                self._boss_is_model = old_flag
                self.boss2_node.reparentTo(self.render)
                self.boss2_bar = WorldBar(self.render, label="ПАПАНЯ", width=3.4,
                                          height=0.44, fill_color=(1.0, 0.85, 0.2, 1),
                                          font=self.fonts.get("world"))
                bx0, by0, bz0 = self.boss2_info["pos"]
                h0 = self.boss2_info.get("h", 0.0)
                if self._boss2_is_model: h0 += AC.BOSS_MODEL_YAW
                self._boss2_vis = [bx0, by0, bz0, h0]
            r, mx = self.boss2_info["respect"], self.boss2_info["max"]
            self.boss2_bar.set_fraction(r / mx if mx else 0.0)
            ph = self.boss2_info.get("phase", 1)
            self.boss2_bar.set_label(f"ПАПАНЯ 2 ({ph} фаза) - {r}/{mx}")
            bx2, by2, bz2 = (self._boss2_vis or self.boss2_info["pos"])[:3]
            if ph == 2:
                self.particles.burst([bx2, by2, bz2 + 1.0], count=2,
                                     color=(0.5, 0.92, 0.32, 1), speed=2.2,
                                     size=0.5, life=1.6, grav=-0.6, spread=1.0, up=0.7)
        elif self.boss2_node is not None:
            self.boss2_node.removeNode()
            self.boss2_node = None
            if self.boss2_bar is not None:
                self.boss2_bar.destroy()
                self.boss2_bar = None
            self._boss2_vis = None

        # улыбающиеся тараканы — обновляем ноды по снапшоту
        self._update_smile_roaches()
        # ЧЕРВЯЧЕЛЛО
        self._update_wormchello_rendering()
        self._update_worm_shots()

    def _update_smile_roaches(self):
        snap_srs = getattr(self, "_last_smile_roaches", [])
        seen = set()
        for sr_data in snap_srs:
            sid, sx, sy, sh_val, shp, *_ = sr_data
            seen.add(sid)
            node = self.smile_roach_nodes.get(sid)
            if node is None:
                from client.procgen import make_smile_roach
                node = make_smile_roach(scale=1.0)
                node.reparentTo(self.render)
                self.smile_roach_nodes[sid] = node
            immune = len(sr_data) > 5 and bool(sr_data[5])
            _si = immune
            if self._smile_immune_prev.get(sid) != _si:
                self._smile_immune_prev[sid] = _si
                if _si:
                    node.setTransparency(TransparencyAttrib.MAlpha)
                    node.setAlphaScale(0.35)
                else:
                    node.setTransparency(TransparencyAttrib.MNone)
                    node.setAlphaScale(1.0)
            node.setPos(sx, sy, 0.0)
            node.setH(sh_val)
        for sid in list(self.smile_roach_nodes):
            if sid not in seen:
                self.smile_roach_nodes[sid].removeNode()
                del self.smile_roach_nodes[sid]
                self._smile_immune_prev.pop(sid, None)

    # ---------------------------------------------------------------- Wormchello

    def _init_wormchello_nodes(self):
        from client.procgen import (make_wormchello_head, make_wormchello_segment,
                                    make_lina_sphere)
        from client.assets import load_texture, texture_exists, load_model
        from common.config import LINA_SPHERE_POSITIONS
        face_tex = None
        if texture_exists(AC.WORMCHELLO_FACE_TEXTURE):
            face_tex = load_texture(self.loader, AC.WORMCHELLO_FACE_TEXTURE)
        hair_mdl = load_model(self.loader, AC.WORMCHELLO_HAIR_MODEL)
        self._wc_head_node = make_wormchello_head(face_tex, hair_model=hair_mdl)
        self._wc_head_node.reparentTo(self.render)
        # 8 сегментов тела (размер уменьшается к хвосту)
        flesh = (0.88, 0.68, 0.54, 1)
        self._wc_seg_nodes = []
        for i in range(8):
            r = max(0.5, 1.2 - i * 0.08)
            seg = make_wormchello_segment(r, flesh)
            seg.reparentTo(self.render)
            seg.hide()
            self._wc_seg_nodes.append(seg)
        # HP-бар
        self.wc_bar = WorldBar(self.render,
                               label="ЧЕРВЯЧЕЛЛО КРЫТОЧЕЛЛО",
                               width=4.2, height=0.46,
                               fill_color=(0.94, 0.45, 0.1, 1),
                               font=self.fonts.get("world"))
        # 4 норы — тёмные диски в полу
        self._spawn_hole_nodes()
        # 4 сферы ЛИНА
        self._wc_lina_nodes = []
        self._wc_lina_bars = []
        for i, (lx, ly, lz) in enumerate(LINA_SPHERE_POSITIONS):
            sph = make_lina_sphere()
            sph.reparentTo(self.render)
            sph.setPos(lx, ly, lz)
            sph.hide()
            self._wc_lina_nodes.append(sph)
            bar = WorldBar(self.render,
                           label=f"LEAN {i+1}",
                           width=1.8, height=0.28,
                           fill_color=(0.25, 0.80, 1.0, 1),
                           font=self.fonts.get("world"))
            bar.set_pos(lx, ly, lz + 2.2)
            bar.set_fraction(1.0)
            self._wc_lina_bars.append(bar)

    def _spawn_hole_nodes(self):
        from client.procgen import make_cylinder
        from common.config import WORMCHELLO_HOLES
        self._wc_hole_nodes = []
        for (hx, hy) in WORMCHELLO_HOLES:
            disc = make_cylinder(2.2, 0.12, 20, (0.04, 0.03, 0.02, 1))
            disc.reparentTo(self.render)
            disc.setPos(hx, hy, 0.05)
            disc.hide()
            self._wc_hole_nodes.append(disc)

    def _clear_wormchello_nodes(self):
        if self._wc_head_node:
            self._wc_head_node.removeNode()
            self._wc_head_node = None
        for seg in self._wc_seg_nodes:
            if seg:
                seg.removeNode()
        self._wc_seg_nodes = []
        if self.wc_bar:
            self.wc_bar.destroy()
            self.wc_bar = None
        for n in self._wc_hole_nodes:
            if n:
                n.removeNode()
        self._wc_hole_nodes = []
        for n in self._wc_lina_nodes:
            if n:
                n.removeNode()
        self._wc_lina_nodes = []
        for b in self._wc_lina_bars:
            if b:
                b.destroy()
        self._wc_lina_bars = []
        self._wc_pos_interp = [0.0, 0.0, -4.0]
        self._wc_h_interp = 0.0
        self._wc_aerial_t = 0.0
        self._wc_cutscene = False
        self._wc_cutscene_t = -1.0

    def _update_wormchello_rendering(self):
        import math as _m
        info = self.wormchello_info
        if not info:
            if self._wc_head_node is not None:
                self._clear_wormchello_nodes()
            return

        if self._wc_head_node is None:
            self._init_wormchello_nodes()

        dt_now = getattr(self, "_last_dt", 0.033)
        self._wc_anim_t += dt_now

        state = info.get("state", "UNDERGROUND")
        px, py, pz = info["pos"]
        hp, max_hp = info["hp"], info["max"]
        ph = info.get("phase", 1)
        trail = info.get("trail", [])
        target_h = info.get("h", 0.0)
        lina_data = info.get("lina", [])

        t = self._wc_anim_t

        # плавная интерполяция позиции и поворота (только когда видно)
        visible = state not in ("UNDERGROUND",)
        if visible:
            lerp = min(1.0, 10.0 * dt_now)
            for i in range(3):
                self._wc_pos_interp[i] += (info["pos"][i] - self._wc_pos_interp[i]) * lerp
            dh = target_h - self._wc_h_interp
            while dh > 180: dh -= 360
            while dh < -180: dh += 360
            self._wc_h_interp += dh * lerp
        else:
            self._wc_pos_interp[:] = list(info["pos"])
            self._wc_h_interp = target_h

        ipx, ipy, ipz = self._wc_pos_interp

        # --- ГОЛОВА ---
        if state == "AERIAL":
            self._wc_aerial_t += dt_now
            max_scale = 6.0
            grow_t = min(1.0, self._wc_aerial_t / 1.5)
            cur_scale = max_scale * grow_t * grow_t
            # медленное вращение во время воздушной фазы
            aerial_h = self._wc_h_interp + 18.0 * _m.sin(t * 0.7)
            aerial_p = 12.0 * _m.sin(t * 1.1)
            self._wc_head_node.show()
            self._wc_head_node.setPos(ipx, ipy, ipz)
            self._wc_head_node.setHpr(aerial_h, aerial_p, 0)
            self._wc_head_node.setScale(max(0.05, cur_scale))
        elif state == "PEEKING" or state == "DESCENDING":
            self._wc_aerial_t = 0.0
            # плавное извивание в дырке: покачивание головой вправо/влево (roll) и
            # лёгкий кивок (pitch) + небольшой сдвиг позиции
            squirm_r = 6.0 * _m.sin(t * 2.3)
            squirm_p = 8.0 * _m.sin(t * 1.7 + 0.9)
            squirm_x = 0.08 * _m.sin(t * 3.1)
            squirm_y = 0.06 * _m.cos(t * 2.5 + 1.2)
            squirm_z = 0.07 * _m.sin(t * 2.0)
            head_h = self._wc_h_interp + 4.0 * _m.sin(t * 1.4)
            self._wc_head_node.show()
            self._wc_head_node.setPos(ipx + squirm_x, ipy + squirm_y, ipz + squirm_z)
            self._wc_head_node.setHpr(head_h, squirm_p, squirm_r)
            self._wc_head_node.setScale(1.0)
        elif state == "SLITHERING":
            self._wc_aerial_t = 0.0
            # лёгкий крен головы в такт движению змеи
            slither_r = 10.0 * _m.sin(t * 4.5)
            slither_p = 5.0 * _m.sin(t * 3.8 + 0.5)
            self._wc_head_node.show()
            self._wc_head_node.setPos(ipx, ipy, ipz)
            self._wc_head_node.setHpr(self._wc_h_interp, slither_p, slither_r)
            self._wc_head_node.setScale(1.0)
        else:
            self._wc_aerial_t = 0.0
            self._wc_head_node.hide()

        # --- ТЕЛО ---
        if state == "SLITHERING":
            # Применяем синусоидальный боковой сдвиг к точкам трейла — snake wiggle.
            # Перпендикуляр к направлению движения вычисляем из соседних точек трейла.
            for i, seg_np in enumerate(self._wc_seg_nodes):
                tidx = 5 + i * 3
                if tidx < len(trail):
                    tx, ty, tz = trail[tidx]
                    # направление движения в данной точке
                    nidx = max(0, tidx - 3)
                    pidx = min(len(trail) - 1, tidx + 3)
                    if nidx != pidx:
                        fdx = trail[nidx][0] - trail[pidx][0]
                        fdy = trail[nidx][1] - trail[pidx][1]
                        fd = _m.hypot(fdx, fdy)
                        if fd > 0.01:
                            # перпендикуляр (право)
                            px_perp = -fdy / fd
                            py_perp =  fdx / fd
                            # бегущая синусоидальная волна: фаза = t*freq - i*0.8
                            wiggle = 0.55 * _m.sin(t * 5.0 - i * 0.9)
                            tx += px_perp * wiggle
                            ty += py_perp * wiggle
                    # лёгкое вертикальное покачивание
                    tz += 0.12 * _m.sin(t * 4.2 - i * 0.7)
                    seg_np.show()
                    seg_np.setPos(tx, ty, tz)
                    # масштаб слегка пульсирует
                    base_scale = max(0.55, 1.1 - i * 0.07)
                    pulse_s = base_scale * (1.0 + 0.06 * _m.sin(t * 5.0 - i * 0.7))
                    seg_np.setScale(pulse_s)
                    # поворот к следующей точке трейла
                    nidx2 = tidx + 3
                    if nidx2 < len(trail):
                        nx_pt, ny_pt = trail[nidx2][0], trail[nidx2][1]
                        dx_s = tx - nx_pt; dy_s = ty - ny_pt
                        if _m.hypot(dx_s, dy_s) > 0.01:
                            seg_np.setH(_m.degrees(_m.atan2(-dx_s, dy_s)))
                else:
                    seg_np.hide()
        elif state == "AERIAL":
            for seg_np in self._wc_seg_nodes:
                seg_np.hide()
        elif state in ("PEEKING", "DESCENDING"):
            # тело висит вертикально ниже головы, с плавным извиванием
            n_show = min(len(self._wc_seg_nodes), 6)
            h_rad = _m.radians(self._wc_h_interp)
            for i, seg_np in enumerate(self._wc_seg_nodes):
                if i >= n_show:
                    seg_np.hide()
                    continue
                seg_z = ipz - (i + 1) * 1.6
                r_scale = max(0.4, 1.0 - i * 0.07)
                # боковой сдвиг в плоскости перпендикулярной направлению
                sway_amp = 0.22 * (1.0 - i / n_show)
                phase_off = i * 0.55
                sway = sway_amp * _m.sin(t * 2.8 + phase_off)
                # перпендикуляр к heading (вправо относительно взгляда)
                sx = -_m.sin(h_rad + _m.pi / 2) * sway
                sy =  _m.cos(h_rad + _m.pi / 2) * sway
                # продольное извивание (вперёд-назад)
                sway2 = 0.12 * _m.sin(t * 3.5 + phase_off + 1.2)
                sx += _m.cos(h_rad) * sway2
                sy += _m.sin(h_rad) * sway2
                seg_np.show()
                seg_np.setPos(ipx + sx, ipy + sy, seg_z)
                seg_np.setScale(r_scale)
                seg_np.setHpr(self._wc_h_interp + 6.0 * _m.sin(t * 2.1 + i * 0.4),
                               4.0 * _m.sin(t * 2.5 - i * 0.3), 0)
        else:
            for seg_np in self._wc_seg_nodes:
                seg_np.hide()

        # --- НОРЫ (показывать пока босс активен, но не во время вступительной кат-сцены) ---
        cs_running = getattr(self, "_wc_cutscene", False)
        if not cs_running:
            for n in self._wc_hole_nodes:
                n.show()

        # --- СФЕРЫ ЛИНА ---
        from common.config import LINA_SPHERE_POSITIONS
        cs_lina_ok = not cs_running or getattr(self, "_wc_cs_lina_shown", False)
        self._wc_lina_pulse_t = getattr(self, "_wc_lina_pulse_t", 0.0)
        self._wc_lina_pulse_t += dt_now
        pulse = 0.85 + 0.15 * _m.sin(self._wc_lina_pulse_t * 3.0)
        for i, (lnode, lbar) in enumerate(zip(self._wc_lina_nodes, self._wc_lina_bars)):
            if i < len(lina_data):
                lhp, lalive = lina_data[i]
            else:
                lhp, lalive = 150, 1
            lx, ly, lz = LINA_SPHERE_POSITIONS[i]
            if lalive:
                if cs_lina_ok:
                    lnode.show()
                lnode.setScale(pulse)
                lbar.set_fraction(max(0.0, lhp / 150.0))
                lbar.set_pos(lx, ly, lz + 2.4)
            else:
                lnode.hide()
                lbar.set_fraction(0.0)

        # --- HP БАР ---
        bar_z = ipz + 5.0 if visible else (self._wc_hole_nodes[0].getZ() + 3 if self._wc_hole_nodes else 5.0)
        bar_x, bar_y = (ipx, ipy) if visible else (px, py)
        self.wc_bar.set_pos(bar_x, bar_y, bar_z)
        self.wc_bar.set_fraction(hp / max_hp if max_hp else 0.0)
        lina_shield = ph == 1 and any((d[1] if len(d) > 1 else 1) for d in lina_data)
        label = f"ЧЕРВЯЧЕЛЛО ({ph} фаза) - {hp}/{max_hp}"
        if lina_shield:
            label += "  [ЩИТ]"
        self.wc_bar.set_label(label)

        # --- ХИТ-ПАРТИКЛЫ ---
        if hp < self._prev_wc_hp and visible:
            self.particles.burst([ipx, ipy, ipz], count=12,
                                 color=(0.95, 0.55, 0.2, 1), speed=5.0,
                                 size=0.3, life=0.6, grav=-6.0, spread=1.2, up=0.8)
            self._play_oneshot(AC.SFX_WORMCHELLO_HIT, volume=self._vol_at(ipx, ipy))
        self._prev_wc_hp = hp

        # фаза 2 AERIAL — нити биомассы сверху
        if state == "AERIAL" and ipz > 8.0:
            self.particles.burst([ipx, ipy, ipz - 1.5], count=3,
                                 color=(0.90, 0.65, 0.45, 1), speed=3.5,
                                 size=0.4, life=1.2, grav=2.0, spread=0.6, up=-1.0)

    def _update_worm_shots(self):
        seen = set()
        for ws_data in getattr(self, "_last_wshots", []):
            # формат: [wsid, x, y, z] или [wsid, x, y, z, kind]
            wsid, wx, wy, wz = ws_data[0], ws_data[1], ws_data[2], ws_data[3]
            wkind = ws_data[4] if len(ws_data) > 4 else 0
            seen.add(wsid)
            node = self.worm_shot_nodes.get(wsid)
            if node is None:
                from client.procgen import make_sphere as _ms
                if wkind == 1:
                    # снаряд ЛИНА — синий светящийся шар
                    node = _ms(0.28, 8, 10, (0.25, 0.80, 1.0, 1))
                    node.setLightOff(1)
                    node.setColorScale(1.6, 1.6, 1.6, 1)
                else:
                    # снаряд ЧЕРВЯЧЕЛЛО — оранжевый кубик
                    from client.primitives import make_box as _mb
                    node = _mb(0.35, 0.35, 0.35, (0.88, 0.55, 0.25, 1))
                    node.setLightOff(1)
                node.reparentTo(self.render)
                self.worm_shot_nodes[wsid] = node
            node.setPos(wx, wy, wz)
        for wsid in list(self.worm_shot_nodes):
            if wsid not in seen:
                self.worm_shot_nodes[wsid].removeNode()
                del self.worm_shot_nodes[wsid]

    def _update_wc_filter(self, dt):
        """Фиолетовый фильтр + кинематографическая кат-сцена ЧЕРВЯЧЕЛЛО."""
        import math as _m
        if not hasattr(self, "_wc_night_overlay"):
            return

        # ---- НЕ ИДЁТ КАТ-СЦЕНА: обычный фиолетовый фильтр ----
        if not self._wc_cutscene:
            target = 0.35 if self.wormchello_info else 0.0
            self._wc_night_alpha += (target - self._wc_night_alpha) * min(1.0, 2.5 * dt)
            if self._wc_night_alpha > 0.005:
                self._wc_night_overlay.setColor(0.08, 0.0, 0.18, self._wc_night_alpha)
                self._wc_night_overlay.show()
            else:
                self._wc_night_overlay.hide()
            return

        # ---- ИДЁТ КАТ-СЦЕНА ----
        self._wc_cutscene_t += dt
        t = self._wc_cutscene_t
        from common.config import LINA_SPHERE_POSITIONS, WORMCHELLO_HOLES

        # центр арены — ориентир камеры
        cx0, cy0, cz0 = 0.0, 0.0, 0.0

        # --- ФАЗА 0 (0..1.8с): затемнение до темноты, стоп-кадр ---
        if t < 1.8:
            a = min(0.95, t / 0.8)
            self._wc_night_alpha = a
            self._wc_night_overlay.setColor(0.05, 0.0, 0.12, a)
            self._wc_night_overlay.show()
            if hasattr(self, "hud_root"):
                self.hud_root.hide()
            return

        # с этого момента HUD скрыт, ночной фильтр держим на 0.40
        self._wc_night_alpha = 0.40
        self._wc_night_overlay.setColor(0.08, 0.0, 0.18, 0.40)
        self._wc_night_overlay.show()

        # --- ФАЗА 1 (1.8..5с): камера облетает центральную арену сверху ---
        if t < 5.0:
            frac = (t - 1.8) / 3.2
            angle = _m.radians(60 + frac * 120)
            r = 28.0
            cam_x = cx0 + _m.cos(angle) * r
            cam_y = cy0 + _m.sin(angle) * r * 0.75
            cam_z = 14.0 + frac * 4.0
            self.camera.setPos(cam_x, cam_y, cam_z)
            self.camera.lookAt(cx0, cy0, 1.5)
            self.camera.setR(0)
            return

        # --- ФАЗА 2 (5..7с): камера опускается к дырам в полу, дыры появляются ---
        if t < 7.0:
            frac = (t - 5.0) / 2.0
            angle = _m.radians(180 + frac * 40)
            r = 22.0 - frac * 8.0
            cam_x = cx0 + _m.cos(angle) * r
            cam_y = cy0 + _m.sin(angle) * r
            cam_z = 14.0 - frac * 8.0
            self.camera.setPos(cam_x, cam_y, cam_z)
            self.camera.lookAt(cx0, cy0, 0.0)
            self.camera.setR(0)
            # t=5.2: дыры в полу
            if not self._wc_cs_holes_shown:
                self._wc_cs_holes_shown = True
                for n in self._wc_hole_nodes:
                    n.show()
                for (hx, hy) in WORMCHELLO_HOLES:
                    self.particles.burst([hx, hy, 0.2], count=25,
                                         color=(0.38, 0.28, 0.12, 1), speed=6.0,
                                         size=0.32, life=1.1, grav=-6.0, spread=1.2, up=1.4)
                self._shake(0.8)
            # t=5.8: сферы LEAN
            if t >= 5.8 and not self._wc_cs_lina_shown:
                self._wc_cs_lina_shown = True
                self._show_notice("Уничтожь сферы LEAN!", color=(0.3, 0.85, 1.0, 1), duration=5.0)
                for i, n in enumerate(self._wc_lina_nodes):
                    n.show()
                    lx, ly, lz = LINA_SPHERE_POSITIONS[i]
                    self.particles.burst([lx, ly, lz], count=22,
                                         color=(0.3, 0.75, 1.0, 1), speed=5.5,
                                         size=0.35, life=1.1, grav=-5.0, spread=1.4, up=1.0)
                self._shake(0.5)
            return

        # --- ФАЗА 3 (7..9с): анонс имени, финальная вспышка ---
        if t < 9.0:
            frac = (t - 7.0) / 2.0
            self.camera.setPos(cx0, cy0 - 24, 8.0 + frac * 6.0)
            self.camera.lookAt(cx0, cy0, 1.5)
            self.camera.setR(0)
            if not self._wc_cs_announced:
                self._wc_cs_announced = True
                self._show_notice("ЧЕРВЯЧЕЛЛО КРЫТОЧЕЛЛО!", color=(0.95, 0.45, 0.1, 1), duration=5.0)
                self._flash_screen((0.1, 0.0, 0.25, 1), 1.2, hold=0.3)
                self._shake(0.5)
            return

        # --- КОНЕЦ КАТ-СЦЕНЫ (>= 9с) ---
        self._wc_cutscene = False
        self._wc_cutscene_t = -1.0
        self._wc_night_alpha = 0.35
        if hasattr(self, "local_worm"):
            self.local_worm.root.unstash()
        if hasattr(self, "hud_root"):
            self.hud_root.show()

    def _wormchello_cutscene(self, msg):
        """Кат-сцена появления ЧЕРВЯЧЕЛЛО КРЫТОЧЕЛЛО (9с с кинематографической камерой)."""
        # инициализировать ноды если ещё нет
        if self._wc_head_node is None:
            self._init_wormchello_nodes()

        # скрыть — будут показаны поэтапно в _update_wc_filter
        for n in self._wc_hole_nodes:
            n.hide()
        for n in self._wc_lina_nodes:
            n.hide()

        self._prev_wc_hp = 2000

        # сброс флагов
        self._wc_cs_lina_shown = False
        self._wc_cs_holes_shown = False
        self._wc_cs_announced = False

        # сташируем червя и скрываем HUD (как в BK кат-сцене)
        if hasattr(self, "local_worm"):
            self.local_worm.root.stash()
        if hasattr(self, "hud_root"):
            self.hud_root.hide()

        # немедленные эффекты
        self._shake(0.7)
        self._play_oneshot(AC.SFX_WORMCHELLO_SPAWN)
        self._play_music(AC.MUSIC_WORMCHELLO)

        # запуск кат-сцены
        self._wc_cutscene = True
        self._wc_cutscene_t = 0.0

    def _update_cup_spots(self, spots):
        """Показать поставленные белые стаканы на 4 угловых пьедесталах."""
        if not self.cup_spot_nodes:
            for (sx, sy) in CUP_SPOTS:
                node = make_cup(scale=1.3)
                node.setPos(sx, sy, 0.9)
                node.reparentTo(self.render)
                node.hide()
                self.cup_spot_nodes.append(node)
        for i, node in enumerate(self.cup_spot_nodes):
            if i < len(spots) and spots[i]:
                node.show()
            else:
                node.hide()

    def _make_drop_node(self, kind):
        """Узел дропа: 3D-модель по типу (honey/syrup/mayo/lit_energy); нет файла — кубик."""
        if kind == "cup":
            return make_cup(scale=1.1)      # процедурный белый стакан
        path = AC.DROP_MODELS.get(kind)
        if path:
            model = load_model(self.loader, path)
            if model and not model.isEmpty():
                holder = NodePath(f"{kind}_drop")
                inst = model.copyTo(holder)        # копия (кэш не мутируем)
                inst.clearTransform()
                lo, hi = inst.getTightBounds()
                h = max(0.01, hi.z - lo.z)
                s = 1.2 / h                         # нормализуем по высоте ~1.2 ед.
                inst.setScale(s)
                inst.setPos(-(lo.x + hi.x) * 0.5 * s, -(lo.y + hi.y) * 0.5 * s, -lo.z * s)
                if kind == "lit_energy":
                    holder.setLightOff(1)           # LIT ENERGY светится
                return holder
        node = make_box(0.4, 0.4, 0.4, DROP_COLORS.get(kind, (1, 1, 1, 1)))
        node.setLightOff(1)        # «светится»
        return node

    def _make_boss_node(self, target_height=6.0):
        """Узел босса: модель из papich (если валидна) либо процедурный таракан-босс."""
        model = load_model(self.loader, AC.BOSS_MODEL)
        if model and not model.isEmpty():
            holder = self.render.attachNewNode("boss_model")
            # РАБОЧАЯ КОПИЯ: кэшированную модель НЕ мутируем (иначе при 2-м появлении
            # getTightBounds вернёт уже отмасштабированные границы -> босс «усыхает»).
            inst = model.copyTo(holder)
            inst.clearTransform()                  # мерим геометрию без чужого масштаба
            lo, hi = inst.getTightBounds()
            h = max(0.01, hi.z - lo.z)
            s = target_height / h
            inst.setScale(s)
            # поставить на землю и отцентрировать по XY
            inst.setPos(-(lo.x + hi.x) * 0.5 * s, -(lo.y + hi.y) * 0.5 * s, -lo.z * s)
            holder.setTwoSided(True)                          # видны «вывернутые» грани (лицо)
            holder.setTransparency(TransparencyAttrib.MNone, 1)  # принудительно непрозрачно
            self._boss_is_model = True
            return holder
        self._boss_is_model = False
        return make_boss(scale=3.0)   # fallback: процедурная модель

    def _update_bk_rendering(self):
        """Рендер BLACK KING из снапшота: создание/удаление узла + HUD. Позиция lerp'ится."""
        if self.bk_boss_info:
            if self.bk_boss_node is None:
                self.bk_boss_node = self._make_bk_boss_node()
                self.bk_boss_node.reparentTo(self.render)
                self.bk_boss_bar = WorldBar(self.render, label="BLACK KING", width=3.8,
                                             height=0.44, fill_color=(0.6, 0.0, 1.0, 1),
                                             font=self.fonts.get("world"))
                bx0, by0, bz0 = self.bk_boss_info["pos"]
                h0 = self.bk_boss_info.get("h", 0.0)
                if self._bk_is_model: h0 += AC.BLACK_KING_MODEL_YAW
                self._bk_boss_vis = [bx0, by0, bz0, h0]
            hp, mx = self.bk_boss_info["hp"], self.bk_boss_info["max_hp"]
            bx, by, bz = (self._bk_boss_vis or self.bk_boss_info["pos"])[:3]
            self.bk_boss_bar.set_pos(bx, by, bz + 6.0)
            self.bk_boss_bar.set_fraction(hp / mx if mx else 0.0)
            self.bk_boss_bar.set_label(f"BLACK KING - {hp}/{mx}")
            self.particles.burst([bx, by, bz + 1.5], count=2,
                                 color=(0.55, 0.0, 1.0, 1), speed=2.5,
                                 size=0.5, life=1.4, grav=-0.4, spread=1.0, up=0.8)
        elif self.bk_boss_node is not None:
            self.bk_boss_node.removeNode()
            self.bk_boss_node = None
            if self.bk_boss_bar is not None:
                self.bk_boss_bar.destroy()
                self.bk_boss_bar = None
            self._bk_boss_vis = None
            self._prev_bk_hp = C.BLACK_KING_HP

    def _make_bk_boss_node(self, target_height=6.0):
        """Узел BLACK KING: модель black_king.glb или тёмный процедурный таракан."""
        model = load_model(self.loader, AC.BLACK_KING_MODEL)
        if model and not model.isEmpty():
            holder = self.render.attachNewNode("bk_boss_model")
            inst = model.copyTo(holder)
            inst.clearTransform()
            lo, hi = inst.getTightBounds()
            h = max(0.01, hi.z - lo.z)
            s = target_height / h
            inst.setScale(s)
            inst.setPos(-(lo.x + hi.x) * 0.5 * s, -(lo.y + hi.y) * 0.5 * s, -lo.z * s)
            holder.setTwoSided(True)
            holder.setTransparency(TransparencyAttrib.MNone, 1)
            self._bk_is_model = True
            return holder
        self._bk_is_model = False
        node = make_cockroach(body_color=(0.08, 0.0, 0.18, 1), scale=3.2)
        node.setLightOff(1)
        node.setColorScale(0.5, 0.0, 0.9, 1)
        return node

    def _make_bk_minion_node(self):
        """Маленькая копия BLACK KING: уменьшенная модель или процедурный мини-таракан."""
        model = load_model(self.loader, AC.BLACK_KING_MODEL)
        if model and not model.isEmpty():
            holder = NodePath("bk_minion")
            inst = model.copyTo(holder)
            inst.clearTransform()
            lo, hi = inst.getTightBounds()
            h = max(0.01, hi.z - lo.z)
            s = 2.0 / h
            inst.setScale(s)
            inst.setPos(-(lo.x + hi.x) * 0.5 * s, -(lo.y + hi.y) * 0.5 * s, -lo.z * s)
            holder.setTwoSided(True)
            holder.setTransparency(TransparencyAttrib.MNone, 1)
            return holder
        return make_bk_minion()

    def _start_bk_death_cutscene(self, x, y):
        """Запустить кат-сцену гибели BLACK KING: уходит под землю у центральной башни."""
        self._bk_death_cs = True
        self._bk_death_t = 0.0
        # фиксированная позиция у северного края центральной башни — всегда видна
        self._bk_death_pos = (0.0, -6.0)
        self.hud_root.hide()
        # фиолетовый фильтр держим активным: кат-сцена + вспышка (через _bk_filter_keep)
        self._bk_filter_keep = True
        self._bk_night_alpha = max(self._bk_night_alpha, 0.38)
        self._bk_night_overlay.setColor(0.05, 0.0, 0.12, self._bk_night_alpha)
        self._bk_night_overlay.show()
        # создаём копию модели специально для кат-сцены
        self._bk_death_node = self._make_bk_boss_node()
        self._bk_death_node.reparentTo(self.render)
        self._bk_death_node.setPos(x, y, 0.0)
        # сбрасываем живой узел — чтобы не мешал
        if self.bk_boss_node:
            self.bk_boss_node.hide()

    def _update_bk_death_cutscene(self, dt):
        if not self._bk_death_cs:
            return
        import random as _r
        DURATION = 5.0
        self._bk_death_t += dt
        t = self._bk_death_t
        x, y = self._bk_death_pos

        # камера — с юга, смотрит на центральную башню и тонущего BK
        frac = min(1.0, t / DURATION)
        cam_z = 8.0 + 6.0 * (1.0 - frac)
        cam_d = 16.0 - 8.0 * frac   # приближается по мере погружения
        self.camera.setPos(x, y - cam_d, cam_z)
        self.camera.lookAt(x, y, 1.5)

        # модель тонет под землю
        sink = max(-7.0, -frac * 7.0)
        if self._bk_death_node and not self._bk_death_node.isEmpty():
            self._bk_death_node.setPos(x, y, sink)
            self._bk_death_node.setH(self._bk_death_node.getH() + 60.0 * dt)
            # фиолетово-чёрные частицы разлетаются
            if int(t * 8) % 2 == 0:
                self.particles.burst([x + _r.uniform(-1, 1), y + _r.uniform(-1, 1), max(0.1, sink + 1)],
                                     count=6, color=(0.4, 0.0, 0.8, 1), speed=4.0,
                                     size=0.5, life=1.2, grav=-2.0, spread=1.5, up=0.6)

        if t >= DURATION:
            # кат-сцена завершена
            self._bk_death_cs = False
            if self._bk_death_node and not self._bk_death_node.isEmpty():
                self._bk_death_node.removeNode()
            self._bk_death_node = None
            self._flash_screen((1.0, 0.9, 0.0, 1), duration=2.0, hold=0.5)
            self._shake(1.2)
            self.hud_root.show()
            # музыка и фильтр меняются только ПОСЛЕ окончания вспышки (+2.5с)
            def _bk_phase_end(task):
                self._play_music(AC.MUSIC_PHASE1)
                self._bk_filter_keep = False  # теперь idle-ветка плавно гасит фильтр
                return task.done
            self.taskMgr.doMethodLater(2.5, _bk_phase_end, "bk_death_phase_end")

    def _start_bk_wipe_sink(self, event_msg):
        """Анимация погружения при bk_wipe: BK и миньоны уходят под землю за 3с."""
        import random as _r
        self._bk_wipe_sinking = []
        self._bk_wipe_t = 0.0

        # взять живой узел BK (если есть) и передать в список погружения
        if self.bk_boss_node and not self.bk_boss_node.isEmpty():
            p = self.bk_boss_node.getPos()
            self._bk_wipe_sinking.append((self.bk_boss_node, p.x, p.y, p.z))
            self.bk_boss_node = None   # отвязать от нормального обновления

        # взять узлы миньонов
        for mid, mnode in list(self.bk_minion_nodes.items()):
            if mnode and not mnode.isEmpty():
                p = mnode.getPos()
                self._bk_wipe_sinking.append((mnode, p.x, p.y, p.z))
        self.bk_minion_nodes.clear()

        # убрать HP-шкалу BK
        if self.bk_boss_bar is not None:
            self.bk_boss_bar.destroy()
            self.bk_boss_bar = None

    def _update_bk_wipe(self, dt):
        """Обновление анимации погружения при bk_wipe."""
        if not self._bk_wipe_sinking:
            return
        import random as _r
        SINK_DUR = 3.0
        self._bk_wipe_t += dt
        t = self._bk_wipe_t
        frac = min(1.0, t / SINK_DUR)
        alive = []
        for node, x, y, z0 in self._bk_wipe_sinking:
            if node.isEmpty():
                continue
            sink_z = z0 - frac * 8.0
            node.setPos(x, y, sink_z)
            node.setH(node.getH() + 45.0 * dt)
            if int(t * 6) % 2 == 0:
                self.particles.burst([x, y, max(-0.5, sink_z + 0.5)], count=3,
                                     color=(0.4, 0.0, 0.7, 1), speed=3.0,
                                     size=0.35, life=0.9, grav=-2.0, spread=1.2, up=0.4)
            if t < SINK_DUR:
                alive.append((node, x, y, z0))
            else:
                node.removeNode()
        self._bk_wipe_sinking = alive

    def _update_remotes(self, dt):
        for av in self.remote.values():
            av.lerp_step(dt)

    def _interpolate_entities(self, dt):
        """Плавное движение сущностей между снапшотами (каждый кадр, не 30 Гц)."""
        a = min(1.0, 15.0 * dt)   # ~67мс до полного совпадения при 60fps
        a_boss = min(1.0, 10.0 * dt)  # боссы медленнее — чуть более плавно

        def _lerp3(v, t, alpha):
            v[0] += (t[0] - v[0]) * alpha
            v[1] += (t[1] - v[1]) * alpha
            v[2] += (t[2] - v[2]) * alpha

        def _lerp_h(cur_h, tgt_h, alpha):
            dh = tgt_h - cur_h
            while dh > 180: dh -= 360
            while dh < -180: dh += 360
            return cur_h + dh * alpha

        # --- Тараканы ---
        for aid, node in self.ant_nodes.items():
            t = self._ant_target.get(aid)
            v = self._ant_vis.get(aid)
            if t is None or v is None:
                continue
            ox, oy = v[0], v[1]
            _lerp3(v, t, a)
            node.setPos(v[0], v[1], v[2])
            dx, dy = v[0] - ox, v[1] - oy
            if dx * dx + dy * dy > 1e-6:
                node.setH(math.degrees(math.atan2(-dx, dy)))

        # --- Нео-муравьи ---
        for nid, node in self.neon_ant_nodes.items():
            t = self._neon_target.get(nid)
            v = self._neon_vis.get(nid)
            if t is None or v is None:
                continue
            _lerp3(v, t, a)
            v[3] = _lerp_h(v[3], t[3], a)
            node.setPos(v[0], v[1], v[2])
            node.setH(v[3])
            # HP-бар следует за визуальной позицией
            bar = self._neon_hp_bars.get(nid)
            if bar:
                bar.set_pos(v[0], v[1], 2.4)

        # --- BK-миньоны ---
        for mid, node in self.bk_minion_nodes.items():
            t = self._bkm_target.get(mid)
            v = self._bkm_vis.get(mid)
            if t is None or v is None:
                continue
            _lerp3(v, t, a)
            node.setPos(v[0], v[1], v[2])

        # --- Папаня (босс) ---
        if self.boss_info and self.boss_node and self._boss_vis:
            tx, ty, tz = self.boss_info["pos"]
            th = self.boss_info.get("h", 0.0)
            if self._boss_is_model: th += AC.BOSS_MODEL_YAW
            v = self._boss_vis
            _lerp3(v, [tx, ty, tz], a_boss)
            v[3] = _lerp_h(v[3], th, a_boss)
            self.boss_node.setPos(v[0], v[1], v[2])
            self.boss_node.setH(v[3])
            self.boss_bar.set_pos(v[0], v[1], v[2] + 5.5)

        # --- Папаня 2 ---
        if self.boss2_info and self.boss2_node and self._boss2_vis:
            tx, ty, tz = self.boss2_info["pos"]
            th = self.boss2_info.get("h", 0.0)
            if self._boss2_is_model: th += AC.BOSS_MODEL_YAW
            v = self._boss2_vis
            _lerp3(v, [tx, ty, tz], a_boss)
            v[3] = _lerp_h(v[3], th, a_boss)
            self.boss2_node.setPos(v[0], v[1], v[2])
            self.boss2_node.setH(v[3])
            self.boss2_bar.set_pos(v[0], v[1], v[2] + 5.5)

        # --- BLACK KING ---
        if self.bk_boss_info and self.bk_boss_node and self._bk_boss_vis:
            tx, ty, tz = self.bk_boss_info["pos"]
            th = self.bk_boss_info.get("h", 0.0)
            if self._bk_is_model: th += AC.BLACK_KING_MODEL_YAW
            v = self._bk_boss_vis
            _lerp3(v, [tx, ty, tz], a_boss)
            v[3] = _lerp_h(v[3], th, a_boss)
            self.bk_boss_node.setPos(v[0], v[1], v[2])
            self.bk_boss_node.setH(v[3])
            if self.bk_boss_bar:
                self.bk_boss_bar.set_pos(v[0], v[1], v[2] + 6.0)

    def _update_bk_cutscene(self, dt):
        """Кат-сцена призыва BLACK KING (12 секунд): тёмно-фиолетовый фильтр,
        кинематографическая камера, вращающиеся стаканы со струями сиропа."""
        import math as _m
        import random as _r

        # когда спавн кат-сцена не идёт — плавно анимировать ночной фильтр
        if not self._bk_cutscene:
            # фильтр держится: активен BK, или death кат-сцена, или ещё идёт вспышка
            keep = self.black_king or self._bk_death_cs or self._bk_filter_keep
            target_a = 0.38 if keep else 0.0
            self._bk_night_alpha += (target_a - self._bk_night_alpha) * min(1.0, 3.0 * dt)
            if self._bk_night_alpha > 0.005:
                self._bk_night_overlay.setColor(0.05, 0.0, 0.12, self._bk_night_alpha)
                self._bk_night_overlay.show()
            else:
                self._bk_night_overlay.hide()
            return

        self._bk_cutscene_t += dt
        t = self._bk_cutscene_t

        # позиция BLACK KING (из снапшота или северный спавн по умолчанию)
        bx = self.bk_boss_info["pos"][0] if self.bk_boss_info else 0.0
        by = self.bk_boss_info["pos"][1] if self.bk_boss_info else 38.0
        bz = self.bk_boss_info["pos"][2] if self.bk_boss_info else 0.0

        # --- ФАЗА 0 (0..1.5с): затемнение до полной тьмы ---
        if t < 1.5:
            a = min(1.0, t / 0.7)
            self._bk_night_overlay.show()
            self._bk_night_overlay.setColor(0.03, 0.0, 0.08, a * 0.98)
            self._bk_night_alpha = a * 0.98
            self.local_worm.root.stash()   # прятать червя во время кат-сцены
            if hasattr(self, "hud_root"):
                self.hud_root.hide()       # HUD скрыт во время кат-сцены
            return

        # кат-сцена: фиолетовая ночь на ~0.40 альфа
        self._bk_night_alpha = 0.40
        self._bk_night_overlay.setColor(0.05, 0.0, 0.12, 0.40)
        self._bk_night_overlay.show()

        # --- ФАЗА 1 (1.5..5с): боковая камера, медленный облёт ---
        if t < 5.0:
            frac = (t - 1.5) / 3.5
            angle = _m.radians(55 + frac * 30)
            r = 20.0
            cx = bx + _m.cos(angle) * r
            cy = by + _m.sin(angle) * r * 0.7
            self.camera.setPos(cx, cy, bz + 5.5)
            self.camera.lookAt(bx, by, bz + 2.5)
            self.camera.setR(0)
            return

        # --- ФАЗА 2 (5..8с): переход в изометрию ---
        if t < 8.0:
            frac = (t - 5.0) / 3.0
            frac3 = frac ** 2   # ускоряющаяся анимация
            angle = _m.radians(85 + frac3 * 10)
            r = 18.0 + frac3 * 8.0
            cz_off = 5.5 + frac3 * 16.0
            cx = bx + _m.cos(angle) * r
            cy = by + _m.sin(angle) * r * 0.5
            self.camera.setPos(cx, cy, bz + cz_off)
            self.camera.lookAt(bx, by, bz + 1.5)
            self.camera.setR(0)
            return

        # --- ФАЗА 3 (8..12с): низкий угол с юга, стаканы вращаются с ускорением ---
        if t < 12.0:
            # камера строго с юга, низко — boss arena открыта, карта не мешает
            self.camera.setPos(bx, by - 22, bz + 3.5)
            self.camera.lookAt(bx, by + 3, bz + 2.5)
            self.camera.setR(0)
            # вращение стаканов (ускоряющееся)
            frac = (t - 8.0) / 4.0
            cup_r = 5.0
            rot_speed = 60 + frac * 300   # градусов/сек, быстро ускоряется
            total_rot = (t - 8.0) * (60 + frac * 150)  # интеграл угловой скорости
            for i, cup_node in enumerate(self._bk_cup_nodes):
                ang = _m.radians(i * 90 + total_rot)
                cx2 = bx + _m.cos(ang) * cup_r
                cy2 = by + _m.sin(ang) * cup_r
                cup_node.setPos(cx2, cy2, 0.5)
                cup_node.setH(_m.degrees(ang) + 90)
                cup_node.show()
                # струи зелёного сиропа от стакана к боссу (каждые ~0.12с)
                if int(t / 0.12) != int((t - dt) / 0.12):
                    dx = bx - cx2; dy = by - cy2
                    dn = _m.hypot(dx, dy) or 1.0
                    # несколько частиц вдоль луча от стакана к боссу
                    for step_frac in (0.2, 0.5, 0.8):
                        px = cx2 + dx * step_frac
                        py = cy2 + dy * step_frac
                        self.particles.burst([px, py, 0.6], count=2,
                                             color=(0.35, 1.0, 0.15, 1), speed=2.0,
                                             size=0.18, life=0.5, grav=-3.0,
                                             spread=0.3, up=0.3)
            # нарастающий белый блик перед концом
            if t >= 11.0:
                flash_t = (t - 11.0) / 1.0
                self._bk_night_overlay.setColor(
                    0.05 + flash_t * 0.95, flash_t * 0.95, 0.12 + flash_t * 0.88,
                    0.40 + flash_t * 0.60)
            return

        # --- КОНЕЦ КАТ-СЦЕНЫ (>= 12с) ---
        for n in self._bk_cup_nodes:
            n.removeNode()
        self._bk_cup_nodes = []
        self._bk_cutscene = False
        self._bk_night_alpha = 0.40
        self._bk_night_overlay.setColor(0.05, 0.0, 0.12, 0.40)
        self.local_worm.root.unstash()
        if hasattr(self, "hud_root"):
            self.hud_root.show()   # вернуть HUD
        # кат-сцена завершена — камера вернулась к игроку, волны начнутся с сервера
        self._show_notice("BLACK KING АКТИВЕН!  УНИЧТОЖЬ ЕГО!",
                          color=(0.9, 0.0, 1.0, 1), duration=4.0)
        self._flash_screen((1.0, 1.0, 1.0, 1.0), duration=1.6, hold=0.25)
        self._shake(0.6)

    def _update_hud(self):
        import time as _t
        snap = getattr(self, "_my_snapshot", None)
        hp = snap["hp"] if snap else C.PLAYER_MAX_HP
        score = snap["score"] if snap else 0
        deaths = snap["deaths"] if snap else 0
        online = len(self.remote) + (1 if self.my_id else 0)
        wnames = {"syrup": "СИРОП", "mayo": "МАЙОНЕЗ", "hive": "ПЧЁЛЫ"}
        wcolors = {"syrup": (0.45, 1.0, 0.55, 1), "mayo": (0.97, 0.97, 0.92, 1),
                   "hive": (1.0, 0.85, 0.2, 1)}

        # HP (низ-слева) + цвет от количества
        self.hp_node.setText(f"{int(hp)}")
        frac = max(0.0, min(1.0, hp / C.PLAYER_MAX_HP))
        self.hp_node.setTextColor(1.0, 0.3 + 0.6 * frac, 0.3 + 0.5 * frac, 1)

        # Очки/смерти (верх-слева)
        self.score_node.setText(f"Очки: {score}   Смертей: {deaths}")
        # Онлайн (верх-справа)
        self.online_node.setText(f"Онлайн: {online}")

        # Единая иконка текущего оружия — обновлять только при смене
        if self.weapon != self._w_prev:
            self._w_prev = self.weapon
            _wtex = self._w_icon_textures.get(self.weapon)
            _wcol = self._w_icon_colors.get(self.weapon, (1, 1, 1, 1))
            if _wtex:
                self._w_icon_bg.setTexture(_wtex, 1)
                self._w_icon_bg.setColor(1, 1, 1, 0.92)
            else:
                self._w_icon_bg.clearTexture()
                self._w_icon_bg.setColor(*_wcol[:3], 0.72)
            _wnames = {"syrup": "СИРОП", "mayo": "МАЙО", "hive": "ПЧЁЛЫ"}
            _wkeys  = {"syrup": "[1]",   "mayo": "[2]",  "hive": "[3]"}
            self._w_label.setText(_wnames.get(self.weapon, self.weapon.upper()))
            self._w_label.setTextColor(*_wcol)
            self._w_key_node.setText(_wkeys.get(self.weapon, ""))

        # доп. строка: LIT ENERGY / таймер пчёл / стаканы / ГАЗ
        gas = " +ГАЗ" if self.keys.get("gas", False) else ""
        extra_parts = []
        if self.bee_time > 0:
            extra_parts.append(f"ПЧЁЛЫ: {self.bee_time:.0f}с{gas}")
        elif gas:
            extra_parts.append(gas.strip())
        extra_parts.append(f"LIT: {self.lit_energy}")
        if self.cups > 0:
            extra_parts.append(f"Стаканы: {self.cups}")
        self.weapon_node.setText("  ".join(extra_parts))

        # центральная подсказка про стакан (только когда рядом свободный пьедестал)
        if self.cups > 0 and any(
            not taken and math.hypot(self.pos.x - cx, self.pos.y - cy) <= 4.5
            for (cx, cy), taken in zip(CUP_SPOTS, self.cup_spots)
        ):
            self.cup_hint_node.setText("[R]  поставить стакан")
        else:
            self.cup_hint_node.setText("")

        phase = f"ФАЗА 1: ТРАВЛЯ - Волна {self.wave} (тараканов: {self.alive_ants})"
        if getattr(self, "neon_alive", 0):
            phase += f" + синих стрелков: {self.neon_alive}"
        if self.boss_info:
            r, m = self.boss_info["respect"], self.boss_info["max"]
            ph = self.boss_info.get("phase", 1)
            phase += f"  |  ПАПАНЯ (фаза {ph}) - {r}/{m}"
        if self.black_king:
            if self.bk_boss_info:
                hp, mx = self.bk_boss_info["hp"], self.bk_boss_info["max_hp"]
                bk_ph = self.bk_boss_info.get("phase", 1)
                bk_label = "ФАЗА 2 - ЛАЗЕРЫ" if bk_ph == 2 else "ФАЗА 1"
                phase += f"  |  BLACK KING [{bk_label}] - {hp}/{mx}"
            else:
                phase += "  |  BLACK KING ПОВЕРЖЕН"
        self.phase_node.setText(phase)

        # предупреждение о щелях с обратным отсчётом (пусто -> ничего не видно)
        if getattr(self, "slit_time", 0.0) > 0.0:
            self.slit_node.setText(f"ЩЕЛЬ! Залейте майонезом (2): {self.slit_time:.0f}с")
        else:
            self.slit_node.setText("")


def main():
    parser = argparse.ArgumentParser(description="Клиент SWAGA")
    parser.add_argument("--name",   default="Игрок",   help="имя игрока (переопределяется auth)")
    parser.add_argument("--host",   default=C.HOST,    help="адрес игрового сервера")
    parser.add_argument("--port",   type=int, default=C.PORT, help="порт игрового сервера")
    parser.add_argument("--auth",   default="",        help="адрес auth-сервера (HOST:PORT)")
    args = parser.parse_args()

    app = Roblox2(args.name, args.host, args.port, auth_server=args.auth)
    app.run()


if __name__ == "__main__":
    main()
