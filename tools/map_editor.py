"""Редактор карт SWAGA (инструмент разработчика).

Запуск:   python -m tools.map_editor maps/моя_карта.json
          python -m tools.map_editor maps/новая.json --empty   (пустая карта)
Нет файла -> создаётся копия встроенной арены (или пустая с --empty).

Управление (см. F1 в редакторе):
  Камера:  ПКМ-драг — вращение, WASD — панорама, колесо — зум, Shift — быстрее
  Инструменты: Esc — выбор, 1 стена, 2 платформа, 3 ковёр, 4 джамп-пад,
               5 пьедестал стакана, 6 витрина, 7 спавн игроков, 8 спавн босса
  ЛКМ — выбрать / поставить;  G — перенос выбранного (ЛКМ/G — подтвердить)
  Стрелки — сдвиг;  Shift+стрелки — размер;  Q/E — высота платформы
  T — текстура, Y — цвет, U/I — масштаб UV, K — флаг ЩЕЛИ (стена)
  Del — удалить, Ctrl+D — дубликат, Ctrl+Z — undo, Ctrl+S — сохранить
  9 — шаг привязки;  B — периметр, L — лампы, N/M — высота стен, ,/. — размер мира
"""

import argparse
import json
import math
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from panda3d.core import (AmbientLight, DirectionalLight, LineSegs, NodePath,
                          Point3, TextNode, TransparencyAttrib, Vec3,
                          loadPrcFileData)

loadPrcFileData("", "window-title SWAGA MAP EDITOR")
loadPrcFileData("", "win-size 1440 860")
loadPrcFileData("", "audio-library-name null")

from direct.showbase.ShowBase import ShowBase

from common import mapformat
from client.primitives import make_box
from client.procgen import make_cylinder
from client.assets import load_texture, texture_exists
from client.citymap import (CARPET, WALLPAPER, WALLPAPER_DARK, LIGHT_PANEL,
                            JUMP_PAD, PLATFORM_TOP, PLATFORM_EDGE, SKY)

ARIAL = r"C:\Windows\Fonts\arial.ttf"

# палитра цветов (Y): None = цвет по умолчанию
COLOR_PRESETS = [
    None,
    [0.74, 0.63, 0.27, 1.0],   # жёлтые обои
    [0.57, 0.48, 0.20, 1.0],   # тёмные обои
    [0.46, 0.40, 0.16, 1.0],   # ковролин
    [0.55, 0.12, 0.12, 1.0],   # тёмно-красный
    [0.15, 0.25, 0.55, 1.0],   # синий
    [0.14, 0.42, 0.20, 1.0],   # зелёный
    [0.20, 0.20, 0.22, 1.0],   # почти чёрный
    [0.85, 0.85, 0.82, 1.0],   # белёсый
    [0.45, 0.20, 0.55, 1.0],   # фиолетовый
]

TOOL_KEYS = {
    "1": "wall", "2": "platform", "3": "carpet", "4": "jump_pad",
    "5": "cup_spot", "6": "structure", "7": "spawn", "8": "boss_spawn",
}
TOOL_TITLES = {
    "select": "ВЫБОР", "wall": "СТЕНА", "platform": "ПЛАТФОРМА",
    "carpet": "КОВЁР", "jump_pad": "ДЖАМП-ПАД", "cup_spot": "ПЬЕДЕСТАЛ",
    "structure": "ВИТРИНА", "spawn": "СПАВН ИГРОКОВ", "boss_spawn": "СПАВН БОССА",
}

HELP_TEXT = """SWAGA MAP EDITOR — ПОМОЩЬ (F1 — закрыть)

КАМЕРА:   ПКМ-драг — вращение | WASD — панорама | колесо — зум | Shift — быстрее
ИНСТРУМЕНТЫ (ЛКМ ставит объект, Esc — режим выбора):
  1 стена   2 платформа   3 ковёр (зона пола)   4 джамп-пад
  5 пьедестал стакана   6 витрина SWAGA   7 спавн игроков   8 спавн босса
ВЫБОР:    ЛКМ по объекту | F — «пол» (текстура всей карты) | Esc — снять
ПРАВКА ВЫБРАННОГО:
  G — перенос за курсором (ЛКМ/G — подтвердить, Esc — отмена)
  стрелки — сдвиг на шаг | Shift+стрелки — ширина/глубина
  Q / E — высота платформы вниз/вверх
  T / Shift+T — текстура | Y — цвет | U / I — масштаб UV меньше/больше
  K — флаг ЩЕЛИ на стене (события залива майонезом)
  Del — удалить | Ctrl+D — дубликат
КАРТА:    B — периметр | L — потолочные лампы | N / M — высота стен -/+
          , / . — размер мира -/+ | 9 — шаг привязки (0.5 / 1 / 2)
ФАЙЛ:     Ctrl+S — сохранить | Ctrl+Z — отменить (undo)

Игра с картой:  python -m server.server --map ФАЙЛ
                python -m client.main --name Имя --map ФАЙЛ"""


