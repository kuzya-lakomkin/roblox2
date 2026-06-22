"""Экраны интерфейса (DirectGui): главное меню-хаб, настройки, пауза, заглушки фаз.

Кнопки скруглённые (процедурная текстура), с тенью и плавными анимациями hover/press.
"""

from direct.gui import DirectGuiGlobals as DGG
from direct.gui.DirectGui import (DirectButton, DirectCheckButton, DirectEntry,
                                  DirectFrame, DirectLabel, DirectOptionMenu,
                                  DirectSlider)
from direct.interval.LerpInterval import (LerpColorScaleInterval,
                                          LerpScaleInterval)
from direct.interval.MetaInterval import Parallel
from panda3d.core import PNMImage, Texture

# доступные разрешения окна
RESOLUTIONS = ["1280x720", "1366x768", "1600x900", "1920x1080"]

# палитра UI в тон backrooms: жёлто-янтарный (флуоресцентный) + холодный голубой,
# панели полупрозрачные — чтобы сквозь меню просвечивала размытая карта
BG = (0.02, 0.02, 0.01, 0.10)       # еле заметное затемнение всего экрана
PANEL = (0.12, 0.10, 0.05, 0.16)    # СИЛЬНО прозрачная «карточка» — карта хорошо видна
ACCENT = (1.0, 0.88, 0.45, 1)       # янтарный (свет ламп backrooms)
ACCENT2 = (0.55, 0.85, 1.0, 1)      # холодный голубой (контраст ламп/падов)
BTN = (0.26, 0.21, 0.10, 0.78)      # база кнопки (полупрозрачная, градиент задаёт текстура)
BTN_HI = (0.58, 0.48, 0.22, 0.90)   # подсветка при наведении
TEXT = (0.97, 0.94, 0.84, 1)
SHADOW = (0, 0, 0, 0.5)

_ROUND_TEX = None      # кэш полностью скруглённой текстуры (панель)
_BTN_TEX = {}          # кэш текстур кнопок по набору скруглённых углов


def _kw(font):
    return {"text_font": font} if font else {}


def _rounded_texture(size=256, radius=56):
    """Бело-прозрачная скруглённая «плитка» (RGBA) — основа панелей."""
    global _ROUND_TEX
    if _ROUND_TEX is not None:
        return _ROUND_TEX
    img = PNMImage(size, size)
    img.addAlpha()
    img.fill(1, 1, 1)
    img.alphaFill(1.0)
    r = radius
    hi = size - 1 - r
    for x in range(size):
        for y in range(size):
            if x < r and y < r:
                cx, cy = r, r
            elif x > hi and y < r:
                cx, cy = hi, r
            elif x < r and y > hi:
                cx, cy = r, hi
            elif x > hi and y > hi:
                cx, cy = hi, hi
            else:
                continue
            d = ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5
            img.setAlpha(x, y, max(0.0, min(1.0, r - d + 0.5)))
    tex = Texture("rounded")
    tex.load(img)
    tex.setMinfilter(Texture.FTLinear)
    tex.setMagfilter(Texture.FTLinear)
    _ROUND_TEX = tex
    return tex


def _button_texture(corners="all", size=128, radius=30):
    """Текстура кнопки с вертикальным градиентом и скруглением нужных углов."""
    if corners in _BTN_TEX:
        return _BTN_TEX[corners]
    do = set()
    if corners in ("all", "top"):
        do |= {"tl", "tr"}
    if corners in ("all", "bottom"):
        do |= {"bl", "br"}
    img = PNMImage(size, size)
    img.addAlpha()
    for y in range(size):
        v = y / (size - 1)
        b = max(0.0, min(1.0, 1.16 - 0.62 * v))
        for x in range(size):
            img.setXel(x, y, b, b, b)
            img.setAlpha(x, y, 1.0)
    r, hi = radius, size - 1 - radius
    for x in range(size):
        for y in range(size):
            if x < r and y < r:
                corner, cx, cy = "tl", r, r
            elif x > hi and y < r:
                corner, cx, cy = "tr", hi, r
            elif x < r and y > hi:
                corner, cx, cy = "bl", r, hi
            elif x > hi and y > hi:
                corner, cx, cy = "br", hi, hi
            else:
                continue
            if corner in do:
                d = ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5
                img.setAlpha(x, y, max(0.0, min(1.0, r - d + 0.5)))
    tex = Texture("btn_" + corners)
    tex.load(img)
    tex.setMinfilter(Texture.FTLinear)
    tex.setMagfilter(Texture.FTLinear)
    _BTN_TEX[corners] = tex
    return tex


