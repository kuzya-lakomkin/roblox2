"""Auth-сервер SWAGA — отдельный HTTP-сервер на Flask.

Запуск:  python -m auth_server.server
         или:  python auth_server/server.py

Порт: 50008 (настраивается через AUTH_PORT в common/config.py)
БД:   swaga_auth.db  (SQLite, создаётся автоматически рядом с этим файлом)
"""

import hashlib
import os
import re
import secrets
import sqlite3
import time

try:
    from flask import Flask, jsonify, request
except ImportError:
    raise SystemExit(
        "Нужен Flask: pip install flask\n"
        "Или: pip install -r requirements_server.txt"
    )

# ── Путь к базе данных (рядом со скриптом) ─────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_HERE, "..", "swaga_auth.db")

TOKEN_TTL = 7 * 86400   # 7 дней

# ── Работа с БД ────────────────────────────────────────────────────────────

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _init_db():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            login         TEXT    UNIQUE NOT NULL,
            nick          TEXT    NOT NULL,
            password_hash TEXT    NOT NULL,
            salt          TEXT    NOT NULL,
            resources     INTEGER DEFAULT 0,
            kills         INTEGER DEFAULT 0,
            max_wave      INTEGER DEFAULT 0,
            created_at    REAL    DEFAULT 0
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS tokens (
            token      TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            expires_at REAL    NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 100_000
    ).hex()


def _new_token(user_id: int) -> str:
    tok = secrets.token_urlsafe(32)
    exp = time.time() + TOKEN_TTL
    with _conn() as c:
        c.execute("DELETE FROM tokens WHERE user_id=?", (user_id,))
        c.execute("INSERT INTO tokens VALUES (?,?,?)", (tok, user_id, exp))
    return tok


def _get_user_by_token(token: str):
    with _conn() as c:
        row = c.execute(
            """SELECT u.* FROM tokens t
               JOIN users u ON t.user_id = u.id
               WHERE t.token=? AND t.expires_at>?""",
            (token, time.time()),
        ).fetchone()
    return dict(row) if row else None


# ── Валидация ввода ─────────────────────────────────────────────────────────

def _valid_login(s):
    return bool(s and re.fullmatch(r"[A-Za-z0-9_]{3,20}", s))


def _valid_nick(s):
    return bool(s and 2 <= len(s.strip()) <= 20)


def _valid_pass(s):
    return bool(s and len(s) >= 6)


# ── Flask-приложение ────────────────────────────────────────────────────────

app = Flask(__name__)


@app.post("/register")
def register():
    d = request.get_json(silent=True) or {}
    login = (d.get("login") or "").strip()
    nick  = (d.get("nick")  or "").strip()
    pw    = d.get("password", "")

    if not _valid_login(login):
        return jsonify(ok=False, error="Логин: 3-20 символов, только A-Z a-z 0-9 _")
    if not _valid_nick(nick):
        return jsonify(ok=False, error="Ник: 2-20 символов")
    if not _valid_pass(pw):
        return jsonify(ok=False, error="Пароль: минимум 6 символов")

    salt = secrets.token_hex(16)
    pw_hash = _hash(pw, salt)
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO users (login,nick,password_hash,salt,created_at) VALUES (?,?,?,?,?)",
                (login, nick, pw_hash, salt, time.time()),
            )
        return jsonify(ok=True)
    except sqlite3.IntegrityError:
        return jsonify(ok=False, error="Логин уже занят")


@app.post("/login")
def login():
    d = request.get_json(silent=True) or {}
    login_str = (d.get("login") or "").strip()
    pw        = d.get("password", "")

    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE login=?", (login_str,)).fetchone()
    if not row:
        return jsonify(ok=False, error="Пользователь не найден")
    row = dict(row)
    if _hash(pw, row["salt"]) != row["password_hash"]:
        return jsonify(ok=False, error="Неверный пароль")

    token = _new_token(row["id"])
    return jsonify(
        ok=True, token=token,
        nick=row["nick"], kills=row["kills"],
        max_wave=row["max_wave"], resources=row["resources"],
        user_id=row["id"],
    )


@app.post("/validate")
def validate():
    """Вызывается игровым сервером при подключении игрока."""
    d = request.get_json(silent=True) or {}
    user = _get_user_by_token(d.get("token", ""))
    if not user:
        return jsonify(ok=False)
    return jsonify(
        ok=True, nick=user["nick"], kills=user["kills"],
        max_wave=user["max_wave"], resources=user["resources"],
        user_id=user["id"],
    )


@app.post("/stats")
def stats():
    """Вызывается игровым сервером при отключении игрока."""
    d = request.get_json(silent=True) or {}
    uid          = d.get("user_id", 0)
    kills_delta  = int(d.get("kills_delta", 0))
    max_wave     = d.get("max_wave")           # None если не передано
    res_delta    = int(d.get("resources_delta", 0))

    if not uid:
        return jsonify(ok=False, error="no user_id")
    with _conn() as c:
        if kills_delta:
            c.execute("UPDATE users SET kills=kills+? WHERE id=?", (kills_delta, uid))
        if max_wave is not None:
            c.execute("UPDATE users SET max_wave=MAX(max_wave,?) WHERE id=?", (max_wave, uid))
        if res_delta:
            c.execute("UPDATE users SET resources=MAX(0,resources+?) WHERE id=?", (res_delta, uid))
    return jsonify(ok=True)


# ── Точка входа ────────────────────────────────────────────────────────────

def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    try:
        from common import config as C
        port = getattr(C, "AUTH_PORT", 50008)
    except Exception:
        port = 50008

    _init_db()
    print(f"=== SWAGA Auth-сервер на порту {port} ===")
    print(f"    БД: {os.path.abspath(DB_PATH)}")
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
