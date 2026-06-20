"""Единый конфиг ассетов: константа -> путь до файла.

Кладите файлы в assets/textures, assets/sounds, assets/fonts.
Если файла нет — загрузчик (client/assets.py) подставит заглушку и не упадёт.
Чтобы добавить новый ассет: положите файл в нужную папку и добавьте сюда константу.
"""

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(_ROOT, "assets")
TEXTURES_DIR = os.path.join(ASSETS_DIR, "textures")
SOUNDS_DIR = os.path.join(ASSETS_DIR, "sounds")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")
MODELS_DIR = os.path.join(ASSETS_DIR, "models")
PAPICH_DIR = os.path.join(_ROOT, "papich")

# 3D-модель главного босса (с привязанными текстурами).
# Поддерживаются .glb/.gltf (нужен panda3d-gltf), .egg, .bam.
# Текстуры, привязанные внутри glTF, подхватываются автоматически.
BOSS_MODEL = os.path.join(PAPICH_DIR, "arthas-папич.glb")
# доворот модели босса (градусы), если её «перёд» смотрит не туда.
# Подбери одно из 0 / 90 / 180 / 270, чтобы Папаня смотрел лицом на игрока.
BOSS_MODEL_YAW = 180.0

# 3D-модель BLACK KING (assets/models/black_king.glb). Нет файла → тёмный процедурный таракан.
BLACK_KING_MODEL = os.path.join(MODELS_DIR, "black_king.glb")
BLACK_KING_MODEL_YAW = 0.0   # скорректируй, если модель смотрит не туда

# Модели дропа с тараканов (assets/models/*.glb). Нет файла → светящийся кубик.
HONEY_JAR_MODEL = os.path.join(MODELS_DIR, "honey_jar.glb")     # дроп honey
SYRUP_MODEL = os.path.join(MODELS_DIR, "green_syrup.glb")       # дроп syrup
MAYO_MODEL = os.path.join(MODELS_DIR, "mayo.glb")               # дроп mayo
LIT_ENERGY_MODEL = os.path.join(MODELS_DIR, "lit_energy.glb")   # предмет LIT ENERGY

# Дроп-вид (kind -> модель). Нет файла → светящийся кубик соответствующего цвета.
DROP_MODELS = {
    "honey": HONEY_JAR_MODEL,
    "syrup": SYRUP_MODEL,
    "mayo": MAYO_MODEL,
    "lit_energy": LIT_ENERGY_MODEL,
}


def _t(name):
    return os.path.join(TEXTURES_DIR, name)


def _s(name):
    return os.path.join(SOUNDS_DIR, name)


def _f(name):
    return os.path.join(FONTS_DIR, name)


# ---------- Текстуры (assets/textures/) ----------
LITVIN_TEXTURE = _t("litvin.png")
# Текстуры карты backrooms (тайлятся). Нет файла -> остаётся сплошной цвет палитры.
BACKROOMS_FLOOR_TEXTURE = _t("backrooms_floor.jpg")
BACKROOMS_WALL_TEXTURE = _t("backrooms_wall.jpg")
# 4 картинки на боковые стены центрального параллелепипеда (витрины).
# По умолчанию все = litvin.png; замени файлы, чтобы стороны были разными.
SHOWCASE_TEXTURES = [
    _t("showcase_1.png"),
    _t("showcase_2.png"),
    _t("showcase_3.png"),
    _t("showcase_4.png"),
]
# Текстура настенного врага «ЩЕЛЬ» (натягивается на два прижатых шара).
# Положи файл assets/textures/slit.png. Нет файла -> шахматка «missing».
SLIT_TEXTURE = _t("slit.png")
PLAYER_BASE_TEXTURE = _t("player_base.png")
COCKROACH_TEXTURE = _t("cockroach.png")
BOSS_TEXTURE = _t("boss_papanya.png")
BEE_TEXTURE = _t("bee.png")
MEME_BG_TEXTURE = _t("meme_bg.png")
ICON_SYRUP_TEXTURE = _t("icon_syrup.png")
ICON_MAYONEZ_TEXTURE = _t("icon_mayonez.png")
ICON_HONEY_TEXTURE = _t("icon_honey.png")

# ---------- Звуки (assets/sounds/) ----------
# Струи: START проигрывается один раз, затем зацикленный LOOP (пока зажата ЛКМ).
SFX_SHOOT_SYRUP_START = _s("sfx_shoot_syrup_start.wav")
SFX_SHOOT_SYRUP_LOOP = _s("sfx_shoot_syrup_loop.wav")
SFX_SHOOT_MAYONEZ_START = _s("sfx_shoot_mayonez_start.wav")
SFX_SHOOT_MAYONEZ_LOOP = _s("sfx_shoot_mayonez_loop.wav")

