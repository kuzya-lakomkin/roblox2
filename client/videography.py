"""12 кинематографических ракурсов + запись видео для режима ВИДЕОГРАФИЯ.

Запись: сырые RGB-кадры из Panda3D → FFmpeg-пайп (фоновый поток) → MP4.
Основной поток тратит только ~5мс на GPU→CPU копию; сжатие не блокирует игру.
"""
import math
import os
import queue
import subprocess
import threading


def _l(a, b, t):
    return (a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t, a[2]+(b[2]-a[2])*t)


def _orbit(cx, cy, z, r, a0, a1, t):
    a = a0 + (a1-a0)*t
    return (cx + math.cos(a)*r, cy + math.sin(a)*r, z)


# (name, duration_secs, cam_pos(t)->xyz, lookat(t)->xyz)
SHOTS = [
    ("Орбит над ареной",    20, lambda t: _orbit(0, 0, 28, 38, 0, math.pi, t),      lambda t: (0.0,  0.0, 5.0)),
    ("Въезд с юга",         18, lambda t: _l((0,-50,2.5),(0,5,2.5), t),              lambda t: _l((0,-28,2.0),(0,25,2.0), t)),
    ("Арена Папани",        18, lambda t: _l((0,18,5),(0,42,5), t),                  lambda t: (0.0, 46.0, 3.0)),
    ("Птичий глаз",         16, lambda t: _l((-50,-50,38),(0,0,38), t),              lambda t: (0.0,  0.0, 4.0)),
    ("Западный проход",     14, lambda t: _l((-30,-15,3),(-30,15,3), t),             lambda t: _l((-18,-15,3),(-18,15,3), t)),
    ("Платформа уровня 2",  18, lambda t: _orbit(0, 0, 16, 20, 0, math.pi, t),      lambda t: (0.0,  0.0, 14.0)),
    ("Прыжковый пад",       14, lambda t: (0.0, -28.0, 0.8+t*11),                   lambda t: (0.0, -26.0+t*4, 1.5+t*9)),
    ("Диагональный пролёт", 20, lambda t: _l((-38,38,8),(38,-38,8), t),              lambda t: (0.0,  0.0, 4.0)),
    ("Витрина SWAGA",       14, lambda t: _orbit(0, -2, 4, 10, -0.8, 3.9, t),       lambda t: (0.0, -2.0, 5.0)),
    ("Пьедесталы углов",    16, lambda t: _l((42,-42,8),(-42,42,8), t),              lambda t: (0.0,  0.0, 3.0)),
    ("Ползущий пол",        18, lambda t: _l((0,-25,0.6),(0,25,0.6), t),             lambda t: _l((0,-23,1.2),(0,27,1.2), t)),
    ("Финальный отъезд",    22, lambda t: (0.0, -10-t*50, 4+t*36),                  lambda t: (0.0,  0.0, 3.0)),
]


class VideoRecorder:
    """Запись видео без промежуточных файлов: RGB-байты → FFmpeg-пайп → MP4.

    Работает в двух потоках:
      - main-поток: getScreenshot() (GPU→CPU, ~5мс) + put_nowait (мгновенно)
      - фоновый поток: пишет данные в stdin FFmpeg (H.264 ultrafast)
    Основной игровой цикл практически не нагружается.
    """

    def __init__(self, win, output_path: str, fps: int = 30):
        self._win = win
        self._output_path = output_path
        self.frames = 0
        self.dropped = 0

        w = win.getXSize()
        h = win.getYSize()
        self._w = w
        self._h = h
        self._stride = w * 3   # RGB24

        cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{w}x{h}",
            "-r", str(fps),
            "-i", "pipe:0",
            "-vf", "vflip",                # Panda3D даёт кадры вверх ногами (OpenGL)
            "-vcodec", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "18",
            "-preset", "ultrafast",
            "-movflags", "+faststart",
            output_path,
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._q = queue.Queue(maxsize=60)   # буфер ~2с при 30fps
        self._t = threading.Thread(target=self._worker, daemon=True)
        self._t.start()

    # ---- public API ----

    def capture(self):
        """Захватить текущий кадр. Вызывать из main-потока не чаще fps раз/сек."""
        tex = None
        try:
            tex = self._win.getScreenshot()
        except Exception:
            return
        if tex is None:
            return
        raw = bytes(tex.getRamImageAs("RGB"))
        if len(raw) != self._stride * self._h:
            return
        try:
            self._q.put_nowait(raw)
            self.frames += 1
        except queue.Full:
            self.dropped += 1

    def finish(self) -> str:
        """Дождаться кодирования и закрыть FFmpeg. Возвращает путь к файлу."""
        self._q.put(None)           # сигнал завершения воркеру
        self._t.join(timeout=120)   # ждём пока FFmpeg дожуёт
        return self._output_path

    # ---- internal ----

    def _worker(self):
        stdin = self._proc.stdin
        while True:
            data = self._q.get()
            if data is None:
                break
            try:
                stdin.write(data)
            except (BrokenPipeError, OSError):
                break
        try:
            stdin.close()
        except Exception:
            pass
        self._proc.wait()
