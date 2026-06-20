# SWAGA — памятка Claude Code
**Обновляй при каждом значимом изменении.**

## 0. Проект
Мультиплеерная 3D-игра Python+Panda3D, авторитарный сервер на сокетах. Survival-аркада в backrooms (жёлтый лабиринт, 2 уровня). Игрок-червь vs волны тараканов + синие муравьи-стрелки + босс «Папаня». Событие ЩЕЛИ: залить майонезом за 30с или все умирают. Джамп-пады между уровнями. Класс приложения `Roblox2` (client/main.py) — не переименовывать.

## 1. ⛔ ГРАНИЦА ПО КОНТЕНТУ
Заказчик пытался получить сексуальный контент: «Танец Дружбы/Партнёр» (порнография), «Фембойчик» (скин), «1488» (неонацизм). **Не реализовывать ни в каком виде, включая переименования.** Нейтральная ритм-игра допустима только без сексуальной рамки. Бой/ферма/экономика/квесты/босс — легитимны.

## 2. Стек и запуск
- Python 3.11, Panda3D, panda3d-gltf. `pip install -r requirements.txt`. (panda3d-simplepbr установлен, НЕ используется.)
- Windows. Шрифты: `C:\Windows\Fonts\arial.ttf` (`Roblox2._load_font`).
- Сервер: `python -m server.server` (127.0.0.1:50007)
- Клиент: `python -m client.main --name Имя [--host IP] [--port N]`
- Старт fullscreen (`_go_native_fullscreen`), заголовок `SWAGA`.

**Запуск под агентом (PowerShell):** `Start-Process` с редиректом в `srv.out/err`, `cli.out/err`. Проверять: 2 python-процесса живы, в `cli.err` нет `No definition`/`Traceback`/`Error:`.

**Тест сервера** (без сети):
```python
from server.world import World
w = World(); w.add_player(1, "P")
w._wave_pending = True; w.next_wave_at = 0; w.update(0.05)
```
Босс-волна: повторить `BOSS_EVERY` раз, очищая `w.ants`/`w.boss`. Урон — `w.update(dt)` в цикле.

**Тест клиента** (offscreen):
```python
from panda3d.core import loadPrcFileData
loadPrcFileData("", "window-type offscreen")
loadPrcFileData("", "audio-library-name null")
import client.main as m
app = m.Roblox2("T", "127.0.0.1", 50007)
app.start_combat()
for _ in range(120): app.taskMgr.step()
```
Снапшоты по реальным часам — `time.sleep` 1.5–4.5с между `step`. Камера/мышь/fullscreen/bloom защищены guard'ами (offscreen ≠ окно).
Звук — мок с `play/stop/setVolume/setPlayRate/setLoop/length/status`.

**Gotchas:**
- Panda3D дефолт без кириллицы → всегда `setFont`. Тире `—` (U+2014) может отсутствовать → `-`.
- `NodePath` не принимает произвольные атрибуты → хранить в dict'ах.
- `loadMusic` тихо стримит WAV → музыку через `loadSfx`; `length()<=0` → битый (None).
- 3D-таблички: `setCardDecal(True)` + `setDepthOffset(1)` + `setLightOff(1)` (z-fight).
- Z-fight карниза стен: карниз `_build_wall_block` поднят выше тела (верх > `WALL_HEIGHT`).

