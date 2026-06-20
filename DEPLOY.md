# SWAGA — Деплой на VPS

## Архитектура

```
[Клиент A]  ──┐
[Клиент B]  ──┤──► [Игровой сервер VPS-2 :50007]
[Клиент C]  ──┘         │
                         │ HTTP POST (validate/stats)
                         ▼
               [Auth-сервер VPS-1 :50008]
                         │
                    [swaga_auth.db]  ← SQLite (ники, хэши паролей, статистика)
```

- **Auth-сервер** — единственный, глобальный. Хранит аккаунты.
- **Игровых серверов** — сколько угодно. Каждый проверяет токены через auth-сервер.
- Игрок не теряет прогресс при смене игрового сервера.

---

## 1. Требования к VPS

| Параметр | Минимум |
|---|---|
| ОС | Ubuntu 22.04 LTS |
| RAM | 1 GB |
| CPU | 1 vCPU |
| Диск | 5 GB |
| Открытые порты | 50007 (TCP, игровой), 50008 (TCP, auth HTTP) |

---

## 2. Первоначальная настройка сервера

```bash
# Обновить систему
sudo apt update && sudo apt upgrade -y

# Установить Python 3.11
sudo apt install -y python3.11 python3.11-venv python3-pip git

# Проверить версию
python3.11 --version
```

---

## 3. Загрузить игру на VPS

**Вариант А — через Git:**
```bash
git clone https://github.com/ВАШ_РЕПО/roblox2.git /opt/swaga
```

**Вариант Б — через SCP (загрузить архив):**
```bash
# На локальной машине — упаковать (исключая ненужное):
zip -r swaga.zip . -x "*.pyc" -x "__pycache__/*" -x "*.glb" -x "swaga_auth.db"

# Загрузить на VPS:
scp swaga.zip user@ВАШ_IP:/opt/swaga.zip

# На VPS — распаковать:
sudo mkdir /opt/swaga && cd /opt
sudo unzip swaga.zip -d /opt/swaga
```

---

## 4. Установить зависимости на VPS

```bash
cd /opt/swaga

# Создать виртуальное окружение
python3.11 -m venv .venv
source .venv/bin/activate

# Зависимости auth-сервера
pip install -r requirements_server.txt

# (panda3d НЕ нужен на VPS — только сервер Python)
```

---

## 5. Настроить конфигурацию

### 5.1 Включить авторизацию

В файле `common/config.py` измените:
```python
AUTH_SERVER_URL = "http://IP_ВАШЕГО_VPS:50008"  # IP auth-сервера
AUTH_ENABLED = True                               # включить проверку токенов
```

### 5.2 Настройка для клиентов

Перед сборкой инсталлятора для друга, в `common/config.py` укажите:
```python
AUTH_SERVER_URL = "http://IP_ВАШЕГО_VPS:50008"
```
Тогда клиент будет автоматически подключаться к вашему auth-серверу.

---

## 6. Открыть порты (UFW)

```bash
sudo apt install -y ufw

# Разрешить SSH (не потеряем доступ!)
sudo ufw allow 22/tcp

# Порты игры
sudo ufw allow 50007/tcp    # игровой сервер
sudo ufw allow 50008/tcp    # auth-сервер (HTTP)

# Включить UFW
sudo ufw enable
sudo ufw status
```

---

## 7. Создать systemd-сервисы (автозапуск)

### Auth-сервер

```bash
sudo nano /etc/systemd/system/swaga-auth.service
```

```ini
[Unit]
Description=SWAGA Auth Server
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/swaga
Environment=PATH=/opt/swaga/.venv/bin
ExecStart=/opt/swaga/.venv/bin/python -m auth_server.server
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Игровой сервер

```bash
sudo nano /etc/systemd/system/swaga-game.service
```

```ini
[Unit]
Description=SWAGA Game Server
After=network.target swaga-auth.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/swaga
Environment=PATH=/opt/swaga/.venv/bin
ExecStart=/opt/swaga/.venv/bin/python -m server.server
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Активировать сервисы

```bash
sudo chown -R www-data:www-data /opt/swaga
sudo systemctl daemon-reload
sudo systemctl enable swaga-auth swaga-game
sudo systemctl start  swaga-auth swaga-game

# Проверить статус:
sudo systemctl status swaga-auth
sudo systemctl status swaga-game

# Логи в реальном времени:
sudo journalctl -u swaga-auth -f
sudo journalctl -u swaga-game -f
```

---

## 8. Проверить что всё работает

```bash
# Проверить что порты слушают:
sudo ss -tlnp | grep -E '50007|50008'

# Проверить auth-сервер (должен вернуть {"ok":false}):
curl -s -X POST http://localhost:50008/validate \
     -H "Content-Type: application/json" \
     -d '{"token":"test"}' | python3 -m json.tool

# Создать тестовый аккаунт:
curl -s -X POST http://localhost:50008/register \
     -H "Content-Type: application/json" \
     -d '{"login":"test","nick":"Тест","password":"123456"}' | python3 -m json.tool
```

---

## 9. Раздать клиенту

1. В `common/config.py` укажите IP auth-сервера:
   ```python
   AUTH_SERVER_URL = "http://IP_AUTH_VPS:50008"
   AUTH_ENABLED = True
   ```

2. Запустите `install.bat` на своём компьютере — убедитесь что всё работает.

3. Упакуйте всю папку игры в ZIP и передайте другу (или выложите на файлообменник).

4. Друг распаковывает архив и запускает `install.bat`.

5. При первом запуске игры появится экран **Регистрации/Входа**:
   - Auth-сервер: `IP_AUTH_VPS:50008` (уже вписан из config.py)
   - Создаёт аккаунт → входит → вводит IP **игрового** сервера в главном меню

---

## 10. Быстрая шпаргалка (после первоначальной настройки)

| Действие | Команда |
|---|---|
| Посмотреть логи игры | `journalctl -u swaga-game -f` |
| Перезапустить игровой сервер | `systemctl restart swaga-game` |
| Перезапустить auth-сервер | `systemctl restart swaga-auth` |
| Обновить игру | `cd /opt/swaga && git pull && systemctl restart swaga-game` |
| Открыть БД вручную | `sqlite3 /opt/swaga/swaga_auth.db` |
| Посмотреть всех игроков | `sqlite3 swaga_auth.db "SELECT login,nick,kills,max_wave FROM users;"` |

---

## Безопасность (минимум)

- Не открывайте порт 50008 (auth) в публичный интернет без нужды — доступ нужен только клиентам для логина, игровому серверу для валидации.  
  Если хотите — добавьте базовую аутентификацию между игровым сервером и auth-сервером (добавьте `AUTH_INTERNAL_KEY` в config.py).
- Делайте бэкап `swaga_auth.db` периодически: `cp swaga_auth.db swaga_auth.db.bak`
- В auth/server.py включен режим `debug=False` — не меняйте на `True` в продакшне.