class Screen:
    """Базовый полноэкранный экран с центральной скруглённой панелью."""

    def __init__(self, app, panel=(-0.46, 0.46, -0.62, 0.74)):
        self.app = app
        self.font_ui = app.fonts.get("ui")
        self.font_title = app.fonts.get("title")
        self._round = _rounded_texture()
        self.root = DirectFrame(frameColor=BG, frameSize=(-2, 2, -1, 1),
                                parent=app.aspect2d)
        self.root.hide()
        self._anim = {}
        if panel:
            l, r, b, t = panel
            self.panel = DirectFrame(
                parent=self.root, relief=None, image=self._round,
                image_scale=((r - l) / 2, 1, (t - b) / 2),
                image_color=PANEL, pos=((l + r) / 2, 0, (b + t) / 2),
            )

    def _button(self, text, y, command, hw=0.34, hh=0.052, corners="all", color=BTN):
        tex = _button_texture(corners)
        btn = DirectButton(
            parent=self.root, text=text, command=command, relief=None,
            pos=(0, 0, y), image=tex, image_scale=(hw, 1, hh),
            image_color=color, text_fg=TEXT, text_scale=0.043,
            text_pos=(0, -0.014), **_kw(self.font_ui),
        )
        btn.bind(DGG.WITHIN, self._on_enter, [btn])
        btn.bind(DGG.WITHOUT, self._on_exit, [btn])
        btn.bind(DGG.B1PRESS, self._on_press, [btn])
        btn.bind(DGG.B1RELEASE, self._on_enter, [btn])
        return btn

    def _button_stack(self, items, top_y, hw=0.34, hh=0.052):
        """Сплошной столбик кнопок с правильным скруглением."""
        n = len(items)
        DirectFrame(parent=self.root, relief=None, image=self._round,
                    image_scale=(hw + 0.022, 1, n * hh + 0.022), image_color=SHADOW,
                    pos=(0.012, 0, top_y - (n - 1) * hh - 0.016))
        btns = []
        for i, (text, cmd) in enumerate(items):
            if n == 1:
                corners = "all"
            elif i == 0:
                corners = "top"
            elif i == n - 1:
                corners = "bottom"
            else:
                corners = "mid"
            btns.append(self._button(text, top_y - i * 2 * hh, cmd, hw, hh, corners))
        return btns

    def _animate(self, btn, scale, bright):
        old = self._anim.get(btn)
        if old:
            old.finish()
        anim = Parallel(
            LerpScaleInterval(btn, 0.12, scale, blendType="easeOut"),
            LerpColorScaleInterval(btn, 0.12, (bright, bright, bright, 1)),
        )
        self._anim[btn] = anim
        anim.start()

    def _on_enter(self, btn, _=None):
        btn["image_color"] = BTN_HI
        self._animate(btn, 1.07, 1.0)

    def _on_exit(self, btn, _=None):
        btn["image_color"] = BTN
        self._animate(btn, 1.0, 1.0)

    def _on_press(self, btn, _=None):
        self._animate(btn, 0.95, 0.85)

    def _title(self, text, y=0.7, color=ACCENT, scale=0.16):
        offs = [(0.0, -0.028), (0.018, -0.022), (-0.018, -0.022),
                (0.030, -0.010), (-0.030, -0.010), (0.012, -0.034), (-0.012, -0.034)]
        for ox, oz in offs:
            DirectLabel(parent=self.root, text=text, scale=scale, pos=(ox, 0, y + oz),
                        frameColor=(0, 0, 0, 0), text_fg=(0, 0, 0, 0.16),
                        **_kw(self.font_title))
        return DirectLabel(parent=self.root, text=text, scale=scale, pos=(0, 0, y),
                           frameColor=(0, 0, 0, 0), text_fg=color, **_kw(self.font_title))

    def _label(self, text, pos, scale=0.045, color=TEXT, align=None):
        kw = _kw(self.font_ui)
        if align is not None:
            kw["text_align"] = align
        return DirectLabel(parent=self.root, text=text, scale=scale, pos=pos,
                           frameColor=(0, 0, 0, 0), text_fg=color, **kw)

    def _entry(self, pos, width=14, initial="", obscured=False):
        kw = _kw(self.font_ui)
        e = DirectEntry(
            parent=self.root, scale=0.050, pos=pos,
            initialText=initial, width=width, numLines=1,
            frameColor=(0.10, 0.09, 0.05, 0.85), text_fg=TEXT,
            obscured=obscured, **kw,
        )
        return e

    def show(self):
        self.root.show()

    def hide(self):
        self.root.hide()