## 3. Файлы
```
common/
  config.py    (~81)    все константы/баланс
  protocol.py  (~50)    построчный JSON TCP: encode(dict)->bytes, StreamDecoder().feed()->[dict]
  citydata.py  (~220)   арена (ARENA=56): WALL_BLOCKS (_RING+_OUTER+_PLAZA, симметрия×4),
                        BOSS_SPAWN, building_rects/in_any_building/resolve_collision (высото-завис),
                        near_wall; PLATFORMS/LEVEL2_Z/support_z/platform_top_at, JUMP_PADS/on_jump_pad,
                        slit_spawn_points, line_blocked (LOS), CUP_SPOTS
server/
  server.py    (~131)   asyncio TCP, TICK_RATE=30, парсинг/рассылка
  world.py     (~900)   симуляция: Player, Ant, NeonAnt, AntShot, Boss, BossShot, Shot, Bee, Slit, World
  navgrid.py   (~120)   NavGrid: BFS flow-поле от игроков, cell=2.0, random_free_point()
client/
  main.py      (~1280)  Roblox2: состояния, ввод, камера 1/3 лицо, рендер снапшотов, HUD, звук,
                        частицы, bloom, fullscreen; RemoteAvatar, WorldBar
  network.py   (~83)    NetworkClient в отдельном потоке; send()/poll()
  citymap.py   (~280)   build_city: ковролин/стены/лампы/платформы/джамп-пады + витрина SWAGA + босс-пад
                        Палитра: CARPET/WALLPAPER/LIGHT_PANEL/JUMP_PAD
  procgen.py   (~340)   make_sphere/make_uv_sphere/make_cylinder/make_truncated_cone;
                        make_cockroach/make_neon_ant/make_bee/make_boss/make_slit/make_cup (+WormModel в main)
  primitives.py (~55)   make_box: куб с нормалями + UV-тайлинг, two-sided
  particles.py (~70)    ParticleSystem: кубики (гравитация, разлёт, alpha-фейд), лимит 320
  ui.py        (~235)   Screen, MainMenu, PauseMenu, SettingsMenu, InfoScreen; скруглённые кнопки (_BTN_TEX)
  assets.py    (~176)   load_texture/sound/music/font/model с fallback (нет файла → заглушка/None)
  asset_config.py(~103) КОНСТАНТА→ПУТЬ всех ассетов
assets/textures/ sounds/ fonts/   papich/ (arthas-папич.glb ~8МБ + текстуры)
```

## 4. Сетевой протокол
Один пакет = JSON строка + `\n`. Поле `t` = тип.

**Клиент→сервер:** `join {name}`, `state {pos,h,p}` (~20Гц), `chat {msg}`, `shoot {pos,dir,weapon}` (weapon: syrup/mayo/hive; hive только в BEE_WINDOW), `ult`, `use_lit`, `place_cup`, `emote {emote,pet}`

**Сервер→клиент:** `welcome {id,world}`, `snapshot` (30Гц), `chat {name,msg}`, `event {kind,...}`

**Снапшот:**
- `players {pid: {name,pos,h,p,hp,score,deaths,emote,pet,dead,lit,bees,slow,cups}}`
- `ants [[aid,x,y,z]]` (z>0 = лезет по стене)
- `neon_ants [[nid,x,y,h]]`, `ant_shots [[asid,x,y,z]]`
- `shots [[sid,x,y,z,kind]]` (0=сироп, 1=майо)
- `bees [[bid,x,y,z]]`, `drops [[did,x,y,kind]]` (honey/syrup/mayo/lit_energy)
- `bshots [[bsid,x,y,z]]`, `boss {pos,h,respect,max,phase}|null`
- `slits [[sid,x,y,z,h,frac,calmed]]`, `slit_time`
- `wave`, `alive`, `neon`, `cup_spots [bool×4]`, `black_king`

**События:** `splash`, `death`, `ant_killed {pos,by}`, `pickup {drop,by}`, `wave {wave,count}`, `boss_spawn`, `boss_defeated {by}`, `boss_throw {pos}`, `boss_explode {pos}`, `ultimate {by}`, `neon_wave`, `neon_shoot {pos}`, `neon_ant_killed {pos,by}`, `skibidi_hit {pos}`, `slit_spawn {count,time}`, `slit_calmed {pos}`, `slit_defeated`, `slit_failed`, `lit_used {by,time}` (клиент → SFX_LIT_ENERGY), `boss_gas {pos,radius}`, `cup_placed {spot,count}`, `black_king_spawn`, `wipe`

Сервер авторитетен. Снаряды гасятся о стены (`_hits_wall`). NeonAnt/Boss не стреляют без LOS.

## 5. Состояния клиента (client/main.py)
`state ∈ {HUB, COMBAT, PAUSE, SETTINGS, FARM, SHOP}`