class MapEditor(ShowBase):
    def __init__(self, path, empty=False):
        ShowBase.__init__(self)
        self.path = path
        self.setBackgroundColor(*SKY[:3])
        self.disableMouse()

        if os.path.exists(path):
            self.map = mapformat.load_map(path)
        else:
            self.map = (mapformat.empty_map_dict() if empty
                        else mapformat.default_map_dict())
            self.map["name"] = os.path.splitext(os.path.basename(path))[0]

        # список текстур: None + файлы assets/textures
        tex_dir = os.path.join("assets", "textures")
        self.texture_names = [None]
        if os.path.isdir(tex_dir):
            self.texture_names += sorted(
                f for f in os.listdir(tex_dir)
                if f.lower().endswith((".png", ".jpg", ".jpeg")))
        self._tex_cache = {}

        self.font = None
        try:
            if os.path.exists(ARIAL):
                from panda3d.core import Filename
                self.font = self.loader.loadFont(str(Filename.fromOsSpecific(ARIAL)))
        except Exception:
            pass

        # состояние редактора
        self.tool = "select"
        self.selected = None          # (kind, index) | ("floor", 0) | None
        self.grabbing = False
        self._grab_backup = None
        self.snap = 1.0
        self.dirty = False
        self.undo_stack = []
        self._status_text = ""
        self._status_until = 0.0
        self.help_visible = False

        # камера-орбита
        self.pivot = self.render.attachNewNode("cam_pivot")
        self.camera.reparentTo(self.pivot)
        self.cam_h, self.cam_p, self.cam_dist = 25.0, -42.0, 130.0
        self._rmb_down = False
        self._last_mouse = None
        self.keys = {}

        self._setup_lights()
        self._setup_hud()
        self._bind_keys()

        self.scene_root = None
        self.ghost = None
        self._nodes = []              # (kind, index, NodePath, aabb)
        self._rebuild()
        self.taskMgr.add(self._update, "editor_update")

    # ---------- ввод ----------
    def _bind_keys(self):
        for k in ("w", "a", "s", "d", "shift"):
            self.accept(k, self.keys.__setitem__, [k, True])
            self.accept(f"{k}-up", self.keys.__setitem__, [k, False])
        self.accept("mouse3", self._set_rmb, [True])
        self.accept("mouse3-up", self._set_rmb, [False])
        self.accept("wheel_up", self._zoom, [0.88])
        self.accept("wheel_down", self._zoom, [1.14])
        self.accept("mouse1", self._on_click)
        for key, tool in TOOL_KEYS.items():
            self.accept(key, self._set_tool, [tool])
        self.accept("escape", self._on_escape)
        self.accept("g", self._toggle_grab)
        self.accept("f", self._select_floor)
        self.accept("f1", self._toggle_help)
        self.accept("9", self._cycle_snap)
        self.accept("t", self._cycle_texture, [1])
        self.accept("shift-t", self._cycle_texture, [-1])
        self.accept("y", self._cycle_color)
        self.accept("u", self._adjust_uv, [1 / 1.3])
        self.accept("i", self._adjust_uv, [1.3])
        self.accept("k", self._toggle_slit)
        self.accept("delete", self._delete_selected)
        self.accept("x", self._delete_selected)
        self.accept("control-d", self._duplicate)
        self.accept("control-s", self._save)
        self.accept("control-z", self._undo)
        self.accept("b", self._toggle_flag, ["perimeter"])
        self.accept("l", self._toggle_flag, ["ceiling_lights"])
        self.accept("n", self._adjust_map, ["wall_height", -1.0])
        self.accept("m", self._adjust_map, ["wall_height", 1.0])
        self.accept(",", self._adjust_map, ["size", -4.0])
        self.accept(".", self._adjust_map, ["size", 4.0])
        for key, dx, dy in (("arrow_left", -1, 0), ("arrow_right", 1, 0),
                            ("arrow_up", 0, 1), ("arrow_down", 0, -1)):
            self.accept(key, self._nudge, [dx, dy, False])
            self.accept(f"shift-{key}", self._nudge, [dx, dy, True])
        self.accept("q", self._adjust_platform_z, [-1.0])
        self.accept("e", self._adjust_platform_z, [1.0])

    def _set_rmb(self, down):
        self._rmb_down = down
        self._last_mouse = None

    def _zoom(self, factor):
        self.cam_dist = max(10.0, min(500.0, self.cam_dist * factor))

    # ---------- статус/HUD ----------
    def _setup_hud(self):
        def make_text(z, scale=0.045, fg=(1, 1, 0.8, 1)):
            tn = TextNode("hud")
            if self.font:
                tn.setFont(self.font)
            tn.setTextColor(*fg)
            tn.setShadow(0.05, 0.05)
            tn.setShadowColor(0, 0, 0, 1)
            np = self.aspect2d.attachNewNode(tn)
            np.setScale(scale)
            np.setPos(-1.72, 0, z)
            return tn
        self.hud_top = make_text(0.92)
        self.hud_sel = make_text(0.80, fg=(0.75, 0.95, 1.0, 1))
        self.hud_status = make_text(-0.88, fg=(1.0, 0.75, 0.4, 1))
        self.hud_hint = make_text(-0.96, scale=0.04, fg=(0.8, 0.8, 0.7, 1))
        self.hud_hint.setText(
            "F1 — помощь | ЛКМ выбрать/поставить | Esc — режим выбора | Ctrl+S — сохранить")
        help_tn = TextNode("help")
        if self.font:
            help_tn.setFont(self.font)
        help_tn.setTextColor(1, 1, 0.85, 1)
        help_tn.setCardColor(0, 0, 0, 0.82)
        help_tn.setCardAsMargin(0.6, 0.6, 0.4, 0.4)
        help_tn.setText(HELP_TEXT)
        self.help_np = self.aspect2d.attachNewNode(help_tn)
        self.help_np.setScale(0.05)
        self.help_np.setPos(-1.35, 0, 0.75)
        self.help_np.hide()

    def _status(self, text, secs=3.0):
        import time
        self._status_text = text
        self._status_until = time.time() + secs

    def _toggle_help(self):
        self.help_visible = not self.help_visible
        if self.help_visible:
            self.help_np.show()
        else:
            self.help_np.hide()

    def _refresh_hud(self):
        m = self.map
        star = " *" if self.dirty else ""
        self.hud_top.setText(
            f"{os.path.basename(self.path)}{star}  «{m['name']}»  "
            f"мир ±{m['size']:g}  стены h={m['wall_height']:g}  снап {self.snap:g}\n"
            f"инструмент: {TOOL_TITLES[self.tool]}  |  "
            f"стен {len(m['walls'])}  платформ {len(m['platforms'])}  "
            f"ковров {len(m['carpets'])}  падов {len(m['jump_pads'])}  "
            f"пьедесталов {len(m['cup_spots'])}  "
            f"периметр {'да' if m['perimeter'] else 'нет'}  "
            f"лампы {'да' if m['ceiling_lights'] else 'нет'}")
        sel = self.selected
        if sel is None:
            self.hud_sel.setText("")
        elif sel[0] == "floor":
            f = m["floor"]
            self.hud_sel.setText(
                f"ВЫБРАН: ПОЛ  текстура={f['texture'] or '—'}  "
                f"цвет={'свой' if f['color'] else 'дефолт'}  uv={f['uv']:g}")
        else:
            kind, i = sel
            e = self._entry(kind, i)
            extra = ""
            if kind == "wall":
                extra = (f"  текстура={e.get('texture') or 'дефолт'}"
                         f"  uv={e.get('uv', 0.4):g}"
                         f"  ЩЕЛЬ={'ДА' if e.get('slit') else 'нет'}")
            elif kind == "carpet":
                extra = f"  текстура={e.get('texture') or '—'}  uv={e.get('uv', 0.32):g}"
            elif kind == "platform":
                extra = f"  z={e['z']:g}"
            grab = "  [ПЕРЕНОС — ЛКМ подтвердить]" if self.grabbing else ""
            if isinstance(e, dict) and "w" in e:
                dims = f"  {e['w']:g}×{e['d']:g}"
            else:
                dims = ""
            pos = self._obj_pos(kind, i)
            self.hud_sel.setText(
                f"ВЫБРАН: {TOOL_TITLES.get(kind, kind)} #{i}  "
                f"({pos[0]:g}, {pos[1]:g}){dims}{extra}{grab}")

    # ---------- доступ к данным карты ----------
    def _list_for(self, kind):
        return {"wall": self.map["walls"], "platform": self.map["platforms"],
                "carpet": self.map["carpets"], "jump_pad": self.map["jump_pads"],
                "cup_spot": self.map["cup_spots"],
                "structure": self.map["structures"]}[kind]

    def _entry(self, kind, i):
        if kind == "spawn":
            return self.map["spawn"]
        if kind == "boss_spawn":
            return self.map["boss_spawn"]
        return self._list_for(kind)[i]

    def _obj_pos(self, kind, i):
        e = self._entry(kind, i)
        if kind in ("jump_pad", "cup_spot", "spawn", "boss_spawn"):
            return e[0], e[1]
        return e["x"], e["y"]

    def _set_obj_pos(self, kind, i, x, y):
        e = self._entry(kind, i)
        if kind in ("jump_pad", "cup_spot", "spawn", "boss_spawn"):
            e[0], e[1] = x, y
        else:
            e["x"], e["y"] = x, y

    def _push_undo(self):
        self.undo_stack.append(json.dumps(self.map))
        if len(self.undo_stack) > 100:
            self.undo_stack.pop(0)
        self.dirty = True

    def _undo(self):
        if self.grabbing:
            return
        if not self.undo_stack:
            self._status("нечего отменять")
            return
        self.map = json.loads(self.undo_stack.pop())
        self.selected = None
        self.dirty = True
        self._rebuild()
        self._status("отменено")

    def _save(self):
        try:
            self.map = mapformat.save_map(self.path, self.map)
        except mapformat.MapError as e:
            self._status(f"ОШИБКА КАРТЫ: {e}", 6.0)
            return
        self.dirty = False
        self._status(f"сохранено: {self.path}")

    # ---------- инструменты/выбор ----------
    def _set_tool(self, tool):
        if self.grabbing:
            return
        self.tool = tool
        self.selected = None
        self._make_ghost()

    def _on_escape(self):
        if self.grabbing:
            self._cancel_grab()
        elif self.tool != "select":
            self.tool = "select"
            self._make_ghost()
        else:
            self.selected = None

    def _select_floor(self):
        if not self.grabbing:
            self.tool = "select"
            self._make_ghost()
            self.selected = ("floor", 0)

    def _cycle_snap(self):
        self.snap = {0.5: 1.0, 1.0: 2.0, 2.0: 0.5}[self.snap]

    def _snap_pt(self, x, y):
        s = self.snap
        return round(round(x / s) * s, 3), round(round(y / s) * s, 3)

    # ---------- мышь: луч и пик ----------
    def _mouse_ray(self):
        if not self.mouseWatcherNode.hasMouse():
            return None
        mpos = self.mouseWatcherNode.getMouse()
        near, far = Point3(), Point3()
        self.camLens.extrude(mpos, near, far)
        near = self.render.getRelativePoint(self.cam, near)
        far = self.render.getRelativePoint(self.cam, far)
        d = Vec3(far - near)
        if d.length() < 1e-9:
            return None
        d.normalize()
        return Point3(near), d

    def _ground_point(self, z=0.0):
        ray = self._mouse_ray()
        if not ray:
            return None
        o, d = ray
        if abs(d.z) < 1e-6:
            return None
        t = (z - o.z) / d.z
        if t <= 0:
            return None
        p = o + d * t
        return p.x, p.y

    @staticmethod
    def _ray_aabb(o, d, box):
        (x0, y0, z0, x1, y1, z1) = box
        tmin, tmax = 0.0, 1e9
        for oc, dc, lo, hi in ((o.x, d.x, x0, x1), (o.y, d.y, y0, y1),
                               (o.z, d.z, z0, z1)):
            if abs(dc) < 1e-9:
                if oc < lo or oc > hi:
                    return None
                continue
            t1, t2 = (lo - oc) / dc, (hi - oc) / dc
            if t1 > t2:
                t1, t2 = t2, t1
            tmin, tmax = max(tmin, t1), min(tmax, t2)
            if tmin > tmax:
                return None
        return tmin

    def _pick(self):
        ray = self._mouse_ray()
        if not ray:
            return None
        o, d = ray
        best, best_t = None, 1e9
        for kind, i, _np, box in self._nodes:
            t = self._ray_aabb(o, d, box)
            if t is not None and t < best_t:
                best, best_t = (kind, i), t
        return best

    def _on_click(self):
        if self.help_visible:
            return
        if self.grabbing:
            self._confirm_grab()
            return
        if self.tool == "select":
            self.selected = self._pick()
            return
        pt = self._ground_point()
        if not pt:
            return
        x, y = self._snap_pt(*pt)
        self._place(self.tool, x, y)

    # ---------- добавление объектов ----------
    def _place(self, tool, x, y):
        self._push_undo()
        m = self.map
        if tool == "wall":
            m["walls"].append({"x": x, "y": y, "w": 8.0, "d": 2.0})
            self.selected = ("wall", len(m["walls"]) - 1)
        elif tool == "platform":
            m["platforms"].append({"x": x, "y": y, "w": 12.0, "d": 12.0,
                                   "z": m["level2_z"]})
            self.selected = ("platform", len(m["platforms"]) - 1)
        elif tool == "carpet":
            m["carpets"].append({"x": x, "y": y, "w": 10.0, "d": 10.0,
                                 "color": [0.55, 0.12, 0.12, 1.0]})
            self.selected = ("carpet", len(m["carpets"]) - 1)
        elif tool == "jump_pad":
            m["jump_pads"].append([x, y])
            self.selected = ("jump_pad", len(m["jump_pads"]) - 1)
        elif tool == "cup_spot":
            m["cup_spots"].append([x, y])
            self.selected = ("cup_spot", len(m["cup_spots"]) - 1)
        elif tool == "structure":
            m["structures"].append({"kind": "showcase", "x": x, "y": y})
            self.selected = ("structure", len(m["structures"]) - 1)
        elif tool == "spawn":
            m["spawn"] = [x, y]
            self.selected = ("spawn", 0)
        elif tool == "boss_spawn":
            m["boss_spawn"] = [x, y]
            self.selected = ("boss_spawn", 0)
        self._rebuild()

    # ---------- правка выбранного ----------
    def _sel_rect(self):
        """Выбранный прямоугольный объект (dict с x,y,w,d) или None."""
        if not self.selected or self.selected[0] not in ("wall", "platform", "carpet"):
            return None
        return self._entry(*self.selected)

    def _nudge(self, dx, dy, resize):
        if not self.selected or self.selected[0] == "floor":
            return
        kind, i = self.selected
        step = self.snap
        if resize:
            e = self._sel_rect()
            if e is None:
                return
            self._push_undo()
            e = self._sel_rect()
            if dx:
                e["w"] = max(0.5, round(e["w"] + dx * step, 3))
            if dy:
                e["d"] = max(0.5, round(e["d"] + dy * step, 3))
        else:
            self._push_undo()
            x, y = self._obj_pos(kind, i)
            self._set_obj_pos(kind, i, round(x + dx * step, 3),
                              round(y + dy * step, 3))
        self._rebuild()

    def _adjust_platform_z(self, dz):
        if not self.selected or self.selected[0] != "platform":
            return
        self._push_undo()
        e = self._entry(*self.selected)
        e["z"] = max(1.0, min(80.0, round(e["z"] + dz, 3)))
        self._rebuild()

    def _cycle_texture(self, step):
        if not self.selected:
            return
        kind = self.selected[0]
        if kind == "floor":
            target = self.map["floor"]
        elif kind in ("wall", "carpet"):
            target = self._entry(*self.selected)
        else:
            return
        self._push_undo()
        cur = target.get("texture")
        idx = self.texture_names.index(cur) if cur in self.texture_names else 0
        new = self.texture_names[(idx + step) % len(self.texture_names)]
        if new is None:
            target.pop("texture", None)
            if kind == "floor":
                target["texture"] = None
        else:
            target["texture"] = new
        self._rebuild()
        self._status(f"текстура: {new or 'нет'}")

    def _cycle_color(self):
        if not self.selected:
            return
        kind = self.selected[0]
        if kind == "floor":
            target = self.map["floor"]
        elif kind in ("wall", "carpet", "platform"):
            target = self._entry(*self.selected)
        else:
            return
        self._push_undo()
        cur = target.get("color")
        idx = 0
        if cur:
            for j, c in enumerate(COLOR_PRESETS):
                if c and all(abs(a - b) < 0.01 for a, b in zip(c, cur)):
                    idx = j
                    break
        new = COLOR_PRESETS[(idx + 1) % len(COLOR_PRESETS)]
        if new is None:
            target.pop("color", None)
            if kind == "floor":
                target["color"] = None
        else:
            target["color"] = list(new)
        self._rebuild()

    def _adjust_uv(self, factor):
        if not self.selected:
            return
        kind = self.selected[0]
        if kind == "floor":
            target, default = self.map["floor"], 0.32
        elif kind in ("wall", "carpet"):
            target, default = self._entry(*self.selected), 0.4
        else:
            return
        self._push_undo()
        target["uv"] = round(max(0.01, min(8.0, target.get("uv", default) * factor)), 3)
        self._rebuild()
        self._status(f"uv: {target['uv']:g}")

    def _toggle_slit(self):
        if not self.selected or self.selected[0] != "wall":
            self._status("флаг ЩЕЛИ — только для стен")
            return
        self._push_undo()
        e = self._entry(*self.selected)
        if e.get("slit"):
            e.pop("slit", None)
        else:
            e["slit"] = True
        self._rebuild()

    def _delete_selected(self):
        if not self.selected or self.selected[0] in ("floor", "spawn", "boss_spawn"):
            return
        kind, i = self.selected
        self._push_undo()
        del self._list_for(kind)[i]
        self.selected = None
        self._rebuild()

    def _duplicate(self):
        if not self.selected:
            return
        kind, i = self.selected
        if kind in ("floor", "spawn", "boss_spawn"):
            return
        self._push_undo()
        lst = self._list_for(kind)
        e = json.loads(json.dumps(lst[i]))
        if isinstance(e, dict):
            e["x"] += 2 * self.snap
            e["y"] += 2 * self.snap
        else:
            e[0] += 2 * self.snap
            e[1] += 2 * self.snap
        lst.append(e)
        self.selected = (kind, len(lst) - 1)
        self._rebuild()

    def _toggle_grab(self):
        if not self.selected or self.selected[0] == "floor":
            return
        if self.grabbing:
            self._confirm_grab()
        else:
            self.grabbing = True
            self._grab_backup = json.dumps(self.map)

    def _confirm_grab(self):
        if self.grabbing:
            self.undo_stack.append(self._grab_backup)
            if len(self.undo_stack) > 100:
                self.undo_stack.pop(0)
            self.dirty = True
            self.grabbing = False
            self._grab_backup = None

    def _cancel_grab(self):
        if self.grabbing:
            self.map = json.loads(self._grab_backup)
            self.grabbing = False
            self._grab_backup = None
            self._rebuild()

    def _toggle_flag(self, key):
        self._push_undo()
        self.map[key] = not self.map[key]
        self._rebuild()

    def _adjust_map(self, key, delta):
        lo, hi = (3, 40) if key == "wall_height" else (20, 240)
        self._push_undo()
        self.map[key] = max(lo, min(hi, self.map[key] + delta))
        self._rebuild()

    # ---------- сцена ----------
    def _setup_lights(self):
        amb = AmbientLight("amb")
        amb.setColor((0.62, 0.58, 0.45, 1))
        self.render.setLight(self.render.attachNewNode(amb))
        dl = DirectionalLight("sun")
        dl.setColor((0.55, 0.52, 0.42, 1))
        dn = self.render.attachNewNode(dl)
        dn.setHpr(-30, -65, 0)
        self.render.setLight(dn)

    def _get_tex(self, name):
        if not name:
            return None
        if name not in self._tex_cache:
            path = os.path.join("assets", "textures", name)
            tex = None
            if texture_exists(path):
                from panda3d.core import Texture as _T
                tex = load_texture(self.loader, path)
                tex.setWrapU(_T.WM_repeat)
                tex.setWrapV(_T.WM_repeat)
            self._tex_cache[name] = tex
        return self._tex_cache[name]

    def _rebuild(self):
        """Полная пересборка 3D-сцены из self.map (редактору хватает)."""
        if self.scene_root:
            self.scene_root.removeNode()
        self.scene_root = self.render.attachNewNode("map_scene")
        self._nodes = []
        m = self.map
        size = m["size"]
        wh = m["wall_height"]

        # пол
        f = m["floor"]
        tex = self._get_tex(f["texture"])
        col = tuple(f["color"]) if f["color"] else ((1, 1, 1, 1) if tex else CARPET)
        ground = make_box(2 * size, 2 * size, 0.4, col, uv_scale=f["uv"])
        ground.setZ(-0.2)
        if tex:
            ground.setTexture(tex)
        ground.reparentTo(self.scene_root)

        # сетка привязки + граница мира
        self._build_grid(size)

        # периметр (полупрозрачный, чтобы не мешал обзору)
        if m["perimeter"]:
            for sx, sy, w, d in ((0, size, 2 * size, 1.5), (0, -size, 2 * size, 1.5),
                                 (size, 0, 1.5, 2 * size), (-size, 0, 1.5, 2 * size)):
                wall = make_box(w, d, wh + 8, (0.74, 0.63, 0.27, 0.35))
                wall.setPos(sx, sy, (wh + 8) / 2)
                wall.setTransparency(TransparencyAttrib.MAlpha)
                wall.reparentTo(self.scene_root)

        # ковры
        for i, cz in enumerate(m["carpets"]):
            tex = self._get_tex(cz.get("texture"))
            col = tuple(cz["color"]) if cz.get("color") else (
                (1, 1, 1, 1) if tex else (0.5, 0.3, 0.2, 1))
            node = make_box(cz["w"], cz["d"], 0.1, col, uv_scale=cz.get("uv", 0.32))
            node.setPos(cz["x"], cz["y"], 0.06 + (i % 3) * 0.012)
            if tex:
                node.setTexture(tex)
            node.reparentTo(self.scene_root)
            self._register("carpet", i, node,
                           (cz["x"] - cz["w"] / 2, cz["y"] - cz["d"] / 2, 0,
                            cz["x"] + cz["w"] / 2, cz["y"] + cz["d"] / 2, 0.4))

        # стены
        for i, wd in enumerate(m["walls"]):
            tex = self._get_tex(wd.get("texture"))
            col = tuple(wd["color"]) if wd.get("color") else (
                (1, 1, 1, 1) if tex else (WALLPAPER if i % 2 == 0 else WALLPAPER_DARK))
            node = make_box(wd["w"], wd["d"], wh, col, uv_scale=wd.get("uv", 0.4))
            node.setPos(wd["x"], wd["y"], wh / 2)
            if tex:
                node.setTexture(tex)
            node.reparentTo(self.scene_root)
            if wd.get("slit"):
                marker = make_box(min(wd["w"], 2.0), min(wd["d"], 2.0), 0.5,
                                  (0.9, 0.1, 0.1, 1))
                marker.setPos(wd["x"], wd["y"], wh + 0.3)
                marker.setLightOff(1)
                marker.reparentTo(self.scene_root)
            self._register("wall", i, node,
                           (wd["x"] - wd["w"] / 2, wd["y"] - wd["d"] / 2, 0,
                            wd["x"] + wd["w"] / 2, wd["y"] + wd["d"] / 2, wh))

        # платформы
        for i, p in enumerate(m["platforms"]):
            col = tuple(p["color"]) if p.get("color") else PLATFORM_TOP
            node = make_box(p["w"], p["d"], 0.6, col)
            node.setPos(p["x"], p["y"], p["z"] - 0.3)
            node.reparentTo(self.scene_root)
            edge = make_box(p["w"], p["d"], 0.1, PLATFORM_EDGE)
            edge.setPos(p["x"], p["y"], p["z"] + 0.05)
            edge.setLightOff(1)
            edge.reparentTo(self.scene_root)
            self._register("platform", i, node,
                           (p["x"] - p["w"] / 2, p["y"] - p["d"] / 2, p["z"] - 0.6,
                            p["x"] + p["w"] / 2, p["y"] + p["d"] / 2, p["z"] + 0.15))

        # джамп-пады
        for i, (px, py) in enumerate(m["jump_pads"]):
            node = make_cylinder(2.0, 0.3, 20, JUMP_PAD)
            node.setPos(px, py, 0.15)
            node.setLightOff(1)
            node.reparentTo(self.scene_root)
            self._register("jump_pad", i, node, (px - 2, py - 2, 0, px + 2, py + 2, 1.2))

        # пьедесталы стаканов
        for i, (px, py) in enumerate(m["cup_spots"]):
            node = make_box(2.2, 2.2, 0.9, (0.10, 0.09, 0.07, 1))
            node.setPos(px, py, 0.45)
            node.reparentTo(self.scene_root)
            ring = make_cylinder(1.1, 0.12, 18, (0.85, 0.3, 0.95, 1))
            ring.setPos(px, py, 0.95)
            ring.setLightOff(1)
            ring.reparentTo(self.scene_root)
            self._register("cup_spot", i, node,
                           (px - 1.4, py - 1.4, 0, px + 1.4, py + 1.4, 1.4))

        # витрины
        for i, s in enumerate(m["structures"]):
            node = make_box(3.6, 3.6, 5.0, (0.12, 0.11, 0.08, 1))
            node.setPos(s["x"], s["y"], 2.5)
            node.reparentTo(self.scene_root)
            trim = make_box(4.0, 4.0, 0.15, JUMP_PAD)
            trim.setPos(s["x"], s["y"], 5.15)
            trim.setLightOff(1)
            trim.reparentTo(self.scene_root)
            self._label(s["x"], s["y"], 6.2, "SWAGA", (1.0, 0.93, 0.55, 1))
            self._register("structure", i, node,
                           (s["x"] - 2, s["y"] - 2, 0, s["x"] + 2, s["y"] + 2, 5.3))

        # маркеры спавнов
        sx, sy = m["spawn"]
        node = make_cylinder(1.6, 0.25, 20, (0.2, 0.95, 0.35, 1))
        node.setPos(sx, sy, 0.13)
        node.setLightOff(1)
        node.reparentTo(self.scene_root)
        self._label(sx, sy, 2.6, "СПАВН", (0.4, 1.0, 0.5, 1))
        self._register("spawn", 0, node, (sx - 1.6, sy - 1.6, 0, sx + 1.6, sy + 1.6, 2.0))

        bx, by = m["boss_spawn"]
        node = make_cylinder(2.2, 0.25, 20, (1.0, 0.55, 0.1, 1))
        node.setPos(bx, by, 0.13)
        node.setLightOff(1)
        node.reparentTo(self.scene_root)
        self._label(bx, by, 2.6, "БОСС", (1.0, 0.7, 0.3, 1))
        self._register("boss_spawn", 0, node,
                       (bx - 2.2, by - 2.2, 0, bx + 2.2, by + 2.2, 2.0))

        # лампы (упрощённо — не мешают редактированию, только образ)
        if m["ceiling_lights"]:
            step = 12.0
            n = int(size / step)
            for gx in range(-n, n + 1):
                for gy in range(-n, n + 1):
                    lp = make_box(3.5, 3.5, 0.15, LIGHT_PANEL)
                    lp.setPos(gx * step, gy * step, wh - 0.05)
                    lp.setLightOff(1)
                    lp.reparentTo(self.scene_root)

        self._apply_selection_highlight()
        self._refresh_hud()

    def _register(self, kind, i, node, aabb):
        self._nodes.append((kind, i, node, aabb))

    def _label(self, x, y, z, text, color):
        tn = TextNode("label")
        if self.font:
            tn.setFont(self.font)
        tn.setText(text)
        tn.setAlign(TextNode.ACenter)
        tn.setTextColor(*color)
        np = self.scene_root.attachNewNode(tn)
        np.setScale(1.6)
        np.setPos(x, y, z)
        np.setBillboardPointEye()
        np.setLightOff(1)

    def _build_grid(self, size):
        segs = LineSegs()
        segs.setThickness(1.0)
        segs.setColor(0.35, 0.33, 0.22, 1)
        step = 4.0
        n = int(size / step)
        for k in range(-n, n + 1):
            v = k * step
            segs.moveTo(v, -size, 0.02)
            segs.drawTo(v, size, 0.02)
            segs.moveTo(-size, v, 0.02)
            segs.drawTo(size, v, 0.02)
        segs.setThickness(3.0)
        segs.setColor(0.9, 0.4, 0.2, 1)
        for x0, y0, x1, y1 in ((-size, -size, size, -size), (size, -size, size, size),
                               (size, size, -size, size), (-size, size, -size, -size)):
            segs.moveTo(x0, y0, 0.05)
            segs.drawTo(x1, y1, 0.05)
        # оси
        segs.setThickness(2.0)
        segs.setColor(0.7, 0.2, 0.2, 1)
        segs.moveTo(0, 0, 0.06)
        segs.drawTo(6, 0, 0.06)
        segs.setColor(0.2, 0.7, 0.2, 1)
        segs.moveTo(0, 0, 0.06)
        segs.drawTo(0, 6, 0.06)
        self.scene_root.attachNewNode(segs.create())

    def _apply_selection_highlight(self):
        for kind, i, node, _box in self._nodes:
            if self.selected == (kind, i):
                node.setColorScale(1.6, 1.6, 0.75, 1)
            else:
                node.clearColorScale()

    def _make_ghost(self):
        if self.ghost:
            self.ghost.removeNode()
            self.ghost = None
        dims = {"wall": (8, 2, self.map["wall_height"]),
                "platform": (12, 12, 0.6), "carpet": (10, 10, 0.15),
                "jump_pad": (4, 4, 0.4), "cup_spot": (2.2, 2.2, 1.0),
                "structure": (3.6, 3.6, 5.0), "spawn": (3, 3, 0.3),
                "boss_spawn": (4.4, 4.4, 0.3)}.get(self.tool)
        if not dims:
            return
        g = make_box(dims[0], dims[1], dims[2], (0.3, 0.9, 1.0, 0.4))
        g.setTransparency(TransparencyAttrib.MAlpha)
        g.setLightOff(1)
        g.reparentTo(self.render)
        self.ghost = g

    # ---------- главный цикл ----------
    def _update(self, task):
        import time
        dt = globalClock.getDt()
        # камера: вращение ПКМ
        if self._rmb_down and self.mouseWatcherNode.hasMouse():
            mp = self.mouseWatcherNode.getMouse()
            cur = (mp.getX(), mp.getY())
            if self._last_mouse is not None:
                dx = cur[0] - self._last_mouse[0]
                dy = cur[1] - self._last_mouse[1]
                self.cam_h -= dx * 120.0
                self.cam_p = max(-89.0, min(-5.0, self.cam_p + dy * 90.0))
            self._last_mouse = cur
        # панорама WASD
        speed = self.map["size"] * (3.2 if self.keys.get("shift") else 1.1) * dt
        rad = math.radians(self.cam_h)
        fwd = Vec3(-math.sin(rad), math.cos(rad), 0)
        right = Vec3(math.cos(rad), math.sin(rad), 0)
        move = Vec3(0)
        if self.keys.get("w"):
            move += fwd
        if self.keys.get("s"):
            move -= fwd
        if self.keys.get("d"):
            move += right
        if self.keys.get("a"):
            move -= right
        if move.lengthSquared() > 0:
            move.normalize()
            self.pivot.setPos(self.pivot.getPos() + move * speed)
        self.pivot.setHpr(self.cam_h, self.cam_p, 0)
        self.camera.setPos(0, -self.cam_dist, 0)
        self.camera.lookAt(self.pivot)

        # призрак инструмента / перенос выбранного
        if self.ghost:
            pt = self._ground_point()
            if pt:
                x, y = self._snap_pt(*pt)
                z = {"platform": self.map["level2_z"] - 0.3}.get(self.tool, 0.0)
                if self.tool == "wall":
                    z = self.map["wall_height"] / 2
                elif self.tool == "structure":
                    z = 2.5
                self.ghost.show()
                self.ghost.setPos(x, y, z)
            else:
                self.ghost.hide()
        if self.grabbing and self.selected:
            pt = self._ground_point()
            if pt:
                x, y = self._snap_pt(*pt)
                kind, i = self.selected
                ox, oy = self._obj_pos(kind, i)
                if (ox, oy) != (x, y):
                    self._set_obj_pos(kind, i, x, y)
                    self._rebuild()

        # статус-строка
        if time.time() > self._status_until:
            self._status_text = ""
        self.hud_status.setText(self._status_text)
        self._refresh_hud()
        return task.cont


def main():
    parser = argparse.ArgumentParser(description="Редактор карт SWAGA")
    parser.add_argument("file", help="файл карты (maps/имя.json); нет — будет создан")
    parser.add_argument("--empty", action="store_true",
                        help="новая карта пустой (по умолчанию — копия арены)")
    args = parser.parse_args()
    app = MapEditor(args.file, empty=args.empty)
    app.run()


if __name__ == "__main__":
    main()