# ── Константы перепривязки клавиш ──────────────────────────────────────────

REBINDABLE_ACTIONS = [
    ("forward",   "Вперёд"),
    ("backward",  "Назад"),
    ("left",      "Влево"),
    ("right",     "Вправо"),
    ("jump",      "Прыжок"),
    ("gas",       "Газ"),
    ("ult",       "Ульт"),
    ("weapon1",   "Оружие 1 - Сироп"),
    ("weapon2",   "Оружие 2 - Майо"),
    ("weapon3",   "Оружие 3 - Улей"),
    ("camera",    "Камера"),
    ("place_cup", "Стакан"),
    ("emote1",    "Эмоция Flex"),
    ("emote2",    "Эмоция Dance"),
    ("emote3",    "Эмоция Wave"),
    ("chat",      "Чат"),
]

DEFAULT_BINDINGS = {
    "forward": "w",    "backward": "s",  "left": "a",     "right": "d",
    "jump": "space",   "gas": "lshift",  "ult": "q",
    "weapon1": "1",    "weapon2": "2",   "weapon3": "3",
    "camera": "c",     "place_cup": "r",
    "emote1": "f",     "emote2": "g",    "emote3": "v",
    "chat": "enter",
}

ALL_BINDABLE_KEYS = [
    "a","b","c","d","e","f","g","h","i","j","k","l","m",
    "n","o","p","q","r","s","t","u","v","w","x","y","z",
    "0","1","2","3","4","5","6","7","8","9",
    "space","tab","lshift","rshift","lcontrol","rcontrol",
    # lalt/ralt намеренно исключены: Alt+F4 закрывает окно на уровне ОС
    "f1","f2","f3","f4","f5","f6","f7","f8","f9","f10","f11","f12",
    "arrow_up","arrow_down","arrow_left","arrow_right",
    "insert","delete","home","end","page_up","page_down",
]

_KEY_DISPLAY = {
    "space": "Пробел", "lshift": "L.Shift", "rshift": "R.Shift",
    "lcontrol": "L.Ctrl", "rcontrol": "R.Ctrl", "lalt": "L.Alt", "ralt": "R.Alt",
    "arrow_up": "↑", "arrow_down": "↓", "arrow_left": "←", "arrow_right": "→",
    "insert": "Ins", "delete": "Del", "home": "Home", "end": "End",
    "page_up": "PgUp", "page_down": "PgDn",
}


def _key_label(key):
    return _KEY_DISPLAY.get(key, key.upper())


# ── Экран перепривязки клавиш ───────────────────────────────────────────────