- Карта строится в `__init__` (`_build_world_scene`, флаг `world_scene_built`) — фон меню.
- Игровое состояние (`_build_game`, флаг `world_built`) — лениво при первом входе в бой.
- Подключение: `_connect()` из `start_combat()`, `_disconnect()` из `goto_hub()`. Живёт только в бою.
- Игровой цикл `update()`: пока `world_built and net` (т.е. и в PAUSE). `controllable=(state=="COMBAT")` гейтит только ввод. Без сети: `_update_menu_background`.
- **HUB**: MainMenu, MUSIC_HUB, камера облетает карту, `_set_menu_blur(True)`.
- **COMBAT**: `start_combat()` → connect → снять blur → 1-е лицо → MUSIC_PHASE1 (MUSIC_BOSS если босс).
- **PAUSE**: мир живёт, blur включён, PauseMenu прозрачное.
- **FARM/SHOP**: InfoScreen-заглушки.
- `goto_hub()`: стоп звуки/струя → disconnect → clear entities → hub музыка/blur.

## 6. Геймплей

**Управление:** WASD — ходьба, Пробел — прыжок, мышь — обзор, ЛКМ (зажать) — стрелять, 1/2/3 — оружие, Shift — газ, Q — ульт, C — камера, F/G/V — эмоции, Enter — чат, Esc — пауза, Alt+Enter — fullscreen, Ctrl+Z — свернуть, R — поставить стакан. Джамп-пад → автоподброс.

**Камера:** FOV 85°. Дефолт: 1-е лицо. C → 3-е (орбита, dist=11, elev=pitch+16 макс 75°). Тангаж −60..80.

**Волны:** START=10, GROWTH=5/волну, потолок COUNT=45, DELAY=4с. Каждая BOSS_EVERY=3-я → спавн босса. Следующая волна: нет живых ants+boss.

**NavGrid** (server/navgrid.py): cell=2.0, стены непроходимы. Каждый тик: multi-source BFS от всех живых игроков → flow-поле. `direction(x,y)` → вектор к ближайшему игроку (без срезания диагоналей). `random_free_point()` → спавн только на поверхности.

**Тараканы (Ant):** CHASE_RANGE=48, умный путь NavGrid, `_step_ground` (скольжение, не входят в стены). Окружение: вблизи (<SURROUND_RADIUS+3) занимают сектор кольца (угол по φ от aid), SURROUND_RADIUS=1.5. На платформе (z>2) — прямо к игроку без коллизий стен. SPEED=5.2, замедляются майо. TOUCH_RANGE=1.8, TOUCH_DAMAGE=24, TOUCH_CD=0.6с (общий для всех врагов, `Player.touch_inv_until`). Гибнут с 1 попадания сиропа/пчелы.
Лезут по стене (`Ant._update_height`): только при `near_wall` (1.3 от WALL_BLOCK) и `platform_top_at>0`. CLIMB_SPEED=8. Спрыгивают гравитацией. z в снапшоте, касание 3D (`_dist2`).

**NeonAnt** (после волны 3): FROM_WAVE=4, BASE=2+GROWTH=1/волну, MAX=12. Кайтинг: PREFERRED_RANGE=14 (отступают/подходят/стрейфят), лицом к игроку. Не стреляют без LOS (`line_blocked`). SHOOT_INTERVAL=2.2с, AntShot: лёгкая дуга, SKIBIDI_DAMAGE=12, SKIBIDI_RADIUS=0.5. HP=3, майо замедляет, пчёлы бьют. +3 очка + шанс дропа. Full-bright синий + синий трейл зелья. Клиент: `make_neon_ant`, узлы `neon_ant_nodes/ant_shot_nodes`.

