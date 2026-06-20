"""Протокол обмена сообщениями.

Формат: каждое сообщение — это одна строка JSON, оканчивающаяся '\n'.
Поверх TCP. Поле "t" задаёт тип сообщения.

Клиент -> сервер:
    join   {"t":"join","name": str}
    state  {"t":"state","pos":[x,y,z],"h":heading,"p":pitch}
    chat   {"t":"chat","msg": str}
    shoot  {"t":"shoot","pos":[x,y,z],"dir":[x,y,z]}   # секретная жидкость
    emote  {"t":"emote","emote": str, "pet": str|None}

Сервер -> клиент:
    welcome  {"t":"welcome","id":int,"world":{...}}
    snapshot {"t":"snapshot","players":{id:{...}},"ants":[...],"shots":[...]}
    chat     {"t":"chat","name":str,"msg":str}
    event    {"t":"event","kind":str, ...}
"""

import json


def encode(msg: dict) -> bytes:
    """dict -> байты строки JSON с переводом строки."""
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")


class StreamDecoder:
    """Накапливает байты из сокета и отдаёт цельные сообщения по '\n'."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes):
        """Добавить полученные байты, вернуть список разобранных dict-сообщений."""
        self._buf.extend(data)
        out = []
        while True:
            idx = self._buf.find(b"\n")
            if idx == -1:
                break
            line = self._buf[:idx]
            del self._buf[: idx + 1]
            if not line.strip():
                continue
            try:
                out.append(json.loads(line.decode("utf-8")))
            except (ValueError, UnicodeDecodeError):
                continue  # битый кадр игнорируем
        return out