class KeyBindingsScreen(Screen):
    """Таблица привязок клавиш. Клик по кнопке активирует режим перепривязки."""

    # 8 действий в левой колонке, остальные — в правой
    _COL_SPLIT = 8

    def __init__(self, app):
        super().__init__(app, panel=(-0.85, 0.85, -0.78, 0.82))
        self._rebinding = None   # действие ожидающее перепривязки (str или None)
        self._key_btns = {}      # action -> DirectButton
        self._rebind_label = None

        self._title("УПРАВЛЕНИЕ", y=0.70, scale=0.12)

        self._build_rows()
        self._button("Сброс", -0.64, self._reset_defaults, hw=0.22, hh=0.048)
        self._button("Назад", -0.72, self._back, hw=0.22, hh=0.048)

        # создаём ПОСЛЕ всех кнопок — DirectGui рендерит детей в порядке добавления
        self._rebind_label = DirectLabel(
            parent=self.root, text="Нажмите клавишу...",
            scale=0.065, pos=(0, 0, 0),
            frameColor=(0, 0, 0, 0.72), frameSize=(-1.1, 1.1, -0.12, 0.12),
            text_fg=(1, 1, 0.3, 1), **_kw(self.font_ui),
        )
        self._rebind_label.hide()

    def _build_rows(self):
        # удалить старые кнопки и метки
        for b in self._key_btns.values():
            b.destroy()
        self._key_btns.clear()
        if hasattr(self, "_row_labels"):
            for lbl in self._row_labels:
                lbl.destroy()
        self._row_labels = []

        left_actions  = REBINDABLE_ACTIONS[:self._COL_SPLIT]
        right_actions = REBINDABLE_ACTIONS[self._COL_SPLIT:]
        row_h = 0.082

        for col_idx, col_actions in enumerate((left_actions, right_actions)):
            cx = -0.42 + col_idx * 0.84
            start_y = 0.56
            for row_i, (action, label) in enumerate(col_actions):
                y = start_y - row_i * row_h
                lbl = DirectLabel(
                    parent=self.root, text=label,
                    scale=0.040, pos=(cx - 0.03, 0, y),
                    frameColor=(0,0,0,0), text_fg=TEXT,
                    text_align=2,
                    **_kw(self.font_ui),
                )
                self._row_labels.append(lbl)
                key = self.app.key_bindings.get(action, "?")
                btn = self._small_key_btn(_key_label(key), y, cx + 0.24, action)
                self._key_btns[action] = btn

        # после rebuild поднимаем overlay-label наверх дерева рендера
        if self._rebind_label is not None:
            self._rebind_label.reparentTo(self.root)

    def _small_key_btn(self, text, y, x, action):
        tex = _button_texture("all", size=64, radius=14)
        btn = DirectButton(
            parent=self.root, text=text,
            command=self._start_rebind, extraArgs=[action],
            relief=None, pos=(x, 0, y),
            image=tex, image_scale=(0.10, 1, 0.038),
            image_color=BTN, text_fg=ACCENT, text_scale=0.038,
            text_pos=(0, -0.012), **_kw(self.font_ui),
        )
        btn.bind(DGG.WITHIN,   self._on_enter, [btn])
        btn.bind(DGG.WITHOUT,  self._on_exit,  [btn])
        btn.bind(DGG.B1PRESS,  self._on_press, [btn])
        btn.bind(DGG.B1RELEASE,self._on_enter, [btn])
        return btn

    def _stop_capture(self):
        """Снять все временные слушатели режима ожидания клавиши."""
        for k in ALL_BINDABLE_KEYS:
            self.app.ignore(k)
        # восстанавливаем глобальный Escape (не просто ignore — иначе пауза перестаёт работать)
        self.app.accept("escape", self.app._on_escape)
        self._rebind_label.hide()
        self._rebinding = None

    def _start_rebind(self, action):
        if self._rebinding:
            return
        self._rebinding = action
        self._rebind_label.show()
        for key in ALL_BINDABLE_KEYS:
            self.app.accept(key, self._key_captured, [key])
        # escape отменяет без сохранения
        self.app.accept("escape", self._cancel_rebind)

    def _cancel_rebind(self):
        self._stop_capture()
        self._build_rows()

    def _key_captured(self, key):
        action = self._rebinding
        self._stop_capture()
        if action:
            # проверить не занята ли клавиша другим действием
            conflict = next(
                (a for a, k in self.app.key_bindings.items() if k == key and a != action),
                None
            )
            if conflict:
                # снять у конфликтующего действия
                self.app.key_bindings[conflict] = ""
            self.app.key_bindings[action] = key
            self.app._save_settings()
            self.app._setup_game_input()
        self._build_rows()

    def _reset_defaults(self):
        if self._rebinding:
            return
        self.app.key_bindings = dict(DEFAULT_BINDINGS)
        self.app._save_settings()
        self.app._setup_game_input()
        self._build_rows()

    def _back(self):
        if self._rebinding:
            self._stop_capture()
        self.hide()
        self.app.settings_menu.show()

    def show(self):
        super().show()
        self._build_rows()