**ЩЕЛЬ (Slit):** Событие раз в SLIT_INTERVAL=(35..60)с. Спавн: 1 щель на игрока (макс = число точек). Точки: `slit_spawn_points()`, внутри кольцевых стен, z=PLAYER_HEIGHT×0.5, eps=0.8 перед стеной. Модель: `make_slit` — 2 uv-сферы (SLIT_TEXTURE) + чёрная точка между ними.
Механика: `progress` 0..1, наполняется MAYO (+SLIT_MAYO_GAIN=0.015/капля, HIT_RADIUS=1.3, снаряд гасится). Все повержены → `slit_defeated`. Не успели за 30с → `slit_failed` (все умирают).
Тараканы во время щели (`_update_slit_laugh`): мчатся (SLIT_SPEED=13) и встают по кольцу вокруг игрока (SLIT_RADIUS=6.5, угол по φ от aid), прыгают (SLIT_JUMP), НЕ кусают. После победы → `_scatter_ants` (SCATTER_DIST=30+подброс). Клиент: смех `SFX_COCKROACH_LAUGH` через `AudioSound.status()` (не луп).
WorldBar над щелью: billboard, вынесен forward×1.4 от стены, выше на 2.2.
Музыка: MUSIC_SLIT (первые 20с), MUSIC_SLIT_FINAL (последние 10с). Звуки: SFX_SLIT_SPAWN / SFX_SLIT_CALM (только если предыдущий доиграл, по `status()`) / SFX_SLIT_DEFEATED + вспышка `_flash_screen` + тряска `_shake` + частицы.

**Оружие** (ЛКМ зажать = струя):
- **1 Сироп** (syrup): DAMAGE=5/капля, убивает ants, копит уважение боссу. SPRAY_COOLDOWN=0.05.
- **2 Майонез** (mayo): не бьёт, замедляет в MAYO_SLOW_RADIUS=5 (фактор 0.35, 2.5с).
- **3 Улей** (hive): залп HIVE_BEES=3 самонаводящихся пчёл, HIVE_COOLDOWN=0.45. Только в BEE_WINDOW=12с после `use_lit`. Кл. 3: окно → выбрать; иначе lit>0 → `use_lit`; иначе → подсказка. Авто-возврат на сироп по истечении. Сервер гейтит по `Player.bee_until`.

**Способности:**
- Shift ГАЗЗЗЗ: ×GAS_MULT=2, GAS_DURATION=3с (клиент).
- Q ульт: заморозка ants+boss, ULT_DURATION=5с, ULT_COOLDOWN=20с (`World.freeze_until`).

**Босс Папаня (Boss):** Без HP — шкала Уважения (RESPECT_MAX=600, RESPECT_PER_HIT=2, только сироп). Повержен → +20 всем, `boss_defeated`. WorldBar над головой.
Спавн: BOSS_SPAWN=(0,46). Движение: NavGrid, BOSS_SPEED=2.4, `Boss.h` (heading к игроку), клиент +BOSS_MODEL_YAW=180.
Фазы: phase=1 (THROW_INTERVAL=3.0) → phase=2 при PHASE2_FRAC=0.5 (THROW_INTERVAL_P2=1.5 + газ GAS_INTERVAL=1с, GAS_RADIUS=13, замедление SLOW_FACTOR=0.5 на SLOW_TIME=1.6с).
Атака: BossShot, SPEED=26. Упреждение по Player.vel (5 итераций) + точная баллистика `vz=(-z0-0.5·g·t²)/t`. LOS перед броском. Детонация → AoE EXPLOSION_DAMAGE=45 + KNOCKBACK=28 (сервер мобам, клиент игроку `_apply_blast_knockback`).

**Дроп:** DROP_CHANCE=0.20, PICKUP_RADIUS=2.2. Типы: honey/syrup/mayo/lit_energy (lit_energy → `Player.lit_energy`, НЕ ресурс). Модели `AC.DROP_MODELS` (`*.glb`, нормализация ~1.2), нет файла → кубик.

**Стаканы и BLACK KING (призыв):** Босс роняет `make_cup` (усечённый конус). R → `place_cup` → ближайший CUP_SPOT (CUP_SPOT_RADIUS=3). Все 4 заняты → создаётся `BlackKing`, `black_king_spawn`. Снапшот: `cup_spots [bool×4]`, `black_king`, `bk_boss {pos,h,hp,max_hp}|null`, `bk_minions [[mid,x,y,z]]`.