# Вход на сервер (старт первой фазы)
SFX_JOIN_PHASE1 = _s("sfx_join_phase1.wav")

# Тараканы
SFX_COCKROACH_DEATH = _s("sfx_cockroach_death.wav")   # убийство таракана
SFX_COCKROACH_STEP = _s("sfx_cockroach_step.wav")     # ходьба тараканов (луп, пока живы)
SFX_COCKROACH_LAUGH = _s("sfx_cockroach_laugh.wav")   # ржач над игроком во время ЩЕЛИ (луп)

# Червь-игрок
SFX_WORM_STEP = _s("sfx_worm_step.wav")               # шаги червя (луп при движении)
SFX_PLAYER_HURT = _s("sfx_player_hurt.wav")           # урон от таракана

# Босс «Папаня»
SFX_BOSS_SPAWN = _s("sfx_boss_spawn.wav")             # появление
SFX_BOSS_HIT = _s("sfx_boss_hit.wav")                 # получает урон (сироп)
SFX_BOSS_DEATH = _s("sfx_boss_death.wav")             # смерть
SFX_BOSS_THROW = _s("sfx_boss_throw.wav")             # бросок взрывного снаряда
SFX_BOSS_VOICES = [                                   # случайные реплики (любое кол-во)
    _s("sfx_boss_voice_1.wav"),
    _s("sfx_boss_voice_2.wav"),
    _s("sfx_boss_voice_3.wav"),
]

SFX_EXPLOSION = _s("sfx_explosion.wav")
SFX_PICKUP = _s("sfx_pickup.wav")        # подбор дропа с таракана
SFX_LIT_ENERGY = _s("sfx_lit_energy.wav")  # активация LIT ENERGY (один раз при использовании)

# ЩЕЛЬ (настенный враг). Нет файла -> тихо.
SFX_SLIT_SPAWN = _s("sfx_slit_spawn.wav")        # появление щели
SFX_SLIT_CALM = _s("sfx_slit_calm.wav")          # одна щель удовлетворена (шкала заполнена)
SFX_SLIT_DEFEATED = _s("sfx_slit_defeated.wav")  # победа над щелью (все повержены)

# Синие неоновые муравьи и их «шкибиди-зелье» (нет файла -> тихо)
SFX_NEON_ANT_DEATH = _s("sfx_neon_ant_death.wav")
SFX_SKIBIDI_SHOOT = _s("sfx_skibidi_shoot.wav")    # выстрел неонового муравья
SFX_SKIBIDI_HIT = _s("sfx_skibidi_hit.wav")        # попадание зелья

# BLACK KING — звуки (assets/sounds/sfx_bk_*.wav). Нет файла → тихо.
SFX_BLACK_KING_SPAWN = _s("sfx_bk_spawn.wav")
SFX_BLACK_KING_DEATH = _s("sfx_bk_death.wav")
SFX_BLACK_KING_HIT = _s("sfx_bk_hit.wav")
SFX_BLACK_KING_VOICES = [           # набор случайных реплик (добавляй файлы по мере)
    _s("sfx_bk_voice_1.wav"),
    _s("sfx_bk_voice_2.wav"),
    _s("sfx_bk_voice_3.wav"),
]

# ---------- Музыка (assets/sounds/) ----------
MUSIC_HUB = _s("music_hub.wav")           # главное меню (опц.)
MUSIC_PHASE1 = _s("music_phase1.wav")     # фон обычной первой фазы
MUSIC_BOSS = _s("music_boss.wav")         # фон битвы с Папаней
MUSIC_SLIT = _s("music_slit.wav")         # событие ЩЕЛИ — первые 20 секунд
MUSIC_SLIT_FINAL = _s("music_slit_final.wav")  # последние 10 секунд (тревога)
MUSIC_BLACK_KING = _s("music_black_king.wav")   # тема финальной фазы BLACK KING

# ---------- Шрифты (assets/fonts/) ----------
# Разделены по элементам игры. Если файла нет — берётся системный шрифт
# по умолчанию (тот же, что сейчас, с поддержкой кириллицы).
FONT_TITLE = _f("title.ttf")     # заголовки (SWAGA, названия экранов)
FONT_UI = _f("ui.ttf")           # кнопки и подписи меню/настроек
FONT_HUD = _f("hud.ttf")         # боевой HUD (HP, очки, фаза, прицел)
FONT_CHAT = _f("chat.ttf")       # чат и строка подсказок
FONT_WORLD = _f("world.otf")     # 3D-текст: ники над червями, шкала босса