# ── Главное меню ─────────────────────────────────────────────────────────────

class MainMenu(Screen):
    """Хаб-экран. Кнопки = переходы между фазами."""

    def __init__(self, app):
        super().__init__(app)
        self._title("SWAGA", y=0.66, scale=0.20)
        self._title("уровень 0 - бэкрумы", y=0.50, color=ACCENT2, scale=0.055)

        self._label("Ваш ник:", (0, 0, 0.36), scale=0.045, color=ACCENT)
        nick_kw = _kw(self.font_ui)
        self.name_entry = DirectEntry(
            parent=self.root, scale=0.055, pos=(-0.24, 0, 0.26),
            initialText=app.player_name, width=12, numLines=1,
            frameColor=(0.10, 0.09, 0.05, 0.85), text_fg=TEXT, **nick_kw,
        )

        self._button_stack([
            ("Тараканья нора (бой)", app.start_combat),
            ("Обучение", app.start_tutorial),
            ("Улей (ферма)", app.goto_farm),
            ("Магазин", app.goto_shop),
            ("Настройки", app.open_settings),
            ("Выход", app.quit_game),
        ], top_y=0.14)

    def get_name(self):
        txt = (self.name_entry.get() or "").strip()
        return txt[:20] if txt else "Игрок"

    def set_nick(self, nick: str):
        """Установить ник (после авторизации)."""
        try:
            self.name_entry.set(nick)
        except Exception:
            pass


# ── Пауза ────────────────────────────────────────────────────────────────────

class PauseMenu(Screen):
    """Пауза во время боя (по Esc)."""

    def __init__(self, app):
        super().__init__(app)
        self.root["frameColor"] = (0.02, 0.02, 0.01, 0.22)
        self._title("ПАУЗА", y=0.42)
        self._button_stack([
            ("Продолжить", app.resume),
            ("Настройки", app.open_settings),
            ("В меню (Хаб)", app.goto_hub),
        ], top_y=0.12)


# ── Настройки ────────────────────────────────────────────────────────────────

_GFX_LABELS = ["Низкое", "Среднее", "Высокое"]
_GFX_VALUES = ["low", "medium", "high"]