**BLACK KING (финальная фаза):** Класс `BlackKing` / `BlackKingMinion` в `server/world.py`.
- Поведение: постоянная быстрая беготня по всей карте (SPEED=11, смена цели каждые 1.5-3.5с, `_random_point()`). Не использует NavGrid — просто бежит к случайной точке со скольжением вдоль стен.
- HP=1200, наносится сиропом (PROJECTILE_DAMAGE=5/капля). Повержен → `bk_defeated` (+50 всем, сброс cup_spots/black_king).
- Спавн копий каждые 8с (по 2, max 12): `BlackKingMinion` рядом с боссом. Копии прыгают к игроку каждые 0.5с (HOP_VZ=7, HOP_SPEED=4.5), гибнут с 1 сиропа (+2 очка).
- Случайные звуки: событие `bk_voice` → клиент играет случайный из `SFX_BLACK_KING_VOICES`.
- Урон: BLACK KING TOUCH=30, копия TOUCH=15 (общий i-frame кулдаун `touch_inv_until`).
- Клиент: модель `assets/models/black_king.glb` (если нет → тёмный таракан full-bright фиолетовый), миньоны — уменьшенная та же модель / `make_bk_minion`. `_bk_boss_node`, `bk_boss_bar` (WorldBar фиолетовый), `bk_minion_nodes`. Музыка: MUSIC_BLACK_KING (приоритет над ЩЕЛЬЮ). Звуки: SFX_BLACK_KING_SPAWN/HIT/DEATH/VOICES.
- Вайп: bk_minions чистятся, bk_boss НЕ чистится (фаза продолжается через смерть команды).
- Admin: ник `GODBLESSER` → сразу `p.cups=4` при входе.

**Смерть и вайп:** HP≤0 → dead, 3с → респаун на спавне (южная яма). Урон клиентом (падение hp) → SFX_PLAYER_HURT (антиспам 0.5с). Все мертвы → `_check_wipe`: чистка ants/neon/boss/slits/снаряды, wave=0, событие `wipe`.

**HUD:** HP низ-лево (цвет от запаса) + чат; очки/смерти верх-лево; онлайн верх-право; оружие+LIT ENERGY[3]+таймер пчёл+стаканы[R] низ-право; волна/фаза/BLACK KING верх-центр + предупреждение ЩЕЛИ с отсчётом; прицел центр. Экранэффекты: `death_overlay` (затемнение+текст), `vignette` (зелёный при газе папани) — оба render2d, лерп-альфа (`_update_overlays`).

## 7. Графика

**Процедурные модели:** make_sphere/make_uv_sphere/make_cylinder/make_box. Таракан: 3 сферы+6 ног+усики. Пчела. Fallback-босс: таракан×3+корона. ЩЕЛЬ: 2 uv-сферы+чёрная точка. make_cup. `make_worm` устарел.

**WormModel** (client/main.py): 9 сфер дуга хвост→голова с глазами. Анимации: дыхание / бегущая волна+бобинг / прыжок-вытяг / эмоции flex/dance/wave. Иерархия: root→anim→сегменты; глаза дети головы. Один риг: RemoteAvatar + локальный. В 1-м лице: голова+шея скрыты (`set_first_person`).

**Модель босса** (`_make_boss_node`): `papich/arthas-папич.glb` (14 текстур), panda3d-gltf, высота 6 ед., `setTwoSided(True)` + принуд. непрозрачно. **Работает с КОПИЕЙ** (`model.copyTo`+`clearTransform`) — иначе 2-е появление «усыхает» (мерим уже отмасштабированные границы). `papich/Image_*@channels=*` — карты каналов, НЕ модели.

**Карта** (citymap.build_city): 2 уровня, симметрия×4. Центр: яма (спавн+витрина). Кольцо стен WALL_HEIGHT=11, R=30, 4 проёма (N/S/E/W). Снаружи: коридор+колонны+арена босса. Уровень 2 (LEVEL2_Z=12): дорожка-кольцо+4 угловых бастиона (PLATFORMS). `flattenStrong()`.
Текстуры: пол=BACKROOMS_FLOOR_TEXTURE, стены=BACKROOMS_WALL_TEXTURE, тайлинг UV из мировых координат × uv_scale, WM_repeat, мипмапы+анизотропия×8.
`resolve_collision` высото-зависимый: не толкает если `z>=WALL_HEIGHT-0.1` (по дорожке ходить свободно).
Пады: JUMP_PAD_RADIUS=2, `on_jump_pad(x,y)`, BOOST=27 (вертикально). `support_z(x,y,z_feet)` только при `vz<=0`.
Витрина: `build_spawn_pillar` — параллелепипед, 4 боковых картинки (SHOWCASE_TEXTURES, fallback litvin), нео-рёбра, SWAGA-билборд.

