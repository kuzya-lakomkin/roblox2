"""Загрузка ассетов с безопасным fallback (заглушка вместо вылета).

Пути берутся из client/asset_config.py (константа -> путь).
- load_texture: принимает либо имя файла в assets/textures, либо готовый путь
  (например, asset_config.LITVIN_TEXTURE). Нет файла -> шахматка "missing".
- load_sound: нет файла -> None (звук просто не играет, без вылета).
"""

import os

from panda3d.core import Filename, PNMImage, Texture

from client import asset_config as AC

TEXTURE_DIR = AC.TEXTURES_DIR

_tex_cache = {}
_snd_cache = {}


def _placeholder_texture(size=64):
    """Шахматка маджента/чёрный — признак отсутствующего файла."""
    img = PNMImage(size, size)
    cell = size // 8
    for x in range(size):
        for y in range(size):
            if ((x // cell) + (y // cell)) % 2 == 0:
                img.setXel(x, y, 0.9, 0.0, 0.9)
            else:
                img.setXel(x, y, 0.05, 0.05, 0.05)
    tex = Texture("missing")
    tex.load(img)
    return tex


def _resolve_texture(name):
    """Превратить имя/путь в список путей-кандидатов."""
    if os.path.sep in name or (os.path.altsep and os.path.altsep in name):
        return [name]                       # уже полный путь (из asset_config)
    if "." in name:
        return [os.path.join(TEXTURE_DIR, name)]
    return [os.path.join(TEXTURE_DIR, name + ext) for ext in (".png", ".jpg", ".jpeg")]


def load_texture(loader, name):
    if name in _tex_cache:
        return _tex_cache[name]
    tex = None
    for path in _resolve_texture(name):
        if os.path.exists(path):
            try:
                tex = loader.loadTexture(str(Filename.fromOsSpecific(path)))
            except Exception:
                tex = None
            if tex:
                break
    if tex is None:
        tex = _placeholder_texture()
    # сглаживание текстур: трилинейная фильтрация (мипмапы) + анизотропия
    tex.setMinfilter(Texture.FTLinearMipmapLinear)
    tex.setMagfilter(Texture.FTLinear)
    tex.setAnisotropicDegree(8)
    _tex_cache[name] = tex
    return tex


def texture_exists(name):
    return any(os.path.exists(p) for p in _resolve_texture(name))


_font_cache = {}


def load_font(loader, path):
    """Загрузить шрифт по пути из asset_config. Нет файла/ошибка -> None."""
    if path in _font_cache:
        return _font_cache[path]
    f = None
    if os.path.exists(path):
        try:
            f = loader.loadFont(str(Filename.fromOsSpecific(path)))
            if f and f.isValid():
                f.setPixelsPerUnit(64)
            else:
                f = None
        except Exception:
            f = None
    _font_cache[path] = f
    return f


def load_sound(loader, path, loop=False):
    """Загрузить звук по пути из asset_config. Нет файла -> None (без вылета)."""
    key = (path, loop)
    if key in _snd_cache:
        return _snd_cache[key]
    snd = None
    if os.path.exists(path):
        try:
            snd = loader.loadSfx(str(Filename.fromOsSpecific(path)))
            if snd and loop:
                snd.setLoop(True)
        except Exception:
            snd = None
    _snd_cache[key] = snd
    return snd


_model_cache = {}
_gltf_ready = False


def _ensure_gltf():
    """panda3d-gltf при импорте регистрирует загрузчик для .glb/.gltf."""
    global _gltf_ready
    if not _gltf_ready:
        try:
            import gltf  # noqa: F401
        except Exception:
            pass
        _gltf_ready = True


def load_model(loader, path):
    """Загрузить 3D-модель (.glb/.gltf/.egg/.bam). Нет/битый файл -> None."""
    if path in _model_cache:
        return _model_cache[path]
    model = None
    if os.path.exists(path) and _valid_model_file(path):
        _ensure_gltf()
        try:
            model = loader.loadModel(str(Filename.fromOsSpecific(path)))
        except Exception:
            model = None
        if model and model.isEmpty():
            model = None
    _model_cache[path] = model
    return model


def _valid_model_file(path):
    """Беглая проверка сигнатуры, чтобы не падать на подменённых файлах
    (напр. JPEG, переименованный в .glb)."""
    ext = os.path.splitext(path)[1].lower()
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        return False
    if ext == ".glb":
        return head[:4] == b"glTF"            # бинарный glTF
    if ext == ".gltf":
        return head.lstrip()[:1] == b"{"      # JSON glTF
    if ext == ".bam":
        return head[:6] == b"pbj\x00\n\r"
    return ext in (".egg", ".obj")            # текстовые — пусть грузит сам


_music_cache = {}


def load_music(loader, path, loop=True):
    """Загрузить музыку. Грузим через loadSfx (в память) — надёжнее, чем
    стриминг больших WAV через loadMusic (даёт тишину на части сборок Panda).
    Нет файла -> None."""
    if path in _music_cache:
        return _music_cache[path]
    snd = None
    if os.path.exists(path):
        try:
            snd = loader.loadSfx(str(Filename.fromOsSpecific(path)))
            # битый/неподдерживаемый файл движок «открывает», но length()==0
            if snd and snd.length() <= 0:
                snd = None
            elif snd:
                snd.setLoop(loop)
        except Exception:
            snd = None
    _music_cache[path] = snd
    return snd