class SettingsMenu(Screen):
    """Настройки: разрешение, полный экран, громкость, управление, разлогин."""

    def __init__(self, app):
        super().__init__(app, panel=(-0.58, 0.58, -0.92, 0.78))
        self._title("НАСТРОЙКИ", y=0.64)

        # --- разрешение ---
        DirectLabel(parent=self.root, text="Разрешение:", scale=0.050,
                    pos=(-0.52, 0, 0.44), frameColor=(0, 0, 0, 0),
                    text_fg=TEXT, text_align=0, **_kw(self.font_ui))
        self.res_menu = DirectOptionMenu(
            parent=self.root, scale=0.058, pos=(0.05, 0, 0.44),
            items=RESOLUTIONS, initialitem=0, highlightColor=BTN_HI,
            frameColor=BTN, text_fg=TEXT, relief="flat",
            popupMarker_scale=0.5, **_kw(self.font_ui),
        )

        # --- полный экран ---
        DirectLabel(parent=self.root, text="Полный экран:", scale=0.050,
                    pos=(-0.52, 0, 0.28), frameColor=(0, 0, 0, 0),
                    text_fg=TEXT, text_align=0, **_kw(self.font_ui))
        self.fs_check = DirectCheckButton(
            parent=self.root, scale=0.058, pos=(0.05, 0, 0.28),
            boxPlacement="right", frameColor=BTN, text_fg=TEXT,
            command=self._noop, **_kw(self.font_ui),
        )

        # --- качество графики ---
        DirectLabel(parent=self.root, text="Графика:", scale=0.048,
                    pos=(-0.52, 0, 0.12), frameColor=(0, 0, 0, 0),
                    text_fg=ACCENT2, text_align=0, **_kw(self.font_ui))
        cur_q = getattr(app, "gfx_quality", "medium")
        cur_idx = _GFX_VALUES.index(cur_q) if cur_q in _GFX_VALUES else 1
        self.gfx_menu = DirectOptionMenu(
            parent=self.root, scale=0.058, pos=(0.05, 0, 0.12),
            items=_GFX_LABELS, initialitem=cur_idx, highlightColor=BTN_HI,
            frameColor=BTN, text_fg=ACCENT2, relief="flat",
            popupMarker_scale=0.5, **_kw(self.font_ui),
            command=self._on_gfx_change,
        )
        self._gfx_restart_lbl = DirectLabel(
            parent=self.root, text="", scale=0.038,
            pos=(0.0, 0, -0.01), frameColor=(0, 0, 0, 0),
            text_fg=(1.0, 0.55, 0.1, 1), **_kw(self.font_ui))

        # --- громкость музыки ---
        DirectLabel(parent=self.root, text="Музыка:", scale=0.048,
                    pos=(-0.52, 0, -0.10), frameColor=(0, 0, 0, 0),
                    text_fg=ACCENT, text_align=0, **_kw(self.font_ui))
        self.music_slider = DirectSlider(
            parent=self.root, range=(0, 100),
            value=int(app._music_vol * 100),
            pageSize=5, pos=(0.12, 0, -0.10), scale=0.30,
            frameColor=(0.20, 0.16, 0.08, 0.80),
            thumb_frameColor=ACCENT,
            command=self._on_music_slider,
        )
        self._music_val_lbl = DirectLabel(
            parent=self.root, text=f"{int(app._music_vol*100)}%",
            scale=0.045, pos=(0.48, 0, -0.10),
            frameColor=(0, 0, 0, 0), text_fg=TEXT, **_kw(self.font_ui))

        # --- громкость звуков ---
        DirectLabel(parent=self.root, text="Звуки:", scale=0.048,
                    pos=(-0.52, 0, -0.26), frameColor=(0, 0, 0, 0),
                    text_fg=ACCENT, text_align=0, **_kw(self.font_ui))
        self.sfx_slider = DirectSlider(
            parent=self.root, range=(0, 100),
            value=int(app._sfx_vol * 100),
            pageSize=5, pos=(0.12, 0, -0.26), scale=0.30,
            frameColor=(0.20, 0.16, 0.08, 0.80),
            thumb_frameColor=ACCENT,
            command=self._on_sfx_slider,
        )
        self._sfx_val_lbl = DirectLabel(
            parent=self.root, text=f"{int(app._sfx_vol*100)}%",
            scale=0.045, pos=(0.48, 0, -0.26),
            frameColor=(0, 0, 0, 0), text_fg=TEXT, **_kw(self.font_ui))

        # --- кнопки ---
        self._button("Управление", -0.42, app.open_keybindings, hw=0.38, hh=0.050)
        self._button("Применить",  -0.56, self._apply,           hw=0.38, hh=0.050)

        from common import config as _cfg
        if getattr(_cfg, "AUTH_ENABLED", False):
            self._button("Выйти из аккаунта", -0.70, app.do_logout, hw=0.38, hh=0.050)
            self._button("Назад", -0.84, app.close_settings, hw=0.38, hh=0.050)
        else:
            self._button("Назад", -0.70, app.close_settings, hw=0.38, hh=0.050)

    def _noop(self, *_):
        pass

    def _on_gfx_change(self, label):
        idx = _GFX_LABELS.index(label) if label in _GFX_LABELS else 1
        new_q = _GFX_VALUES[idx]
        self.app.set_gfx_quality(new_q)
        if new_q != self.app.gfx_quality:
            self._gfx_restart_lbl["text"] = "Перезапустите игру"
        else:
            self._gfx_restart_lbl["text"] = ""

    def _on_music_slider(self):
        v = int(self.music_slider["value"])
        self._music_val_lbl["text"] = f"{v}%"
        self.app._music_vol = v / 100.0
        if self.app._music and hasattr(self.app._music, "setVolume"):
            self.app._music.setVolume(self.app._music_vol)
        self.app._save_settings()

    def _on_sfx_slider(self):
        v = int(self.sfx_slider["value"])
        self._sfx_val_lbl["text"] = f"{v}%"
        self.app._sfx_vol = v / 100.0
        self.app._save_settings()

    def _apply(self):
        w, h = (int(v) for v in self.res_menu.get().split("x"))
        fullscreen = bool(self.fs_check["indicatorValue"])
        self.app.apply_video_settings(w, h, fullscreen)
        self.app.apply_audio_settings(
            self.music_slider["value"] / 100.0,
            self.sfx_slider["value"] / 100.0,
        )


