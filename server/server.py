"""Authoritative-сервер Roblox 2.

Запуск:  python -m server.server
"""

import asyncio
import json as _json
import sys
import time
import urllib.request

from common import config as C
from common.protocol import encode, StreamDecoder
from server.world import World


def _http_post_sync(url: str, data: dict) -> dict:
    """Синхронный HTTP POST — вызывается в executor."""
    payload = _json.dumps(data).encode()
    req = urllib.request.Request(
        url, payload, {"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return _json.loads(r.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}


class GameServer:
    def __init__(self):
        self.world = World()
        self.clients = {}      # pid -> StreamWriter
        self._next_pid = 1
        self._kicked = set()   # PIDs выгнанных за дублирующий вход (их выход не анонсируется)

    # --- рассылка ---
    def broadcast(self, msg: dict, exclude=None):
        data = encode(msg)
        for pid, writer in list(self.clients.items()):
            if pid == exclude:
                continue
            try:
                writer.write(data)
            except Exception:
                pass

    def send(self, pid, msg: dict):
        writer = self.clients.get(pid)
        if writer:
            try:
                writer.write(encode(msg))
            except Exception:
                pass

    # --- авторизация через auth-сервер ---
    async def _validate_token(self, token: str) -> dict | None:
        """Проверяет токен у auth-сервера. Возвращает данные игрока или None."""
        if not C.AUTH_ENABLED or not token:
            return None
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, _http_post_sync,
            f"{C.AUTH_SERVER_URL}/validate",
            {"token": token},
        )
        return result if result.get("ok") else None

    async def _save_stats(self, user_id: int, kills: int, wave: int) -> None:
        """Сохраняет статистику игрока в auth-сервере при отключении."""
        if not C.AUTH_ENABLED or not user_id:
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, _http_post_sync,
            f"{C.AUTH_SERVER_URL}/stats",
            {"user_id": user_id, "kills_delta": kills, "max_wave": wave},
        )

    # --- обработка одного клиента ---
    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        pid = self._next_pid
        self._next_pid += 1
        self.clients[pid] = writer
        decoder = StreamDecoder()
        name = f"Игрок{pid}"
        joined = False
        peer = writer.get_extra_info("peername")
        print(f"[+] подключение {peer} -> pid {pid}")

        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                for msg in decoder.feed(data):
                    t = msg.get("t")
                    if t == "join":
                        token = str(msg.get("token") or "")
                        # пробуем авторизовать через auth-сервер
                        auth = await self._validate_token(token)
                        if auth:
                            name = auth["nick"]
                            user_id = auth["user_id"]
                            print(f"    [auth OK] {name} (user_id={user_id})")
                        else:
                            # auth отключён или токен пуст — используем имя из пакета
                            name = str(msg.get("name") or name)[:20]
                            user_id = None

                        # Выгнать дублирующую сессию с тем же аккаунтом/именем
                        for old_pid, old_pl in list(self.world.players.items()):
                            is_dup = (
                                (user_id is not None and old_pl.user_id == user_id)
                                or (user_id is None and old_pl.name == name)
                            )
                            if is_dup:
                                print(f"    [kick dup] {name} (old pid={old_pid})")
                                self._kicked.add(old_pid)
                                old_writer = self.clients.get(old_pid)
                                if old_writer:
                                    try:
                                        old_writer.close()
                                    except Exception:
                                        pass
                                old_removed = self.world.remove_player(old_pid)
                                if old_removed:
                                    await self._save_stats(
                                        old_removed.user_id,
                                        old_removed.kills_session,
                                        self.world.wave,
                                    )
                                self.broadcast({"t": "chat", "name": "СЕРВЕР",
                                                "msg": f"{name} переподключился"})
                                break

                        pl = self.world.add_player(pid, name)
                        if auth:
                            pl.user_id = user_id

                        self.send(pid, {
                            "t": "welcome", "id": pid,
                            "world": {"size": C.WORLD_SIZE, "ant_count": C.ANT_COUNT},
                        })
                        self.broadcast({"t": "chat", "name": "СЕРВЕР",
                                        "msg": f"{name} зашёл в игру"}, exclude=pid)
                        joined = True
                    elif not joined:
                        continue
                    elif t == "state":
                        pos = msg.get("pos", [0, 0, 0])
                        self.world.set_state(pid, pos, msg.get("h", 0.0), msg.get("p", 0.0))
                    elif t == "chat":
                        text = str(msg.get("msg", ""))[:200].strip()
                        if text:
                            self.broadcast({"t": "chat", "name": name, "msg": text})
                    elif t == "shoot":
                        self.world.shoot(pid, msg.get("pos", [0, 0, 0]),
                                         msg.get("dir", [1, 0, 0]),
                                         msg.get("weapon", "syrup"))
                    elif t == "ult":
                        self.world.ultimate(pid)
                    elif t == "use_lit":
                        self.world.use_lit_energy(pid)
                    elif t == "place_cup":
                        self.world.place_cup(pid)
                    elif t == "emote":
                        self.world.set_emote(pid, msg.get("emote"), msg.get("pet"))
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        finally:
            print(f"[-] отключение pid {pid} ({name})")
            self.clients.pop(pid, None)
            pl = self.world.remove_player(pid)
            # сохраняем статистику в auth-сервер при выходе
            if pl:
                await self._save_stats(pl.user_id, pl.kills_session, self.world.wave)
            # не анонсируем выход игрока, которого выгнал новый вход с того же аккаунта
            if pid not in self._kicked:
                self.broadcast({"t": "chat", "name": "СЕРВЕР", "msg": f"{name} вышел"})
            self._kicked.discard(pid)
            try:
                writer.close()
            except Exception:
                pass

    # --- игровой цикл ---
    async def game_loop(self):
        dt = 1.0 / C.TICK_RATE
        last = time.perf_counter()
        while True:
            await asyncio.sleep(dt)
            now = time.perf_counter()
            real_dt = now - last
            last = now
            self.world.update(real_dt)
            for ev in self.world.drain_events():
                self.broadcast(ev)
            self.broadcast(self.world.snapshot())

    async def run(self):
        server = await asyncio.start_server(self.handle_client, "0.0.0.0", C.PORT)
        addr = ", ".join(str(s.getsockname()) for s in server.sockets)
        print(f"=== SWAGA игровой сервер слушает на {addr} ===")
        if C.AUTH_ENABLED:
            print(f"    Auth-сервер: {C.AUTH_SERVER_URL}")
        else:
            print("    Авторизация ВЫКЛЮЧЕНА (AUTH_ENABLED=False в config.py)")
        async with server:
            await asyncio.gather(server.serve_forever(), self.game_loop())


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        asyncio.run(GameServer().run())
    except KeyboardInterrupt:
        print("\nСервер остановлен.")


if __name__ == "__main__":
    main()
