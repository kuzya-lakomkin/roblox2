"""Сетевой клиент в отдельном потоке.

Главный поток (Panda3D) общается через потокобезопасные очереди:
    client.send(msg)        -> поставить сообщение в очередь отправки
    client.poll()           -> список входящих сообщений (dict)
"""

import queue
import socket
import threading

from common.protocol import encode, StreamDecoder


class NetworkClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None
        self._out = queue.Queue()
        self._in = queue.Queue()
        self.connected = False
        self.error = None
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def send(self, msg: dict):
        self._out.put(msg)

    def poll(self):
        out = []
        try:
            while True:
                out.append(self._in.get_nowait())
        except queue.Empty:
            pass
        return out

    def stop(self):
        self._stop.set()
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass

    def _run(self):
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=5)
            self.sock.settimeout(0.05)
            self.connected = True
        except OSError as e:
            self.error = f"Не удалось подключиться к {self.host}:{self.port} ({e})"
            return

        decoder = StreamDecoder()
        while not self._stop.is_set():
            # отправка
            try:
                while True:
                    msg = self._out.get_nowait()
                    self.sock.sendall(encode(msg))
            except queue.Empty:
                pass
            except OSError as e:
                self.error = f"Соединение потеряно: {e}"
                break
            # приём
            try:
                data = self.sock.recv(8192)
                if not data:
                    self.error = "Сервер закрыл соединение"
                    break
                for m in decoder.feed(data):
                    self._in.put(m)
            except socket.timeout:
                continue
            except OSError as e:
                self.error = f"Соединение потеряно: {e}"
                break
        self.connected = False