# ── Экран входа / регистрации ─────────────────────────────────────────────────

class LoginScreen(Screen):
    """Экран авторизации: логин + пароль + адрес auth-сервера."""

    # поле с меткой над ним (по центру)
    def _field(self, label, y_label, y_entry, width=18, obscured=False, hint=""):
        from panda3d.core import TextNode
        self._label(label, (0, 0, y_label), scale=0.040, color=ACCENT,
                    align=TextNode.ACenter)
        if hint:
            self._label(hint, (0, 0, y_label - 0.065), scale=0.028,
                        color=(0.65, 0.65, 0.55, 1), align=TextNode.ACenter)
        entry_x = -(width * 0.050 * 0.48)
        return self._entry((entry_x, 0, y_entry), width=width, obscured=obscured)

    def __init__(self, app):
        super().__init__(app, panel=(-0.54, 0.54, -0.76, 0.82))
        self._title("SWAGA", y=0.68, scale=0.18)
        self._label("Войдите, чтобы играть", (0, 0, 0.50),
                    scale=0.044, color=ACCENT2)

        self.e_login = self._field("Логин",  0.33, 0.22, width=18)
        self.e_pass  = self._field("Пароль", 0.08, -0.03, width=18, obscured=True)

        # auth-сервер — мелко, отдельно
        self._label("Auth-сервер", (0, 0, -0.24), scale=0.032,
                    color=(0.65, 0.65, 0.55, 1))
        entry_x = -(22 * 0.042 * 0.48)
        self.e_auth = self._entry((entry_x, 0, -0.33), width=22,
                                  initial=app._auth_server)
        self.e_auth["scale"] = 0.042

        self._button_stack([
            ("Войти",       self._do_login),
            ("Регистрация", self._goto_register),
        ], top_y=-0.47, hw=0.36, hh=0.055)

        self._error_label = DirectLabel(
            parent=self.root, text="", scale=0.038, pos=(0, 0, -0.66),
            frameColor=(0, 0, 0, 0), text_fg=(1, 0.35, 0.35, 1),
            **_kw(self.font_ui),
        )

    def show_error(self, text: str):
        self._error_label["text"] = text

    def _do_login(self):
        self.show_error("")
        login  = (self.e_login.get() or "").strip()
        pw     = self.e_pass.get() or ""
        server = (self.e_auth.get() or "").strip()
        if not login or not pw:
            self.show_error("Введите логин и пароль")
            return
        self.app.do_login(login, pw, server)

    def _goto_register(self):
        self.hide()
        self.app.register_screen.show()