**Рендеринг:**
- MSAA: `framebuffer-multisample 1`, `multisamples 4`, `setAntialias(MMultisample)`.
- Bloom: `CommonFilters.setBloom(mintrigger=0.55)`, try/except (offscreen → `self.filters=None`).
- Blur меню: тот же CommonFilters `setBlurSharpen` (`_set_menu_blur`).
- Свечение: `setLightOff(1)` (full-bright) + bloom.
- Освещение: тёплый ambient + отвесный от потолка (`_setup_lights`).
- WorldBar: billboard-полоса (рамка+make_box заполнение в X-Z+TextNode), scale-X растёт слева, `setDepthOffset` от z-fight. Для босса и ЩЕЛИ.
- Камера-коллизий НЕТ (TODO).

## 8. UI (client/ui.py)
- `Screen`: PANEL alpha~0.16, BG~0.10, кнопки~0.78 (прозрачно → видно карту).
- `_button_texture(corners)` (кэш `_BTN_TEX`): вертикальный градиент (светлее↑), скругление по нужным углам (top/bottom/mid/all).
- Анимации: hover ×1.07, press ×0.95 (`LerpScaleInterval`+`LerpColorScaleInterval`, биндинги DGG.WITHIN/WITHOUT/B1PRESS/B1RELEASE).
- Заголовок: фейк-блюр тень (несколько полупрозрачных копий со смещениями).
- `MainMenu`: «SWAGA / уровень 0 - бэкрумы», ник + 5 кнопок (`_button_stack`).
- `PauseMenu`: `_button_stack`, прозрачный.

## 9. Аудио
Деградирует молча. Музыка: фикс. громкость 0.5. Звуки: `_vol_for_dist`/`_vol_at`.
- Струя: START→LOOP (`_start_spray_sound`, переключение по `length()`+`doMethodLater`), сироп/майо раздельно. Глохнет при отпуске/смене/паузе/смерти.
- Музыка (`_play_music`, loadSfx): HUB→MUSIC_HUB, бой→MUSIC_PHASE1, босс→MUSIC_BOSS. ЩЕЛЬ: MUSIC_SLIT (0-20с)/MUSIC_SLIT_FINAL (20-30с), потом возврат.
- Ambient-лупы (`_set_loop`): SFX_WORM_STEP (при движении по земле), SFX_COCKROACH_STEP (пока ants живы, громкость по ближайшему).
- Разовые: SFX_JOIN_PHASE1, SFX_COCKROACH_DEATH (pitch rand 0.8-1.3), SFX_PLAYER_HURT, SFX_BOSS_SPAWN/HIT/DEATH/THROW, SFX_BOSS_VOICES (rand 4-9с), SFX_PICKUP, SFX_EXPLOSION.

## 10. Ассеты (asset_config.py)
Базовые папки: `assets/{textures,sounds,fonts}`, `papich/`. Нет файла → шахматка/None.

**Текстуры** (`assets/textures/`): litvin.png, slit.png (на 2 шара ЩЕЛИ), showcase_1..4.png (fallback litvin), backrooms_floor.jpg, backrooms_wall.jpg. (COCKROACH/BOSS/BEE/PLAYER_BASE/иконки/meme_bg — ещё не наложены на модели.)

**Звуки** — есть: сиропная/майо-струи, join, cockroach_death/step, worm_step, pickup, explosion, boss_spawn/hit/death/voice_1/voice_2, music_hub/phase1/boss.
Нет: sfx_player_hurt, sfx_boss_throw, sfx_boss_voice_3, sfx_neon_ant_death, sfx_skibidi_shoot, sfx_skibidi_hit (NeonAnt пока используют cockroach_death с высоким питчем).
ЩЕЛЬ (файлов нет → тихо): sfx_slit_spawn.wav, sfx_slit_calm.wav, sfx_slit_defeated.wav, music_slit.wav, music_slit_final.wav, sfx_cockroach_laugh.wav.