class RegisterScreen(Screen):
    """Экран регистрации нового аккаунта."""

    def _field(self, label, y_label, y_entry, width=18, obscured=False, hint=""):
        from panda3d.core import TextNode
        self._label(label, (0, 0, y_label), scale=0.040, color=ACCENT,
                    align=TextNode.ACenter)
        if hint:
            self._label(hint, (0, 0, y_label - 0.058), scale=0.026,
                        color=(0.60, 0.60, 0.50, 1), align=TextNode.ACenter)
        entry_x = -(width * 0.050 * 0.48)
        return self._entry((entry_x, 0, y_entry), width=width, obscured=obscured)

    def __init__(self, app):
        super().__init__(app, panel=(-0.54, 0.54, -0.90, 0.82))
        self._title("РЕГИСТРАЦИЯ", y=0.68, scale=0.11)

        self.e_login = self._field(
            "Логин", 0.52, 0.40, width=18,
            hint="3-20 символов: A-Z a-z 0-9 _")
        self.e_nick  = self._field("Ник в игре", 0.22, 0.11, width=18)
        self.e_pass  = self._field("Пароль",     -0.04, -0.15, width=18, obscured=True)
        self.e_pass2 = self._field("Повторить пароль", -0.29, -0.40, width=18, obscured=True)

        self._label("Auth-сервер", (0, 0, -0.56), scale=0.030,
                    color=(0.65, 0.65, 0.55, 1))
        entry_x = -(22 * 0.040 * 0.48)
        self.e_auth = self._entry((entry_x, 0, -0.64), width=22,
                                  initial=app._auth_server)
        self.e_auth["scale"] = 0.040

        self._button_stack([
            ("Создать аккаунт", self._do_register),
            ("Назад",           self._goto_login),
        ], top_y=-0.73, hw=0.38, hh=0.055)

        self._error_label = DirectLabel(
            parent=self.root, text="", scale=0.036, pos=(0, 0, -0.83),
            frameColor=(0, 0, 0, 0), text_fg=(1, 0.35, 0.35, 1),
            **_kw(self.font_ui),
        )

    def show_error(self, text: str):
        self._error_label["text"] = text

    def _do_register(self):
        self.show_error("")
        login  = (self.e_login.get() or "").strip()
        nick   = (self.e_nick.get()  or "").strip()
        pw     = self.e_pass.get()  or ""
        pw2    = self.e_pass2.get() or ""
        server = (self.e_auth.get() or "").strip()
        if not login or not nick or not pw:
            self.show_error("Заполните все поля")
            return
        if pw != pw2:
            self.show_error("Пароли не совпадают")
            return
        self.app.do_register(login, nick, pw, server)

    def _goto_login(self):
        self.hide()
        self.app.login_screen.show()


# ── Заглушки ферма/магазин ────────────────────────────────────────────────────

class InfoScreen(Screen):
    """Простой 2D-экран-заглушка для Фермы/Магазина (с кнопкой Назад)."""

    def __init__(self, app, title, lines):
        super().__init__(app)
        self._title(title, y=0.6)
        y = 0.30
        for ln in lines:
            DirectLabel(parent=self.root, text=ln, scale=0.055, pos=(0, 0, y),
                        frameColor=(0, 0, 0, 0), text_fg=TEXT, **_kw(self.font_ui))
            y -= 0.13
        self._button("Назад в меню", -0.55, app.goto_hub)