**Шрифты**: title.ttf, world.otf присутствуют; остальные роли (UI/HUD/CHAT) → Arial системный. Роли: FONT_TITLE/UI/HUD/CHAT/WORLD.

**Модель босса**: `papich/arthas-папич.glb`, BOSS_MODEL_YAW=180.

**Дроп-модели** (`assets/models/*.glb`): honey_jar, green_syrup, mayo, lit_energy (нет → кубик). Стакан = procgen.make_cup. SFX_LIT_ENERGY: sfx_lit_energy.wav.

## 11. Баланс (менять только в common/config.py)
```
Сеть:       PORT=50007, TICK_RATE=30
Мир:        WORLD_SIZE=56, GRAVITY=-25, PLAYER_SPEED=8, PLAYER_JUMP=9, PLAYER_HEIGHT=1.8, MAX_HP=100
Снаряды:    SPEED=34, LIFETIME=1.4, DAMAGE=5, SPREAD=0.05, SPRAY_CD=0.05, HIVE_CD=0.45
Тараканы:   COUNT=45, SPEED=5.2, TOUCH_RANGE=1.8, TOUCH_DMG=24, TOUCH_CD=0.6, CHASE=48,
            SURROUND=1.5, CLIMB_SPEED=8, CLIMB_TRIGGER=3
            SLIT: SPEED=13, RADIUS=6.5, JUMP=8, SCATTER=30
NeonAnt:    FROM=4, BASE=2, GROW=1, MAX=12, SPEED=3.6, HP=3, PREF_RANGE=14,
            SHOOT_RANGE=28, CHASE=44, SHOOT_INT=2.2, TOUCH_DPS=14
AntShot:    SPEED=19, LIFE=3.2, RADIUS=0.5, DMG=12
ЩЕЛЬ:       TIME=30, FINAL=10, MAYO_GAIN=0.015, HIT_R=1.3, INTERVAL=(35,60)
Джамп-пад: BOOST=27, RADIUS=2
Волны:      START=10, GROW=5, DELAY=4, BOSS_EVERY=3
Босс:       RESPECT_MAX=600, PER_HIT=2, SPEED=2.4, THROW_INT=3.0/P2=1.5, PROJ_SPEED=26,
            PROJ_LIFE=4, EXPL_R=6, EXPL_DMG=45, KNOCKBACK=28, PHASE2_FRAC=0.5
            GAS: INT=1.0, R=13, SLOW_TIME=1.6, SLOW_F=0.5
Дроп:       CHANCE=0.20, PICKUP_R=2.2
            DROP_TABLE: honey/syrup/mayo/lit_energy (lit_energy НЕ ресурс → Player.lit_energy)
            Босс роняет cup; CUP_SPOTS=4, CUP_SPOT_R=3 → BLACK_KING
BLACK KING:  HP=1200, SPEED=11, WANDER=(1.5,3.5)s, VOICE_INT=(4,9)s
            MINION_SPAWN=8s, MAX=12, MINION_HP=1, MINION_SPEED=4.5,
            HOP_INT=0.5s, HOP_VZ=7, TOUCH=30, MINION_TOUCH=15
Оружие:     MAYO_SLOW_R=5, SLOW_F=0.35, SLOW_T=2.5, HIVE_BEES=3, BEE_SPEED=22, BEE_LIFE=3, BEE_WIN=12
Способности: GAS_DUR=3, GAS_MULT=2, ULT_DUR=5, ULT_CD=20
Карта:      BOSS_SPAWN=(0,46), ARENA=56, LEVEL2_Z=12
```

## 12. TODO
- Текстуры на модели (червь/таракан/пчела, сейчас vertex-color)
- Камера-коллизии в 3-м лице
- Ферма/Магазин (заглушки; `Player.resources`)
- Квесты, рейтинг, королевская битва
- Интерполяция RemoteAvatar (30 Гц, приемлемо)

---
Заказчик — не технарь (выгружал JPEG под видом .glb). Всегда проверяй валидность ассетов.
