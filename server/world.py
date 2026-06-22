"""Состояние мира и игровая симуляция (сервер). Фаза 1: Травля."""

import math
import random
import time

from common import config as C
from common.citydata import (building_rects, in_any_building, BOSS_SPAWN,
                             platform_top_at, support_z, near_wall,
                             slit_spawn_points, line_blocked, WALL_HEIGHT,
                             LEVEL2_Z, CUP_SPOTS, CUP_SPOT_RADIUS)
from server.navgrid import NavGrid

_BUILDING_RECTS = building_rects(pad=0.5)
_WALL_NEAR_RECTS = building_rects(pad=1.3)   # «впритык к стене» — для лазания тараканов
_LOS_RECTS = building_rects(pad=0.0)         # стены для проверки прямой видимости (стрельба)


def _hits_wall(pos):
    """Снаряд врезался в стену (ниже верха стен и внутри её footprint)."""
    return pos[2] <= WALL_HEIGHT and in_any_building(pos[0], pos[1], _LOS_RECTS)

_SLIT_POINTS = slit_spawn_points()

_DROP_KINDS = [k for k, _v, _w in C.DROP_TABLE]
_DROP_VALUE = {k: v for k, v, _w in C.DROP_TABLE}
_DROP_WEIGHTS = [w for _k, _v, w in C.DROP_TABLE]


def _clamp_to_arena(x, y):
    lim = C.WORLD_SIZE - 1.0
    return max(-lim, min(lim, x)), max(-lim, min(lim, y))


def _dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _nearest_player(players, pos, max_range):
    best, best_d = None, max_range * max_range
    for pl in players.values():
        if pl.hp <= 0:
            continue
        d = (pl.pos[0] - pos[0]) ** 2 + (pl.pos[1] - pos[1]) ** 2
        if d < best_d:
            best, best_d = pl, d
    return best


class Player:
    __slots__ = ("pid", "name", "pos", "h", "p", "hp", "score", "deaths",
                 "emote", "pet", "emote_until", "last_shot", "ult_ready_at",
                 "dead", "respawn_at", "resources", "vel", "_last_pos",
                 "touch_inv_until", "lit_energy", "bee_until", "move_slow_until",
                 "cups", "user_id", "kills_session")

    def __init__(self, pid, name):
        self.pid = pid
        self.name = name
        self.pos = [random.uniform(-12, 12), random.uniform(-20, -10), 0.0]
        self.h = 0.0
        self.p = 0.0
        self.hp = C.PLAYER_MAX_HP
        self.score = 0
        self.deaths = 0
        self.emote = None
        self.pet = "worm"
        self.emote_until = 0.0
        self.last_shot = 0.0
        self.ult_ready_at = 0.0
        self.dead = False
        self.respawn_at = 0.0
        self.resources = {}   # kind -> количество (для фермы/экономики)
        self.vel = [0.0, 0.0, 0.0]      # оценка скорости (для упреждения снарядов босса)
        self._last_pos = list(self.pos)
        self.touch_inv_until = 0.0      # кулдаун на урон от касаний мобов
        self.lit_energy = 0             # запас предметов LIT ENERGY (не ресурс)
        self.bee_until = 0.0            # до какого момента доступны пчёлы (после LIT ENERGY)
        self.move_slow_until = 0.0      # замедление от газа босса (клиент применяет к скорости)
        self.cups = 0                   # белые стаканы (дроп с босса) в руках
        self.user_id = 0               # ID в auth-сервере (0 = не авторизован)
        self.kills_session = 0         # убийств за сессию (отправляется в auth при выходе)

    def snapshot(self):
        now = time.time()
        return {
            "name": self.name, "pos": [round(v, 3) for v in self.pos],
            "h": round(self.h, 1), "p": round(self.p, 1),
            "hp": int(self.hp), "score": self.score, "deaths": self.deaths,
            "emote": self.emote, "pet": self.pet, "dead": self.dead,
            "lit": self.lit_energy,
            "bees": round(max(0.0, self.bee_until - now), 1),
            "slow": round(max(0.0, self.move_slow_until - now), 2),
            "cups": self.cups,
        }


class Ant:
    __slots__ = ("aid", "pos", "dir", "slow_until", "vz")

    def __init__(self, aid, pos=None):
        self.aid = aid
        self.slow_until = 0.0
        self.vz = 0.0
        if pos is None:
            pos = self._fallback_pos()
        self.pos = [pos[0], pos[1], 0.0]   # спавн только на поверхности (не в стенах)
        ang = random.uniform(0, 2 * math.pi)
        self.dir = [math.cos(ang), math.sin(ang)]

    @staticmethod
    def _fallback_pos():
        for _ in range(40):
            x = random.uniform(-C.WORLD_SIZE, C.WORLD_SIZE)
            y = random.uniform(-C.WORLD_SIZE, C.WORLD_SIZE)
            if not in_any_building(x, y, _BUILDING_RECTS):
                return (x, y)
        return (0.0, -20.0)

    def update(self, dt, now, players, frozen, slit_active=False, nav=None):
        if frozen:
            return
        if slit_active:
            self._update_slit_laugh(dt, players, nav)
            return
        speed = C.ANT_SPEED * (C.MAYO_SLOW_FACTOR if now < self.slow_until else 1.0)
        target = _nearest_player(players, self.pos, C.ANT_CHASE_RANGE)
        elevated = target is not None and target.pos[2] > C.ANT_CLIMB_TRIGGER
        on_roof = self.pos[2] > 2.0       # уже забрался на платформу/дорожку

        if target and on_roof:
            # НА КРЫШЕ: стены ниже — идём прямо к игроку без коллизий с ними
            # (упавший с края обрабатывается _update_height). Это чинит «застревание».
            dx, dy = target.pos[0] - self.pos[0], target.pos[1] - self.pos[1]
            n = math.hypot(dx, dy) or 1.0
            self.dir = [dx / n, dy / n]
            self.pos[0] += self.dir[0] * speed * dt
            self.pos[1] += self.dir[1] * speed * dt
        elif target:
            # НА ЗЕМЛЕ: стратегия ОКРУЖЕНИЯ. Издалека — умным путём по графу к игроку;
            # вблизи — занимаем свой сектор кольца вокруг игрока (с разных сторон).
            dx, dy = target.pos[0] - self.pos[0], target.pos[1] - self.pos[1]
            pdist = math.hypot(dx, dy)
            if elevated or pdist > C.ANT_SURROUND_RADIUS + 3.0:
                # при лазании по стене → целиться в кольцо рядом с игроком, не прямо под него
                is_climbing = (elevated
                               and near_wall(self.pos[0], self.pos[1], _WALL_NEAR_RECTS))
                if is_climbing:
                    phi = (self.aid * 2.3999632) % (2 * math.pi)
                    tx = target.pos[0] + math.cos(phi) * (C.ANT_SURROUND_RADIUS + 1.0)
                    ty = target.pos[1] + math.sin(phi) * (C.ANT_SURROUND_RADIUS + 1.0)
                    cdx, cdy = tx - self.pos[0], ty - self.pos[1]
                    n = math.hypot(cdx, cdy) or 1.0
                    self.dir = [cdx / n, cdy / n]
                else:
                    d = nav.direction(self.pos[0], self.pos[1]) if nav else None
                    if d is None:
                        n = pdist or 1.0
                        d = (dx / n, dy / n)
                    self.dir = [d[0], d[1]]
            else:
                # свой угол на кольце (золотой угол по aid -> разные стороны)
                ang = (self.aid * 2.3999632) % (2 * math.pi)
                tx = target.pos[0] + math.cos(ang) * C.ANT_SURROUND_RADIUS
                ty = target.pos[1] + math.sin(ang) * C.ANT_SURROUND_RADIUS
                sdx, sdy = tx - self.pos[0], ty - self.pos[1]
                n = math.hypot(sdx, sdy) or 1.0
                self.dir = [sdx / n, sdy / n]
            self._step_ground(speed * dt)
        else:
            if random.random() < 0.02:
                ang = random.uniform(0, 2 * math.pi)
                self.dir = [math.cos(ang), math.sin(ang)]
            self._step_ground(speed * dt)

        self.pos[0], self.pos[1] = _clamp_to_arena(self.pos[0], self.pos[1])
        self._update_height(dt, target, elevated)

    def _step_ground(self, dist):
        """Шаг по земле с проскальзыванием вдоль стен (чтобы не застревать в углах)."""
        x, y = self.pos[0], self.pos[1]
        nx = x + self.dir[0] * dist
        ny = y + self.dir[1] * dist
        if not in_any_building(nx, ny, _BUILDING_RECTS):
            self.pos[0], self.pos[1] = nx, ny
        elif not in_any_building(nx, y, _BUILDING_RECTS):
            self.pos[0] = nx                      # скользим вдоль стены по X
        elif not in_any_building(x, ny, _BUILDING_RECTS):
            self.pos[1] = ny                      # скользим вдоль стены по Y

    def _update_slit_laugh(self, dt, players, nav=None):
        """Во время ЩЕЛИ встать ПО КРУГУ вокруг игрока (на радиусе, с разбросом) и
        ржать — стоя на месте и СЛУЧАЙНО подпрыгивая. Издалека добегают умным путём."""
        target = _nearest_player(players, self.pos, 9999)
        if target:
            pdx, pdy = target.pos[0] - self.pos[0], target.pos[1] - self.pos[1]
            pdist = math.hypot(pdx, pdy)
            # своя точка на окружности (золотой угол -> равномерно по кругу; разные кольца)
            ang = (self.aid * 2.3999632) % (2 * math.pi)
            r = C.ANT_SLIT_RADIUS + (self.aid % 3) * 0.9
            if pdist > r + 4.0:
                # ещё далеко от круга — бежим к игроку по графу (обходя стены)
                d = nav.direction(self.pos[0], self.pos[1]) if nav else None
                if d is None:
                    n = pdist or 1.0
                    d = (pdx / n, pdy / n)
                self.dir = [d[0], d[1]]
                self._step_ground(C.ANT_SLIT_SPEED * dt)
            else:
                # рядом с игроком (открытая зона) — встаём точно на свою точку круга
                tx = target.pos[0] + math.cos(ang) * r
                ty = target.pos[1] + math.sin(ang) * r
                dx, dy = tx - self.pos[0], ty - self.pos[1]
                d = math.hypot(dx, dy)
                if d > 0.5:
                    ux, uy = dx / d, dy / d
                    self.dir = [ux, uy]
                    self._step_ground(C.ANT_SLIT_SPEED * dt)   # не залезать в стены/столбы
                else:
                    # стоит на круге лицом к игроку и произвольно подпрыгивает
                    fn = pdist or 1.0
                    self.dir = [pdx / fn, pdy / fn]
                    if self.vz == 0.0 and random.random() < dt * 2.0:
                        self.vz = random.uniform(0.6, 1.0) * C.ANT_SLIT_JUMP
        self.pos[0], self.pos[1] = _clamp_to_arena(self.pos[0], self.pos[1])
        # гравитация/прыжок над землёй
        ground = support_z(self.pos[0], self.pos[1], self.pos[2])
        if self.pos[2] > ground or self.vz > 0.0:
            self.vz += C.GRAVITY * dt
            self.pos[2] += self.vz * dt
            if self.pos[2] <= ground:
                self.pos[2] = ground
                self.vz = 0.0
        else:
            self.pos[2] = ground
            self.vz = 0.0

    def _update_height(self, dt, target, elevated):
        """Лезть ВВЕРХ только прижавшись к ближайшей стене (не по воздуху), иначе падать."""
        x, y = self.pos[0], self.pos[1]
        plat = platform_top_at(x, y)
        if (elevated and plat > 0.0 and near_wall(x, y, _WALL_NEAR_RECTS)
                and self.pos[2] < min(target.pos[2], plat) - 0.05):
            # таракан ползёт вверх по стене к высоко стоящему игроку, выходя на платформу
            self.pos[2] = min(min(target.pos[2], plat), self.pos[2] + C.ANT_CLIMB_SPEED * dt)
            self.vz = 0.0
            return
        # иначе — оседаем на опору; сошёл с края платформы -> падает («спрыгивает» к игроку)
        ground = support_z(x, y, self.pos[2])
        if self.pos[2] > ground + 0.01:
            self.vz += C.GRAVITY * dt
            self.pos[2] += self.vz * dt
            if self.pos[2] <= ground:
                self.pos[2] = ground
                self.vz = 0.0
        else:
            self.pos[2] = ground
            self.vz = 0.0

    def snapshot(self):
        return [self.aid, round(self.pos[0], 2), round(self.pos[1], 2), round(self.pos[2], 2)]


class Boss:
    """Босс «Папаня»: вместо HP — шкала уважения (заполняется сиропом).

    Две фазы: 1) кидает ракеты; 2) (>= BOSS_PHASE2_FRAC уважения) кидает ЧАЩЕ и
    испускает ГАЗ — едкий дым, замедляющий игроков рядом."""
    __slots__ = ("pos", "dir", "respect", "h", "throw_at", "gas_at")

    def __init__(self, now):
        self.respect = 0
        self.pos = [BOSS_SPAWN[0], BOSS_SPAWN[1], 0.0]   # всегда фикс-точка
        self.dir = [0.0, 1.0]
        self.h = 0.0
        self.throw_at = now + C.BOSS_THROW_INTERVAL      # не кидает сразу
        self.gas_at = 0.0

    @property
    def phase(self):
        return 2 if self.respect >= C.BOSS_RESPECT_MAX * C.BOSS_PHASE2_FRAC else 1

    def update(self, dt, now, players, frozen, nav=None, shots=None):
        if frozen:
            return
        target = _nearest_player(players, self.pos, 9999)   # всегда к ближайшему
        if target:
            # умный путь к игроку по графу клеток (обход стен), лицом — на игрока
            nd = nav.direction(self.pos[0], self.pos[1]) if nav else None
            if nd is None:
                dx, dy = target.pos[0] - self.pos[0], target.pos[1] - self.pos[1]
                n = math.hypot(dx, dy) or 1.0
                nd = (dx / n, dy / n)
            self.dir = [nd[0], nd[1]]
            fdx, fdy = target.pos[0] - self.pos[0], target.pos[1] - self.pos[1]
            self.h = math.degrees(math.atan2(-fdx, fdy))    # лицом прямо к игроку

        # уворот: если снаряд летит рядом — стрейфим перпендикулярно
        dodge_x, dodge_y = 0.0, 0.0
        if shots:
            for sh in shots.values():
                if sh.kind != "syrup":
                    continue
                dx = self.pos[0] - sh.pos[0]
                dy = self.pos[1] - sh.pos[1]
                dist = math.hypot(dx, dy)
                if dist < C.BOSS_DODGE_RANGE and dist > 0.1:
                    # снаряд летит к боссу?
                    vn = math.hypot(sh.vel[0], sh.vel[1]) or 1.0
                    approach = -(sh.vel[0] * dx + sh.vel[1] * dy) / (vn * dist)
                    if approach > 0.3:
                        # перпендикуляр влево/вправо (выбираем сторону по id снаряда)
                        side = 1 if sh.sid % 2 == 0 else -1
                        dodge_x += -sh.vel[1] / vn * side
                        dodge_y +=  sh.vel[0] / vn * side
            dn = math.hypot(dodge_x, dodge_y)
            if dn > 0.01:
                dodge_x /= dn; dodge_y /= dn

        move_x = self.dir[0] + dodge_x * 1.6
        move_y = self.dir[1] + dodge_y * 1.6
        mn = math.hypot(move_x, move_y) or 1.0
        move_x /= mn; move_y /= mn

        nx = self.pos[0] + move_x * C.BOSS_SPEED * dt
        ny = self.pos[1] + move_y * C.BOSS_SPEED * dt
        if not in_any_building(nx, ny, _BUILDING_RECTS):
            self.pos[0], self.pos[1] = nx, ny
        elif not in_any_building(nx, self.pos[1], _BUILDING_RECTS):
            self.pos[0] = nx
        elif not in_any_building(self.pos[0], ny, _BUILDING_RECTS):
            self.pos[1] = ny
        self.pos[0], self.pos[1] = _clamp_to_arena(self.pos[0], self.pos[1])

    def snapshot(self):
        return {"pos": [round(v, 2) for v in self.pos], "h": round(self.h, 1),
                "respect": self.respect, "max": C.BOSS_RESPECT_MAX, "phase": self.phase}


class BossShot:
    """Взрывной снаряд босса — летит по дуге в игрока, взрывается с AoE-уроном."""
    __slots__ = ("bsid", "pos", "vel", "die_at")

    def __init__(self, bsid, pos, target_pos, target_vel, now):
        self.bsid = bsid
        self.pos = [pos[0], pos[1], pos[2]]
        sp = C.BOSS_PROJECTILE_SPEED
        # УПРЕЖДЕНИЕ: целимся ТОЧНО туда, где игрок окажется к моменту прилёта
        tx, ty = target_pos[0], target_pos[1]
        for _ in range(5):
            L = math.hypot(tx - pos[0], ty - pos[1]) or 1.0
            t = max(0.25, L / sp)
            tx = target_pos[0] + target_vel[0] * t
            ty = target_pos[1] + target_vel[1] * t
        dx, dy = tx - pos[0], ty - pos[1]
        L = math.hypot(dx, dy) or 1.0
        t = max(0.25, L / sp)
        # вертикальная скорость, чтобы упасть РОВНО в z=0 за время t:
        #   z(t) = z0 + vz*t + 0.5*g*t^2 = 0  ->  vz = (-z0 - 0.5*g*t^2)/t
        vz = (-pos[2] - 0.5 * C.GRAVITY * t * t) / t
        self.vel = [dx / L * sp, dy / L * sp, vz]
        self.die_at = now + C.BOSS_PROJECTILE_LIFETIME

    def update(self, dt):
        for i in range(3):
            self.pos[i] += self.vel[i] * dt
        self.vel[2] += C.GRAVITY * dt

    def snapshot(self):
        return [self.bsid, round(self.pos[0], 2), round(self.pos[1], 2), round(self.pos[2], 2)]


class Shot:
    __slots__ = ("sid", "owner", "pos", "vel", "die_at", "kind")

    def __init__(self, sid, owner, pos, direction, now, kind):
        self.sid = sid
        self.owner = owner
        self.kind = kind  # "syrup" | "mayo"
        self.pos = list(pos)
        n = math.sqrt(sum(d * d for d in direction)) or 1.0
        self.vel = [d / n * C.PROJECTILE_SPEED for d in direction]
        self.die_at = now + C.PROJECTILE_LIFETIME

    def update(self, dt):
        for i in range(3):
            self.pos[i] += self.vel[i] * dt
        self.vel[2] += C.GRAVITY * dt * 0.15  # более пологая дуга — легче целиться

    def snapshot(self):
        k = 1 if self.kind == C.WEAPON_MAYO else 0
        return [self.sid, round(self.pos[0], 2), round(self.pos[1], 2), round(self.pos[2], 2), k]


class Bee:
    """Самонаводящаяся пчела — летит к ближайшему таракану."""
    __slots__ = ("bid", "owner", "pos", "vel", "die_at")

    def __init__(self, bid, owner, pos, direction, now):
        self.bid = bid
        self.owner = owner
        self.pos = list(pos)
        n = math.sqrt(sum(d * d for d in direction)) or 1.0
        self.vel = [d / n * C.BEE_SPEED for d in direction]
        self.die_at = now + C.BEE_LIFETIME

    def update(self, dt, ants):
        # навестись на ближайшего таракана
        target, best = None, 1e18
        for ant in ants:
            d = _dist2(self.pos, ant.pos)
            if d < best:
                target, best = ant, d
        if target:
            dx = target.pos[0] - self.pos[0]
            dy = target.pos[1] - self.pos[1]
            dz = (target.pos[2] + 0.3) - self.pos[2]
            n = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
            desired = [dx / n * C.BEE_SPEED, dy / n * C.BEE_SPEED, dz / n * C.BEE_SPEED]
            for i in range(3):  # плавный поворот
                self.vel[i] += (desired[i] - self.vel[i]) * min(1.0, 6 * dt)
        for i in range(3):
            self.pos[i] += self.vel[i] * dt

    def snapshot(self):
        return [self.bid, round(self.pos[0], 2), round(self.pos[1], 2), round(self.pos[2], 2)]


class NeonAnt:
    """Синий неоновый муравей: держит дистанцию (кайтит) и стреляет шкибиди-зельем."""
    __slots__ = ("nid", "pos", "dir", "h", "slow_until", "hp", "shoot_at")

    def __init__(self, nid, now):
        self.nid = nid
        self.slow_until = 0.0
        self.hp = C.NEON_ANT_HP
        self.h = 0.0
        self.shoot_at = now + random.uniform(0.6, C.NEON_ANT_SHOOT_INTERVAL)
        self._reset_pos()

    def _reset_pos(self):
        for _ in range(40):
            x = random.uniform(-C.WORLD_SIZE, C.WORLD_SIZE)
            y = random.uniform(-C.WORLD_SIZE, C.WORLD_SIZE)
            if not in_any_building(x, y, _BUILDING_RECTS):
                break
        else:
            x, y = 0.0, -20.0  # безопасный fallback вне стен
        self.pos = [x, y, 0.0]
        ang = random.uniform(0, 2 * math.pi)
        self.dir = [math.cos(ang), math.sin(ang)]

    def update(self, dt, now, players, frozen):
        if frozen:
            return
        speed = C.NEON_ANT_SPEED * (C.MAYO_SLOW_FACTOR if now < self.slow_until else 1.0)
        target = _nearest_player(players, self.pos, C.NEON_ANT_CHASE_RANGE)
        if target:
            dx, dy = target.pos[0] - self.pos[0], target.pos[1] - self.pos[1]
            dist = math.hypot(dx, dy) or 1.0
            ux, uy = dx / dist, dy / dist
            self.h = math.degrees(math.atan2(-ux, uy))   # лицом к игроку
            # стену не простреливают: если игрок за стеной — сперва выходим на него
            los = not line_blocked(self.pos[0], self.pos[1],
                                   target.pos[0], target.pos[1], _LOS_RECTS)
            pref = C.NEON_ANT_PREFERRED_RANGE
            if not los:
                self.dir = [ux, uy]                       # выйти из-за стены на игрока
            elif dist > pref * 1.2:
                self.dir = [ux, uy]                       # подойти на дистанцию стрельбы
            elif dist < pref * 0.75:
                self.dir = [-ux, -uy]                     # отступить (кайт)
            else:
                self.dir = [-uy, ux]                      # стрейф по кругу вокруг игрока
        elif random.random() < 0.02:
            ang = random.uniform(0, 2 * math.pi)
            self.dir = [math.cos(ang), math.sin(ang)]

        nx = self.pos[0] + self.dir[0] * speed * dt
        ny = self.pos[1] + self.dir[1] * speed * dt
        if in_any_building(nx, ny, _BUILDING_RECTS):
            ang = random.uniform(0, 2 * math.pi)
            self.dir = [math.cos(ang), math.sin(ang)]
        else:
            self.pos[0], self.pos[1] = nx, ny
        self.pos[0], self.pos[1] = _clamp_to_arena(self.pos[0], self.pos[1])

    def snapshot(self):
        return [self.nid, round(self.pos[0], 2), round(self.pos[1], 2), round(self.h, 1), self.hp]


class AntShot:
    """Шкибиди-зелье — синий неоновый снаряд неонового муравья (бьёт игрока)."""
    __slots__ = ("asid", "pos", "vel", "die_at")

    def __init__(self, asid, pos, target_pos, now):
        self.asid = asid
        self.pos = [pos[0], pos[1], pos[2]]
        dx = target_pos[0] - pos[0]
        dy = target_pos[1] - pos[1]
        dz = target_pos[2] - pos[2]
        n = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        sp = C.SKIBIDI_SPEED
        self.vel = [dx / n * sp, dy / n * sp, dz / n * sp]
        self.die_at = now + C.SKIBIDI_LIFETIME

    def update(self, dt):
        for i in range(3):
            self.pos[i] += self.vel[i] * dt
        self.vel[2] += C.GRAVITY * dt * 0.12   # лёгкая дуга

    def snapshot(self):
        return [self.asid, round(self.pos[0], 2), round(self.pos[1], 2), round(self.pos[2], 2)]


class Slit:
    """ЩЕЛЬ — настенный враг: два прижатых шара. Шкала удовлетворённости (0..1)
    наполняется попаданиями МАЙОНЕЗА. Заполнил до краёв — щель повержена."""
    __slots__ = ("sid", "pos", "normal", "h", "progress", "calmed")

    def __init__(self, sid, pos, normal):
        self.sid = sid
        self.pos = list(pos)          # [x, y, z]
        self.normal = list(normal)    # [nx, ny] — лицом в центр арены
        self.h = math.degrees(math.atan2(-normal[0], normal[1]))
        self.progress = 0.0           # шкала удовлетворённости 0..1 (майонез)
        self.calmed = False

    def snapshot(self):
        return [self.sid, round(self.pos[0], 2), round(self.pos[1], 2),
                round(self.pos[2], 2), round(self.h, 1), round(self.progress, 3),
                1 if self.calmed else 0]


class BKShot:
    """Фиолетовый лазерный выстрел BLACK KING (фаза 2)."""
    __slots__ = ("bksid", "pos", "vel", "die_at", "grav")

    def __init__(self, bksid, origin, target_pos, now, grav=0.10):
        self.bksid = bksid
        self.pos = list(origin)
        dx = target_pos[0] - origin[0]
        dy = target_pos[1] - origin[1]
        dz = target_pos[2] - origin[2]
        n = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        s = C.BK_SHOT_SPEED
        self.vel = [dx / n * s, dy / n * s, dz / n * s]
        self.die_at = now + C.BK_SHOT_LIFETIME
        self.grav = grav

    def update(self, dt):
        for i in range(3):
            self.pos[i] += self.vel[i] * dt
        self.vel[2] += C.GRAVITY * dt * self.grav

    def snapshot(self):
        return [self.bksid, round(self.pos[0], 2), round(self.pos[1], 2), round(self.pos[2], 2)]


class BKLivingCup:
    """Оживший стакан (фаза 2 BLACK KING): медленно ползёт к ближайшему игроку,
    стреляет замедляющими снарядами, роняет аптечки."""
    __slots__ = ("cid", "pos", "dir", "shoot_at", "drop_at")

    def __init__(self, cid, pos, now):
        self.cid = cid
        self.pos = [float(pos[0]), float(pos[1]), 0.0]
        self.dir = [0.0, 0.0]
        self.shoot_at = now + random.uniform(1.5, C.BK_CUP_SHOOT_INTERVAL)
        self.drop_at = now + C.BK_CUP_HEALTH_DROP_INTERVAL

    def snapshot(self):
        return [self.cid, round(self.pos[0], 2), round(self.pos[1], 2)]


class BKCupShot:
    """Зелёный замедляющий снаряд ожившего стакана."""
    __slots__ = ("csid", "pos", "vel", "die_at")

    def __init__(self, csid, origin, target_pos, now):
        self.csid = csid
        self.pos = list(origin)
        dx = target_pos[0] - origin[0]
        dy = target_pos[1] - origin[1]
        dz = target_pos[2] - origin[2]
        n = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        s = C.BK_CUP_SHOT_SPEED
        self.vel = [dx / n * s, dy / n * s, dz / n * s]
        self.die_at = now + C.BK_CUP_SHOT_LIFETIME

    def update(self, dt):
        for i in range(3):
            self.pos[i] += self.vel[i] * dt
        self.vel[2] += C.GRAVITY * dt * 0.08

    def snapshot(self):
        return [self.csid, round(self.pos[0], 2), round(self.pos[1], 2), round(self.pos[2], 2)]


class BlackKing:
    """Финальный секретный босс: прыгает-скачет по всей карте, рикошетит от стен.
    Нет шкалы уважения — настоящее HP, наносится сиропом. Первые CINEMATIC_TIME секунд
    стоит на месте (кат-сцена)."""
    __slots__ = ("pos", "dir", "hp", "h", "target_pos", "retarget_at",
                 "spawn_minion_at", "vz", "hop_at", "cinematic_until", "phase",
                 "shoot_at", "flying")

    def __init__(self, now):
        self.pos = [0.0, 38.0, 0.0]    # стартует у северного спавна
        self.dir = [1.0, 0.0]
        self.hp = C.BLACK_KING_HP
        self.h = 0.0
        self.target_pos = [0.0, 38.0]
        self.retarget_at = now + C.BLACK_KING_CINEMATIC_TIME   # начинает бегать после кат-сцены
        self.spawn_minion_at = now + C.BLACK_KING_CINEMATIC_TIME + C.BLACK_KING_MINION_SPAWN_INTERVAL
        self.vz = 0.0
        self.hop_at = now + C.BLACK_KING_CINEMATIC_TIME        # прыгает после кат-сцены
        self.phase = 1
        self.shoot_at = 0.0
        self.flying = False    # режим полёта (игрок на 2-м этаже)

    @staticmethod
    def _random_point():
        for _ in range(30):
            x = random.uniform(-C.WORLD_SIZE * 0.75, C.WORLD_SIZE * 0.75)
            y = random.uniform(-C.WORLD_SIZE * 0.75, C.WORLD_SIZE * 0.75)
            if not in_any_building(x, y, _BUILDING_RECTS):
                return [x, y]
        return [0.0, 0.0]

    def update(self, dt, now, players=None):
        # обновить режим полёта: летим если хоть один игрок на 2-м этаже
        if players and self.phase == 2:
            any_up = any(
                not pl.dead and pl.pos[2] >= WALL_HEIGHT - 2.0
                for pl in players.values()
            )
            self.flying = any_up
        else:
            self.flying = False

        # во время кат-сцены не двигаться
        if now < self.retarget_at and self.pos == [0.0, 38.0, 0.0]:
            # стоим на месте
            pass
        else:
            # выбор новой случайной цели
            if now >= self.retarget_at:
                self.target_pos = self._random_point()
                self.retarget_at = now + random.uniform(*C.BLACK_KING_WANDER_INTERVAL)

            dx, dy = self.target_pos[0] - self.pos[0], self.target_pos[1] - self.pos[1]
            dist = math.hypot(dx, dy)
            if dist > 1.5:
                self.dir = [dx / dist, dy / dist]

            # движение с РИКОШЕТОМ от стен (не скользит, а отражается)
            step = C.BLACK_KING_SPEED * dt
            nx = self.pos[0] + self.dir[0] * step
            ny = self.pos[1] + self.dir[1] * step
            if in_any_building(nx, ny, _BUILDING_RECTS):
                can_x = not in_any_building(nx, self.pos[1], _BUILDING_RECTS)
                can_y = not in_any_building(self.pos[0], ny, _BUILDING_RECTS)
                if not can_x and not can_y:
                    self.dir = [-self.dir[0], -self.dir[1]]    # отброс назад
                elif not can_x:
                    self.dir[0] = -self.dir[0]                 # отражение по X
                else:
                    self.dir[1] = -self.dir[1]                 # отражение по Y
                self.retarget_at = 0.0   # сразу выбрать новую цель
                # попробовать двинуться после рикошета
                nx = self.pos[0] + self.dir[0] * step
                ny = self.pos[1] + self.dir[1] * step
                if not in_any_building(nx, ny, _BUILDING_RECTS):
                    self.pos[0], self.pos[1] = nx, ny
            else:
                self.pos[0], self.pos[1] = nx, ny
            self.pos[0], self.pos[1] = _clamp_to_arena(self.pos[0], self.pos[1])

        if self.flying:
            # зависание над 2-м этажом: плавный подъём к BK_HOVER_Z
            target_z = C.BK_HOVER_Z
            dz = target_z - self.pos[2]
            self.pos[2] += math.copysign(
                min(abs(dz), C.BK_HOVER_RISE_SPEED * dt), dz)
            self.vz = 0.0
        else:
            # спуск на землю если летели
            if self.pos[2] > 0.1:
                self.vz += C.GRAVITY * dt
                self.pos[2] = max(0.0, self.pos[2] + self.vz * dt)
                if self.pos[2] <= 0.0:
                    self.vz = 0.0
            else:
                # обычные прыжки по земле
                if now >= self.hop_at and self.pos[2] <= 0.02:
                    self.vz = C.BLACK_KING_HOP_VZ
                    self.hop_at = now + C.BLACK_KING_HOP_INTERVAL
                self.vz += C.GRAVITY * dt
                self.pos[2] = max(0.0, self.pos[2] + self.vz * dt)
                if self.pos[2] <= 0.0:
                    self.vz = 0.0

        if self.flying:
            self.h += 200.0 * dt   # вращение вокруг оси при полёте
        else:
            self.h = math.degrees(math.atan2(-self.dir[0], self.dir[1]))

    def snapshot(self):
        now = time.time()
        return {"pos": [round(v, 2) for v in self.pos],
                "h": round(self.h, 1), "hp": self.hp, "max_hp": C.BLACK_KING_HP,
                "cinematic": now < self.spawn_minion_at - C.BLACK_KING_MINION_SPAWN_INTERVAL,
                "phase": self.phase, "flying": self.flying}


class BlackKingMinion:
    """Маленькая копия BLACK KING: движется к ближайшему игроку в припрыжку.
    Если игрок на втором уровне — карабкается по стенам."""
    __slots__ = ("mid", "pos", "dir", "hp", "vz", "hop_at", "climbing")

    def __init__(self, mid, spawn_pos=None):
        self.mid = mid
        self.hp = C.BLACK_KING_MINION_HP
        self.vz = 0.0
        self.hop_at = 0.0               # прыгнет сразу при первом update
        self.climbing = False
        if spawn_pos is None:
            for _ in range(40):
                x = random.uniform(-C.WORLD_SIZE * 0.7, C.WORLD_SIZE * 0.7)
                y = random.uniform(-C.WORLD_SIZE * 0.7, C.WORLD_SIZE * 0.7)
                if not in_any_building(x, y, _BUILDING_RECTS):
                    spawn_pos = (x, y)
                    break
            else:
                spawn_pos = (0.0, -20.0)
        self.pos = [spawn_pos[0], spawn_pos[1], 0.0]
        ang = random.uniform(0, 2 * math.pi)
        self.dir = [math.cos(ang), math.sin(ang)]

    def update(self, dt, now, players):
        target = _nearest_player(players, self.pos, 9999)
        target_z = target.pos[2] if target else 0.0
        if target:
            dx = target.pos[0] - self.pos[0]
            dy = target.pos[1] - self.pos[1]
            d = math.hypot(dx, dy)
            if d > 0.1:
                self.dir = [dx / d, dy / d]

        # карабканье по стенам (если игрок на втором уровне)
        is_near = near_wall(self.pos[0], self.pos[1], _WALL_NEAR_RECTS)
        wall_top = platform_top_at(self.pos[0], self.pos[1]) if is_near else 0
        should_climb = is_near and wall_top > 0 and target_z > C.ANT_CLIMB_TRIGGER

        if should_climb:
            self.climbing = True
            self.vz = 0.0
            self.pos[2] = min(self.pos[2] + C.ANT_CLIMB_SPEED * dt, wall_top)
            step = C.BLACK_KING_MINION_SPEED * 0.25 * dt
            nx = self.pos[0] + self.dir[0] * step
            ny = self.pos[1] + self.dir[1] * step
            self.pos[0], self.pos[1] = nx, ny
            self.pos[0], self.pos[1] = _clamp_to_arena(self.pos[0], self.pos[1])
            return
        elif self.climbing and self.pos[2] > 0.01:
            # спуск вниз
            self.pos[2] = max(0.0, self.pos[2] - 8.0 * dt)
            if self.pos[2] <= 0.01:
                self.climbing = False
            return
        else:
            self.climbing = False

        # горизонтальное движение
        step = C.BLACK_KING_MINION_SPEED * dt
        nx = self.pos[0] + self.dir[0] * step
        ny = self.pos[1] + self.dir[1] * step
        if not in_any_building(nx, ny, _BUILDING_RECTS):
            self.pos[0], self.pos[1] = nx, ny
        elif not in_any_building(nx, self.pos[1], _BUILDING_RECTS):
            self.pos[0] = nx
        elif not in_any_building(self.pos[0], ny, _BUILDING_RECTS):
            self.pos[1] = ny
        self.pos[0], self.pos[1] = _clamp_to_arena(self.pos[0], self.pos[1])
        # попрыгунчик: при приземлении — сразу новый прыжок (без таймера)
        self.vz += C.GRAVITY * dt
        new_z = self.pos[2] + self.vz * dt
        if new_z <= 0.0:
            self.pos[2] = 0.0
            self.vz = C.BLACK_KING_MINION_HOP_VZ   # мгновенный отскок
        else:
            self.pos[2] = new_z

    def snapshot(self):
        return [self.mid, round(self.pos[0], 2), round(self.pos[1], 2), round(self.pos[2], 2)]


class World:
    def __init__(self):
        self.players = {}
        self.ants = {}          # aid -> Ant
        self.neon_ants = {}     # nid -> NeonAnt (синие стрелки, после 3-й волны)
        self.ant_shots = {}     # asid -> AntShot (шкибиди-зелье)
        self._next_neon_id = 1
        self._next_ant_shot_id = 1
        self.shots = {}
        self.bees = {}
        self.drops = {}         # did -> {"pos":[x,y,z], "kind":str}
        self._next_drop_id = 1
        self.boss = None
        self.boss_shots = {}    # bsid -> BossShot
        self._next_boss_shot_id = 1
        self.slits = {}              # sid -> Slit (настенный враг «ЩЕЛЬ»)
        self._next_slit_id = 1
        self.slit_event_active = False
        self.slit_deadline = 0.0     # дедлайн текущего события (иначе все умирают)
        self.next_slit_at = 0.0      # когда стартует следующее событие щелей
        self.wave = 0
        self.freeze_until = 0.0      # заморозка тараканов (ультимейт)
        self.next_wave_at = 0.0
        self._wave_pending = True
        self._next_shot_id = 1
        self._next_bee_id = 1
        self._next_ant_id = 1
        self.events = []
        self.nav = NavGrid()         # граф клеток для умного поиска пути мобами
        self.cup_spots = [False] * len(CUP_SPOTS)   # заняты ли 4 угловых пьедестала
        self.black_king = False      # запущена ли секретная фаза BLACK KING
        self._pre_bk_wave = 0        # волна которая была ДО призыва BLACK KING
        self.bk_boss = None          # BlackKing boss instance
        self.bk_minions = {}         # mid -> BlackKingMinion
        self._next_bk_minion_id = 1
        self._bk_voice_at = 0.0      # когда следующая случайная реплика BLACK KING
        # фаза 2 BLACK KING
        self.bk_shots = {}           # bksid -> BKShot
        self._next_bk_shot_id = 1
        self.bk_living_cups = {}     # cid -> BKLivingCup (оживают в фазе 2)
        self.bk_cup_shots = {}       # csid -> BKCupShot
        self._next_bk_cup_shot_id = 1
        self._all_dead = False       # были ли все игроки мертвы (для сброса фазы)

    # --- игроки ---
    def add_player(self, pid, name):
        p = Player(pid, name)
        if name == "GODBLESSER":
            p.cups = 4
        self.players[pid] = p
        if len(self.players) == 1 and self.wave == 0:
            self._wave_pending = True
            self.next_wave_at = time.time() + 2.0
            self.next_slit_at = time.time() + random.uniform(*C.SLIT_INTERVAL)
        return p

    def remove_player(self, pid):
        pl = self.players.pop(pid, None)
        if not self.players:
            # все вышли — сброс до начального состояния
            self.ants.clear()
            self.neon_ants.clear()
            self.ant_shots.clear()
            self.shots.clear()
            self.bees.clear()
            self.boss_shots.clear()
            self.boss = None
            self.slits = {}
            self.slit_event_active = False
            self.drops.clear()
            self.wave = 0
            self._wave_pending = False
            self.next_wave_at = 0.0
            self.next_slit_at = 0.0
            # сброс фазы BLACK KING
            self.bk_boss = None
            self.bk_minions.clear()
            self.bk_shots.clear()
            self.bk_living_cups.clear()
            self.bk_cup_shots.clear()
            self.black_king = False
            self.cup_spots = [False] * len(CUP_SPOTS)
        return pl

    def set_state(self, pid, pos, h, p):
        pl = self.players.get(pid)
        if not pl:
            return
        x, y = _clamp_to_arena(pos[0], pos[1])
        pl.pos = [x, y, max(0.0, pos[2])]
        pl.h, pl.p = h, p

    def set_emote(self, pid, emote, pet):
        pl = self.players.get(pid)
        if not pl:
            return
        if emote in C.EMOTES:
            pl.emote = emote
            pl.emote_until = time.time() + 3.0
        if pet:
            pl.pet = pet

    def shoot(self, pid, pos, direction, weapon=C.WEAPON_SYRUP):
        pl = self.players.get(pid)
        now = time.time()
        if not pl or pl.hp <= 0 or pl.dead:
            return
        # пчёлы доступны ТОЛЬКО в окне LIT ENERGY
        if weapon == C.WEAPON_HIVE and now >= pl.bee_until:
            return
        cooldown = C.HIVE_COOLDOWN if weapon == C.WEAPON_HIVE else C.SPRAY_COOLDOWN
        if now - pl.last_shot < cooldown:
            return
        pl.last_shot = now
        if weapon == C.WEAPON_HIVE:
            for _ in range(C.HIVE_BEES):
                d = [direction[0] + random.uniform(-0.2, 0.2),
                     direction[1] + random.uniform(-0.2, 0.2),
                     direction[2] + random.uniform(-0.1, 0.1)]
                self.bees[self._next_bee_id] = Bee(self._next_bee_id, pid, pos, d, now)
                self._next_bee_id += 1
        else:
            kind = weapon if weapon in (C.WEAPON_SYRUP, C.WEAPON_MAYO) else C.WEAPON_SYRUP
            self.shots[self._next_shot_id] = Shot(self._next_shot_id, pid, pos, direction, now, kind)
            self._next_shot_id += 1

    def use_lit_energy(self, pid):
        """Потратить один LIT ENERGY -> открыть пчёл на BEE_WINDOW секунд."""
        pl = self.players.get(pid)
        now = time.time()
        if not pl or pl.dead or pl.lit_energy <= 0 or now < pl.bee_until:
            return
        pl.lit_energy -= 1
        pl.bee_until = now + C.BEE_WINDOW
        self.events.append({"t": "event", "kind": "lit_used",
                            "by": pl.name, "time": C.BEE_WINDOW})

    def place_cup(self, pid):
        """Поставить белый стакан на свободный угловой пьедестал рядом с игроком.
        Когда заняты все 4 — стартует секретная фаза BLACK KING."""
        pl = self.players.get(pid)
        if not pl or pl.dead or pl.cups <= 0:
            return
        for i, (sx, sy) in enumerate(CUP_SPOTS):
            if self.cup_spots[i]:
                continue
            if (pl.pos[0] - sx) ** 2 + (pl.pos[1] - sy) ** 2 <= CUP_SPOT_RADIUS ** 2:
                self.cup_spots[i] = True
                pl.cups -= 1
                self.events.append({"t": "event", "kind": "cup_placed",
                                    "spot": i, "count": sum(self.cup_spots)})
                if all(self.cup_spots) and not self.black_king:
                    self._pre_bk_wave = self.wave   # запомнить текущую волну
                    self.black_king = True
                    now2 = time.time()
                    self.bk_boss = BlackKing(now2)
                    self._bk_voice_at = now2 + C.BLACK_KING_CINEMATIC_TIME + random.uniform(*C.BLACK_KING_VOICE_INTERVAL)
                    # очистить всех обычных мобов — начинается фаза BLACK KING
                    self.ants.clear()
                    self.neon_ants.clear()
                    self.ant_shots.clear()
                    self.shots.clear()
                    self.bees.clear()
                    self.boss_shots.clear()
                    self.boss = None
                    self.slits = {}
                    self.slit_event_active = False
                    self._wave_pending = False   # волны больше не спавнятся
                    self.events.append({"t": "event", "kind": "black_king_spawn"})
                return

    def ultimate(self, pid):
        pl = self.players.get(pid)
        now = time.time()
        if not pl or pl.dead or now < pl.ult_ready_at:
            return
        pl.ult_ready_at = now + C.ULT_COOLDOWN
        self.freeze_until = now + C.ULT_DURATION
        self.events.append({"t": "event", "kind": "ultimate", "by": pl.name})

    # --- волны ---
    def _start_wave(self):
        self.wave += 1
        count = min(C.ANT_COUNT, C.WAVE_START + (self.wave - 1) * C.WAVE_GROWTH)
        for _ in range(count):
            self.ants[self._next_ant_id] = Ant(self._next_ant_id,
                                               self.nav.random_free_point())
            self._next_ant_id += 1
        # синие неоновые муравьи-стрелки — появляются после 3-й волны
        if self.wave >= C.NEON_ANT_FROM_WAVE:
            ncount = min(C.NEON_ANT_MAX,
                         C.NEON_ANT_BASE + (self.wave - C.NEON_ANT_FROM_WAVE) * C.NEON_ANT_GROWTH)
            now = time.time()
            for _ in range(ncount):
                self.neon_ants[self._next_neon_id] = NeonAnt(self._next_neon_id, now)
                self._next_neon_id += 1
            self.events.append({"t": "event", "kind": "neon_wave",
                                "wave": self.wave, "count": ncount})
        if self.wave % C.BOSS_EVERY == 0:
            self.boss = Boss(time.time())
            self.events.append({"t": "event", "kind": "boss_spawn", "wave": self.wave})
        self.events.append({"t": "event", "kind": "wave", "wave": self.wave, "count": count})
        self._wave_pending = False

    # --- симуляция ---
    def update(self, dt):
        now = time.time()
        self._check_wipe(now)
        self._respawn_dead(now)
        frozen = now < self.freeze_until
        has_players = any(p.hp > 0 for p in self.players.values()) or bool(self.players)

        # менеджер волн (подавлен во время фазы BLACK KING)
        if has_players and not self.black_king:
            if self._wave_pending and now >= self.next_wave_at:
                self._start_wave()
            elif (not self._wave_pending and not self.ants
                  and not self.neon_ants and self.boss is None):
                self._wave_pending = True
                self.next_wave_at = now + C.WAVE_DELAY

        self._update_player_vel(dt)
        # пересчёт flow-поля от живых игроков (общий граф для всех мобов)
        if not frozen and (self.ants or self.boss):
            srcs = [pl.pos for pl in self.players.values() if not pl.dead]
            if srcs:
                self.nav.compute(srcs)
        for ant in self.ants.values():
            ant.update(dt, now, self.players, frozen, self.slit_event_active, self.nav)
        for na in self.neon_ants.values():
            na.update(dt, now, self.players, frozen)
        if not frozen:
            self._neon_ant_shoot(now)
        if self.boss:
            self.boss.update(dt, now, self.players, frozen, self.nav, self.shots)
            if not frozen:
                self._boss_throw(now)
                self._boss_gas(now)
        self._update_boss_shots(dt, now)
        self._update_ant_shots(dt, now)

        # эмоции
        for pl in self.players.values():
            if pl.emote and now >= pl.emote_until:
                pl.emote = None

        self._update_shots(dt, now)
        self._update_bees(dt, now)
        self._collect_drops(now)
        if not frozen:
            self._touch_damage(dt, now)
        self._update_slits(dt, now)   # щели живут независимо от заморозки
        self._update_black_king(dt, now)

    def _update_player_vel(self, dt):
        """Оценить скорость игроков по смещению за тик (для упреждения снарядов босса)."""
        if dt <= 0:
            return
        for pl in self.players.values():
            pl.vel = [(pl.pos[0] - pl._last_pos[0]) / dt,
                      (pl.pos[1] - pl._last_pos[1]) / dt,
                      (pl.pos[2] - pl._last_pos[2]) / dt]
            pl._last_pos = list(pl.pos)

    def _update_shots(self, dt, now):
        dead = []
        for sid, shot in self.shots.items():
            shot.update(dt)
            hit = False
            # тараканы
            for aid, ant in list(self.ants.items()):
                if _dist2(shot.pos, ant.pos) < (C.PROJECTILE_RADIUS + 0.6) ** 2:
                    if shot.kind == C.WEAPON_MAYO:
                        self._mayo_splash(shot.pos, now)
                    else:
                        self._kill_ant(aid, shot.owner, now)
                    hit = True
                    break
            # неоновые муравьи (синие): сироп ранит, майонез замедляет
            if not hit:
                for nid, na in list(self.neon_ants.items()):
                    if _dist2(shot.pos, [na.pos[0], na.pos[1], 0.9]) < (C.PROJECTILE_RADIUS + 0.7) ** 2:
                        if shot.kind == C.WEAPON_MAYO:
                            self._mayo_splash(shot.pos, now)
                        else:
                            self._hurt_neon_ant(nid, shot.owner, now)
                        hit = True
                        break
            # ЩЕЛЬ — наполняется только майонезом
            if not hit and self.slit_event_active and shot.kind == C.WEAPON_MAYO:
                for slit in self.slits.values():
                    if slit.calmed:
                        continue
                    if _dist2(shot.pos, slit.pos) < (C.PROJECTILE_RADIUS + C.SLIT_HIT_RADIUS) ** 2:
                        self._satisfy_slit(slit, now)
                        hit = True
                        break
            # босс — только сироп копит уважение
            if not hit and self.boss and shot.kind == C.WEAPON_SYRUP:
                if _dist2(shot.pos, [self.boss.pos[0], self.boss.pos[1], 1.2]) < 16.0:
                    self._respect_boss(shot.owner, now)
                    hit = True
            # BLACK KING — сироп наносит HP-урон
            if not hit and self.bk_boss and shot.kind == C.WEAPON_SYRUP:
                bk = self.bk_boss
                if bk.flying:
                    # летит высоко — только XY (снаряды не достигают Z=14)
                    d2 = (shot.pos[0]-bk.pos[0])**2 + (shot.pos[1]-bk.pos[1])**2
                else:
                    d2 = _dist2(shot.pos, [bk.pos[0], bk.pos[1], bk.pos[2] + 2.0])
                if d2 < 16.0:
                    self._hurt_bk_boss(C.PROJECTILE_DAMAGE, shot.owner, now)
                    hit = True
            # маленькие копии BLACK KING — 1 капля сиропа убивает (3D-хитбокс)
            if not hit and self.bk_minions and shot.kind == C.WEAPON_SYRUP:
                for mid, m in list(self.bk_minions.items()):
                    cx = m.pos[0]; cy = m.pos[1]; cz = m.pos[2] + 0.6
                    dist2 = ((shot.pos[0]-cx)**2 + (shot.pos[1]-cy)**2
                             + (shot.pos[2]-cz)**2)
                    if dist2 < (C.PROJECTILE_RADIUS + 0.85) ** 2:
                        self._kill_bk_minion(mid, shot.owner, now)
                        hit = True
                        break
            # другие игроки
            if not hit:
                for tid, target in self.players.items():
                    if tid == shot.owner or target.hp <= 0:
                        continue
                    tc = [target.pos[0], target.pos[1], target.pos[2] + C.PLAYER_HEIGHT / 2]
                    if _dist2(shot.pos, tc) < (C.PROJECTILE_RADIUS + 0.7) ** 2:
                        self._hurt(target, C.PROJECTILE_DAMAGE, now, shot.owner)
                        hit = True
                        break
            # снаряд врезался в стену -> разрушается (стрелять сквозь стены нельзя)
            wall = (not hit) and _hits_wall(shot.pos)
            if hit or wall or shot.pos[2] <= 0.0 or now >= shot.die_at:
                if shot.kind == C.WEAPON_MAYO and not hit and not wall and shot.pos[2] <= 0.0:
                    self._mayo_splash(shot.pos, now)  # майонез растекается по земле
                dead.append(sid)
        for sid in dead:
            self.shots.pop(sid, None)

    def _update_bees(self, dt, now):
        dead = []
        targets = list(self.ants.values()) + list(self.neon_ants.values())
        no_targets = not targets
        for bid, bee in self.bees.items():
            bee.update(dt, targets)
            stung = False
            for aid, ant in list(self.ants.items()):
                if _dist2(bee.pos, ant.pos) < 1.0:
                    self._kill_ant(aid, bee.owner, now)
                    stung = True
                    break
            if not stung:
                for nid, na in list(self.neon_ants.items()):
                    if _dist2(bee.pos, na.pos) < 1.0:
                        self._hurt_neon_ant(nid, bee.owner, now)
                        stung = True
                        break
            if no_targets:
                bee.die_at = min(bee.die_at, now + 0.8)
            if stung or now >= bee.die_at:
                dead.append(bid)
        for bid in dead:
            self.bees.pop(bid, None)

    def _mayo_splash(self, pos, now):
        # замедлить всех тараканов и неоновых муравьёв в радиусе
        r2 = C.MAYO_SLOW_RADIUS ** 2
        for ant in self.ants.values():
            if _dist2(pos, ant.pos) < r2:
                ant.slow_until = now + C.MAYO_SLOW_TIME
        for na in self.neon_ants.values():
            if _dist2(pos, na.pos) < r2:
                na.slow_until = now + C.MAYO_SLOW_TIME

    def _kill_ant(self, aid, owner_id, now):
        ant = self.ants.pop(aid, None)
        if not ant:
            return
        owner = self.players.get(owner_id)
        if owner:
            owner.score += 1
            owner.kills_session += 1
        self.events.append({"t": "event", "kind": "ant_killed",
                            "pos": [round(ant.pos[0], 2), round(ant.pos[1], 2)], "by": owner_id})
        # дроп
        if random.random() < C.DROP_CHANCE:
            kind = random.choices(_DROP_KINDS, _DROP_WEIGHTS)[0]
            did = self._next_drop_id
            self._next_drop_id += 1
            self.drops[did] = {"pos": [ant.pos[0], ant.pos[1], 0.0], "kind": kind}

    def _hurt_neon_ant(self, nid, owner_id, now):
        na = self.neon_ants.get(nid)
        if not na:
            return
        na.hp -= 1
        if na.hp > 0:
            return
        self.neon_ants.pop(nid, None)
        owner = self.players.get(owner_id)
        if owner:
            owner.score += 3
            owner.kills_session += 1
        self.events.append({"t": "event", "kind": "neon_ant_killed",
                            "pos": [round(na.pos[0], 2), round(na.pos[1], 2)], "by": owner_id})
        if random.random() < C.DROP_CHANCE:
            kind = random.choices(_DROP_KINDS, _DROP_WEIGHTS)[0]
            did = self._next_drop_id
            self._next_drop_id += 1
            self.drops[did] = {"pos": [na.pos[0], na.pos[1], 0.0], "kind": kind}

    def _neon_ant_shoot(self, now):
        for na in self.neon_ants.values():
            if now < na.shoot_at:
                continue
            target = _nearest_player(self.players, na.pos, C.NEON_ANT_SHOOT_RANGE)
            if not target:
                na.shoot_at = now + 0.6
                continue
            # не стрелять сквозь стену — сначала выйти на игрока (без LOS пропускаем выстрел)
            if line_blocked(na.pos[0], na.pos[1], target.pos[0], target.pos[1], _LOS_RECTS):
                na.shoot_at = now + 0.4
                continue
            na.shoot_at = now + C.NEON_ANT_SHOOT_INTERVAL * random.uniform(0.8, 1.25)
            origin = [na.pos[0], na.pos[1], 1.1]
            tgt = [target.pos[0], target.pos[1], target.pos[2] + C.PLAYER_HEIGHT * 0.5]
            asid = self._next_ant_shot_id
            self._next_ant_shot_id += 1
            self.ant_shots[asid] = AntShot(asid, origin, tgt, now)
            self.events.append({"t": "event", "kind": "neon_shoot",
                                "pos": [round(origin[0], 2), round(origin[1], 2), 1.1]})

    def _update_ant_shots(self, dt, now):
        dead = []
        for asid, sh in self.ant_shots.items():
            sh.update(dt)
            hit = False
            for pl in self.players.values():
                if pl.dead:
                    continue
                tc = [pl.pos[0], pl.pos[1], pl.pos[2] + C.PLAYER_HEIGHT * 0.5]
                if _dist2(sh.pos, tc) < (C.SKIBIDI_RADIUS + 0.7) ** 2:
                    self._hurt(pl, C.SKIBIDI_DAMAGE, now, None)
                    hit = True
                    break
            # зелье гасится о стену (сквозь стены не летает)
            if hit or _hits_wall(sh.pos) or sh.pos[2] <= 0.0 or now >= sh.die_at:
                self.events.append({"t": "event", "kind": "skibidi_hit",
                                    "pos": [round(sh.pos[0], 2), round(sh.pos[1], 2),
                                            max(0.0, round(sh.pos[2], 2))]})
                dead.append(asid)
        for asid in dead:
            self.ant_shots.pop(asid, None)

    def _collect_drops(self, now):
        if not self.drops:
            return
        r2 = C.DROP_PICKUP_RADIUS ** 2
        for did in list(self.drops):
            drop = self.drops[did]
            for pl in self.players.values():
                if pl.dead:
                    continue
                if ((pl.pos[0] - drop["pos"][0]) ** 2 + (pl.pos[1] - drop["pos"][1]) ** 2 < r2
                        and abs(pl.pos[2] - drop["pos"][2]) < 2.5):
                    kind = drop["kind"]
                    if kind == "lit_energy":
                        pl.lit_energy += 1     # НЕ ресурс и не очки — расходник на пчёл
                    elif kind == "cup":
                        pl.cups += 1           # белый стакан — нести к угловому пьедесталу
                    elif kind == "health":
                        pl.hp = min(C.PLAYER_MAX_HP, pl.hp + C.HEALTH_DROP_HEAL)
                    else:
                        pl.score += _DROP_VALUE.get(kind, 1)
                        pl.resources[kind] = pl.resources.get(kind, 0) + 1
                    self.events.append({"t": "event", "kind": "pickup",
                                        "drop": kind, "by": pl.name})
                    del self.drops[did]
                    break

    def _boss_throw(self, now):
        interval = C.BOSS_THROW_INTERVAL_P2 if self.boss.phase == 2 else C.BOSS_THROW_INTERVAL
        if now < self.boss.throw_at:
            return
        target = _nearest_player(self.players, self.boss.pos, 9999)
        if not target:
            self.boss.throw_at = now + interval
            return
        # не бросать сквозь стену — ждём прямой видимости (босс к ней подходит по пути)
        if line_blocked(self.boss.pos[0], self.boss.pos[1],
                        target.pos[0], target.pos[1], _LOS_RECTS):
            self.boss.throw_at = now + 0.5
            return
        self.boss.throw_at = now + interval
        origin = [self.boss.pos[0], self.boss.pos[1], 2.5]
        bsid = self._next_boss_shot_id
        self._next_boss_shot_id += 1
        self.boss_shots[bsid] = BossShot(bsid, origin, target.pos, target.vel, now)
        self.events.append({"t": "event", "kind": "boss_throw",
                            "pos": [round(origin[0], 2), round(origin[1], 2), 2.5]})

    def _boss_gas(self, now):
        """Фаза 2: пульс ГАЗА — замедляет игроков в радиусе вокруг босса."""
        if self.boss.phase != 2 or now < self.boss.gas_at:
            return
        self.boss.gas_at = now + C.BOSS_GAS_INTERVAL
        bx, by = self.boss.pos[0], self.boss.pos[1]
        r2 = C.BOSS_GAS_RADIUS ** 2
        for pl in self.players.values():
            if pl.dead:
                continue
            if (pl.pos[0] - bx) ** 2 + (pl.pos[1] - by) ** 2 < r2:
                pl.move_slow_until = now + C.BOSS_GAS_SLOW_TIME
        self.events.append({"t": "event", "kind": "boss_gas",
                            "pos": [round(bx, 2), round(by, 2)],
                            "radius": C.BOSS_GAS_RADIUS})

    def _update_boss_shots(self, dt, now):
        dead = []
        for bsid, sh in self.boss_shots.items():
            sh.update(dt)
            # детонация: земля / таймаут / рядом с живым игроком
            hit_player = any(
                (not pl.dead) and (pl.pos[0] - sh.pos[0]) ** 2
                + (pl.pos[1] - sh.pos[1]) ** 2 < 4.0 and sh.pos[2] < 3.0
                for pl in self.players.values())
            if sh.pos[2] <= 0.0 or now >= sh.die_at or hit_player or _hits_wall(sh.pos):
                self._boss_explode(sh.pos, now)
                dead.append(bsid)
        for bsid in dead:
            self.boss_shots.pop(bsid, None)

    def _boss_explode(self, pos, now):
        self.events.append({"t": "event", "kind": "boss_explode",
                            "pos": [round(pos[0], 2), round(pos[1], 2), max(0.0, round(pos[2], 2))]})
        r = C.BOSS_EXPLOSION_RADIUS
        for pl in self.players.values():
            if pl.dead:
                continue
            d = math.hypot(pl.pos[0] - pos[0], pl.pos[1] - pos[1])
            if d < r:
                dmg = C.BOSS_EXPLOSION_DAMAGE * (1.0 - d / r)   # спад к краю
                self._hurt(pl, dmg, now, None)
                # отброс игрока считает клиент (по событию boss_explode) — он
                # авторитетен над своей позицией; сервер бьёт уроном.
        # отброс мобов (тараканы/неоновые) из эпицентра
        for mob in list(self.ants.values()) + list(self.neon_ants.values()):
            d = math.hypot(mob.pos[0] - pos[0], mob.pos[1] - pos[1])
            if d < r:
                f = C.BOSS_KNOCKBACK * (1.0 - d / r)
                ux = (mob.pos[0] - pos[0]) / (d or 1.0)
                uy = (mob.pos[1] - pos[1]) / (d or 1.0)
                mob.pos[0] += ux * f * 0.25
                mob.pos[1] += uy * f * 0.25
                mob.pos[0], mob.pos[1] = _clamp_to_arena(mob.pos[0], mob.pos[1])
                if hasattr(mob, "vz"):
                    mob.vz = max(mob.vz, f * 0.8)   # подкинуть вверх (только у тараканов)

    def _respect_boss(self, owner_id, now):
        if not self.boss:
            return
        self.boss.respect += C.BOSS_RESPECT_PER_HIT
        if self.boss.respect >= C.BOSS_RESPECT_MAX:
            owner = self.players.get(owner_id)
            for pl in self.players.values():
                pl.score += 20            # «много ресурсов» всем
            # дроп белого пластикового стакана на месте босса
            did = self._next_drop_id
            self._next_drop_id += 1
            self.drops[did] = {"pos": [self.boss.pos[0], self.boss.pos[1], 0.0], "kind": "cup"}
            self.events.append({"t": "event", "kind": "boss_defeated",
                                "by": owner.name if owner else "?"})
            self.boss = None

    # --- ЩЕЛЬ (настенный враг) ---
    def _spawn_slits(self, now):
        """Появление щелей: столько же, сколько игроков, одновременно в разных
        местах на стенах, на уровне игрока (половина роста)."""
        n = min(len(self.players), len(_SLIT_POINTS))
        if n <= 0:
            return
        pts = random.sample(_SLIT_POINTS, n)
        self.slits = {}
        z = C.PLAYER_HEIGHT * 0.5
        for (x, y, nx, ny) in pts:
            sid = self._next_slit_id
            self._next_slit_id += 1
            self.slits[sid] = Slit(sid, [x, y, z], [nx, ny])
        self.slit_event_active = True
        self.slit_deadline = now + C.SLIT_TIME_LIMIT
        self.events.append({"t": "event", "kind": "slit_spawn",
                            "count": n, "time": C.SLIT_TIME_LIMIT})

    def _satisfy_slit(self, slit, now):
        """Капля майонеза попала в щель — наполняем шкалу удовлетворённости."""
        if slit.calmed:
            return
        slit.progress = min(1.0, slit.progress + C.SLIT_MAYO_GAIN)
        if slit.progress >= 1.0:
            slit.calmed = True
            self.events.append({"t": "event", "kind": "slit_calmed",
                                "pos": [round(slit.pos[0], 2),
                                        round(slit.pos[1], 2),
                                        round(slit.pos[2], 2)]})

    def _update_slits(self, dt, now):
        if self.black_king:   # во время BLACK KING щели не появляются
            return
        # менеджер появления события
        if (self.players and not self.slit_event_active
                and now >= self.next_slit_at):
            self._spawn_slits(now)
        if not self.slit_event_active:
            return
        # все повержены (наполнены майонезом) -> победа
        if self.slits and all(s.calmed for s in self.slits.values()):
            self._scatter_ants()          # раскидать ржущих тараканов подальше
            self._end_slit_event(now)
            self.events.append({"t": "event", "kind": "slit_defeated"})
            return
        # время вышло -> все умирают
        if now >= self.slit_deadline:
            for pl in self.players.values():
                if not pl.dead:
                    self._hurt(pl, C.PLAYER_MAX_HP * 2, now, None)
            self._end_slit_event(now)
            self.events.append({"t": "event", "kind": "slit_failed"})

    def _scatter_ants(self):
        """После победы над щелью — разбросать тараканов далеко от игроков (взрыв радости)."""
        for ant in self.ants.values():
            target = _nearest_player(self.players, ant.pos, 9999)
            if target:
                dx, dy = ant.pos[0] - target.pos[0], ant.pos[1] - target.pos[1]
                n = math.hypot(dx, dy) or 1.0
                ux, uy = dx / n, dy / n
            else:
                ang = random.uniform(0, 2 * math.pi)
                ux, uy = math.cos(ang), math.sin(ang)
            push = C.ANT_SCATTER_DIST * random.uniform(0.7, 1.2)
            # не закинуть внутрь стены: уменьшаем бросок, пока точка не станет свободной
            for _ in range(6):
                tx = ant.pos[0] + ux * push
                ty = ant.pos[1] + uy * push
                tx, ty = _clamp_to_arena(tx, ty)
                if not in_any_building(tx, ty, _BUILDING_RECTS):
                    ant.pos[0], ant.pos[1] = tx, ty
                    break
                push *= 0.6
            ant.vz = random.uniform(16.0, 24.0)   # подбросить вверх

    def _end_slit_event(self, now):
        self.slits = {}
        self.slit_event_active = False
        self.next_slit_at = now + random.uniform(*C.SLIT_INTERVAL)

    def _touch_damage(self, dt, now):
        for pl in self.players.values():
            if pl.hp <= 0 or now < pl.touch_inv_until:
                continue                      # короткий кулдаун на урон от касаний
            touch_dmg = 0
            # во время ЩЕЛИ тараканы не кусают — они просто ржут над игроком
            if not self.slit_event_active:
                for ant in self.ants.values():
                    if _dist2(pl.pos, ant.pos) < C.ANT_TOUCH_RANGE ** 2:
                        touch_dmg = max(touch_dmg, C.ANT_TOUCH_DAMAGE)
                        break
            if not touch_dmg:
                for na in self.neon_ants.values():
                    if _dist2(pl.pos, na.pos) < C.ANT_TOUCH_RANGE ** 2:
                        touch_dmg = max(touch_dmg, C.ANT_TOUCH_DAMAGE)
                        break
            if self.boss and _dist2(pl.pos, self.boss.pos) < (C.ANT_TOUCH_RANGE + 1.5) ** 2:
                touch_dmg = max(touch_dmg, C.ANT_TOUCH_DAMAGE)
            if self.bk_boss and _dist2(pl.pos, self.bk_boss.pos) < (C.ANT_TOUCH_RANGE + 1.5) ** 2:
                touch_dmg = max(touch_dmg, C.BLACK_KING_TOUCH_DAMAGE)
            if not touch_dmg:
                for m in self.bk_minions.values():
                    if _dist2(pl.pos, m.pos) < C.ANT_TOUCH_RANGE ** 2:
                        touch_dmg = max(touch_dmg, C.BLACK_KING_MINION_TOUCH_DAMAGE)
                        break
            if touch_dmg:
                pl.touch_inv_until = now + C.ANT_TOUCH_CD
                self._hurt(pl, touch_dmg, now, None)

    def _hurt(self, target, dmg, now, attacker_id):
        if target.dead:
            return
        target.hp -= dmg
        atk = self.players.get(attacker_id) if attacker_id is not None else None
        if atk and atk is not target:
            atk.score += 1
        if target.hp <= 0:
            target.hp = 0
            target.dead = True                       # настоящая смерть
            target.respawn_at = now + 3.0
            target.deaths += 1
            if atk and atk is not target:
                atk.score += 5
                self.events.append({"t": "event", "kind": "splash",
                                    "victim": target.name, "by": atk.name})
            else:
                self.events.append({"t": "event", "kind": "death",
                                    "victim": target.name})

    def _respawn_dead(self, now):
        for pl in self.players.values():
            if pl.dead and now >= pl.respawn_at:
                pl.dead = False
                pl.hp = C.PLAYER_MAX_HP
                # респавн рядом с центральной статуей (витрина у (0,0))
                pl.pos = [random.uniform(-3, 3), random.uniform(4, 8), 0.0]

    def _check_wipe(self, now):
        """Если ВСЕ игроки мертвы:
        - обычная фаза: сброс до волны 1.
        - фаза BLACK KING: завершить BK-фазу, вернуть волну которая была до призыва."""
        if not self.players:
            self._all_dead = False
            return
        all_dead = all(pl.dead for pl in self.players.values())
        if all_dead and not self._all_dead:
            # очистить обычных врагов всегда
            self.ants.clear()
            self.neon_ants.clear()
            self.ant_shots.clear()
            self.shots.clear()
            self.bees.clear()
            self.boss_shots.clear()
            self.boss = None
            self.slits = {}
            self.slit_event_active = False

            # сброс инвентарей всех игроков при любом вайпе
            for _pl in self.players.values():
                _pl.lit_energy = 0
                _pl.cups = 0
            # очистить предметы на земле
            self.drops.clear()
            # сбросить установленные стойки
            self.cup_spots = [False] * len(CUP_SPOTS)

            if self.black_king:
                # погружение: собрать позиции BK и миньонов для анимации
                bk_pos = ([round(self.bk_boss.pos[0], 2), round(self.bk_boss.pos[1], 2)]
                           if self.bk_boss else [0.0, 38.0])
                minion_poss = [[round(m.pos[0], 2), round(m.pos[1], 2), round(m.pos[2], 2)]
                               for m in self.bk_minions.values()]
                self.events.append({"t": "event", "kind": "bk_wipe",
                                    "bk_pos": bk_pos, "minion_positions": minion_poss})
                # завершить BK-фазу полностью
                self.bk_boss = None
                self.bk_minions.clear()
                self.bk_shots.clear()
                self.bk_living_cups.clear()
                self.bk_cup_shots.clear()
                self.black_king = False
                # восстановить волну до той что была перед призывом
                self.wave = max(0, self._pre_bk_wave - 1)
                self._wave_pending = True
                self.next_wave_at = now + 10.0  # кат-сцена wipe + вспышка + пауза
                self.next_slit_at = now + random.uniform(*C.SLIT_INTERVAL)
            else:
                self.bk_minions.clear()
                self.bk_shots.clear()
                self.bk_cup_shots.clear()
                self.wave = 0
                self._wave_pending = True
                self.next_wave_at = now + C.WAVE_DELAY
                self.next_slit_at = now + random.uniform(*C.SLIT_INTERVAL)
                self.events.append({"t": "event", "kind": "wipe"})
        self._all_dead = all_dead

    # --- снапшот ---
    def snapshot(self):
        return {
            "t": "snapshot",
            "players": {str(pid): pl.snapshot() for pid, pl in self.players.items()},
            "ants": [a.snapshot() for a in self.ants.values()],
            "neon_ants": [n.snapshot() for n in self.neon_ants.values()],
            "ant_shots": [s.snapshot() for s in self.ant_shots.values()],
            "shots": [s.snapshot() for s in self.shots.values()],
            "bees": [b.snapshot() for b in self.bees.values()],
            "drops": [[did, round(d["pos"][0], 2), round(d["pos"][1], 2), d["kind"]]
                      for did, d in self.drops.items()],
            "bshots": [s.snapshot() for s in self.boss_shots.values()],
            "boss": self.boss.snapshot() if self.boss else None,
            "slits": [s.snapshot() for s in self.slits.values()],
            "slit_time": (round(max(0.0, self.slit_deadline - time.time()), 1)
                          if self.slit_event_active else 0.0),
            "wave": self.wave,
            "alive": len(self.ants),
            "neon": len(self.neon_ants),
            "cup_spots": list(self.cup_spots),
            "black_king": self.black_king,
            "bk_boss": self.bk_boss.snapshot() if self.bk_boss else None,
            "bk_minions": [m.snapshot() for m in self.bk_minions.values()],
            "bk_shots": [s.snapshot() for s in self.bk_shots.values()],
            "bk_living_cups": [c.snapshot() for c in self.bk_living_cups.values()],
            "bk_cup_shots": [s.snapshot() for s in self.bk_cup_shots.values()],
        }

    # --- BLACK KING ---
    def _update_black_king(self, dt, now):
        if not self.bk_boss:
            return
        self.bk_boss.update(dt, now, self.players)

        # переход в фазу 2 при 50% HP
        if (self.bk_boss.phase == 1
                and self.bk_boss.hp <= int(C.BLACK_KING_HP * C.BLACK_KING_PHASE2_FRAC)):
            self.bk_boss.phase = 2
            self.bk_boss.shoot_at = now + 0.5
            for i, (sx, sy) in enumerate(CUP_SPOTS):
                self.bk_living_cups[i] = BKLivingCup(i, (sx, sy), now)
            self.events.append({"t": "event", "kind": "bk_phase2"})

        # спавн копий (в фазе 2 — в 2 раза больше за раз)
        if (now >= self.bk_boss.spawn_minion_at
                and len(self.bk_minions) < C.BLACK_KING_MINION_MAX):
            per_spawn = 3 if self.bk_boss.phase == 2 else 2
            count = min(per_spawn, C.BLACK_KING_MINION_MAX - len(self.bk_minions))
            for _ in range(count):
                mid = self._next_bk_minion_id
                self._next_bk_minion_id += 1
                # ищем свободную точку рядом с боссом без стен
                ox, oy = self.nav.random_free_point()
                for _attempt in range(30):
                    cx = self.bk_boss.pos[0] + random.uniform(-8, 8)
                    cy = self.bk_boss.pos[1] + random.uniform(-8, 8)
                    cx, cy = _clamp_to_arena(cx, cy)
                    if not in_any_building(cx, cy, _BUILDING_RECTS):
                        ox, oy = cx, cy
                        break
                self.bk_minions[mid] = BlackKingMinion(mid, (ox, oy))
            self.bk_boss.spawn_minion_at = now + C.BLACK_KING_MINION_SPAWN_INTERVAL
            self.events.append({"t": "event", "kind": "bk_minion_spawn", "count": count})

        # случайные звуки
        if now >= self._bk_voice_at:
            self._bk_voice_at = now + random.uniform(*C.BLACK_KING_VOICE_INTERVAL)
            self.events.append({"t": "event", "kind": "bk_voice"})

        # обновить копии и боевые системы фазы 2
        for m in self.bk_minions.values():
            m.update(dt, now, self.players)
        if self.bk_boss.phase == 2:
            self._bk_shoot(now)
            self._update_bk_cups(dt, now)
        self._update_bk_shots(dt, now)

    def _bk_shoot(self, now):
        """BLACK KING стреляет фиолетовым лазером (фаза 2)."""
        if not self.bk_boss or now < self.bk_boss.shoot_at:
            return

        origin = [self.bk_boss.pos[0], self.bk_boss.pos[1],
                  self.bk_boss.pos[2] + 2.5]
        ev_pos = [round(origin[0], 2), round(origin[1], 2), round(origin[2], 2)]

        if self.bk_boss.flying:
            # режим полёта: горизонтальная очередь по кругу, параллельно полу
            # origin и target на одной высоте → vel[2]=0 → строго горизонтально
            self.bk_boss.shoot_at = now + C.BK_RAPID_FIRE_INTERVAL
            base_angle = math.radians(self.bk_boss.h)
            shot_z = LEVEL2_Z + C.PLAYER_HEIGHT * 0.5  # уровень игрока на 2-м этаже
            fly_origin = [self.bk_boss.pos[0], self.bk_boss.pos[1], shot_z]
            for i in range(C.BK_RAPID_FIRE_DIRS):
                angle = base_angle + 2 * math.pi * i / C.BK_RAPID_FIRE_DIRS
                tpos = [fly_origin[0] + math.cos(angle) * 25,
                        fly_origin[1] + math.sin(angle) * 25,
                        shot_z]  # same Z → горизонтальный полёт без гравитации
                bksid = self._next_bk_shot_id
                self._next_bk_shot_id += 1
                self.bk_shots[bksid] = BKShot(bksid, fly_origin, tpos, now, grav=0.0)
        else:
            # наземный режим: прицельный выстрел в ближайшего
            self.bk_boss.shoot_at = now + C.BK_SHOOT_INTERVAL
            target = _nearest_player(self.players, self.bk_boss.pos, 9999)
            if not target:
                return
            tpos = [target.pos[0], target.pos[1],
                    target.pos[2] + C.PLAYER_HEIGHT * 0.5]
            bksid = self._next_bk_shot_id
            self._next_bk_shot_id += 1
            self.bk_shots[bksid] = BKShot(bksid, origin, tpos, now)

        self.events.append({"t": "event", "kind": "bk_shoot", "pos": ev_pos})

    def _update_bk_shots(self, dt, now):
        """Обновить фиолетовые лазеры BLACK KING."""
        dead = []
        for bksid, sh in self.bk_shots.items():
            sh.update(dt)
            hit = False
            for pl in self.players.values():
                if pl.dead:
                    continue
                # XY-цилиндр: летящие снаряды на Z=12.9 должны попадать и в игроков на земле
                d2_xy = (sh.pos[0]-pl.pos[0])**2 + (sh.pos[1]-pl.pos[1])**2
                if d2_xy < 1.44:   # XY-радиус ~1.2
                    self._hurt(pl, C.BK_SHOT_DAMAGE, now, None)
                    self.events.append({"t": "event", "kind": "bk_shot_hit",
                                        "pos": [round(sh.pos[0], 2), round(sh.pos[1], 2),
                                                max(0.0, round(sh.pos[2], 2))]})
                    hit = True
                    break
            if hit or _hits_wall(sh.pos) or sh.pos[2] <= 0.0 or now >= sh.die_at:
                dead.append(bksid)
        for bksid in dead:
            self.bk_shots.pop(bksid, None)

    def _update_bk_cups(self, dt, now):
        """Ожившие стаканы: ползут к игроку, стреляют замедляющими снарядами, роняют аптечки."""
        for cup in self.bk_living_cups.values():
            # движение к ближайшему игроку
            target = _nearest_player(self.players, cup.pos, 9999)
            if target:
                dx = target.pos[0] - cup.pos[0]
                dy = target.pos[1] - cup.pos[1]
                d = math.hypot(dx, dy)
                if d > 1.0:
                    cup.dir = [dx / d, dy / d]
                    step = C.BK_CUP_SPEED * dt
                    nx = cup.pos[0] + cup.dir[0] * step
                    ny = cup.pos[1] + cup.dir[1] * step
                    if not in_any_building(nx, ny, _BUILDING_RECTS):
                        cup.pos[0], cup.pos[1] = nx, ny
                    elif not in_any_building(nx, cup.pos[1], _BUILDING_RECTS):
                        cup.pos[0] = nx
                    elif not in_any_building(cup.pos[0], ny, _BUILDING_RECTS):
                        cup.pos[1] = ny
                    cup.pos[0], cup.pos[1] = _clamp_to_arena(cup.pos[0], cup.pos[1])
            if now >= cup.shoot_at:
                cup.shoot_at = now + C.BK_CUP_SHOOT_INTERVAL * random.uniform(0.7, 1.3)
                target = _nearest_player(self.players, cup.pos, 9999)
                if target:
                    origin = [cup.pos[0], cup.pos[1], 1.5]
                    tpos = [target.pos[0], target.pos[1], target.pos[2] + C.PLAYER_HEIGHT * 0.5]
                    csid = self._next_bk_cup_shot_id
                    self._next_bk_cup_shot_id += 1
                    self.bk_cup_shots[csid] = BKCupShot(csid, origin, tpos, now)
                    self.events.append({"t": "event", "kind": "bk_cup_shoot",
                                        "pos": [round(cup.pos[0], 2), round(cup.pos[1], 2), 1.5]})
            if now >= cup.drop_at:
                cup.drop_at = now + C.BK_CUP_HEALTH_DROP_INTERVAL
                did = self._next_drop_id
                self._next_drop_id += 1
                off = random.uniform(-4, 4)
                self.drops[did] = {"pos": [cup.pos[0] + off, cup.pos[1] + off, 0.0], "kind": "health"}
        # обновить снаряды стаканов
        dead = []
        for csid, sh in self.bk_cup_shots.items():
            sh.update(dt)
            hit = False
            for pl in self.players.values():
                if pl.dead:
                    continue
                tc = [pl.pos[0], pl.pos[1], pl.pos[2] + C.PLAYER_HEIGHT * 0.5]
                if _dist2(sh.pos, tc) < 1.44:
                    pl.move_slow_until = max(pl.move_slow_until, now + C.BK_CUP_SLOW_TIME)
                    self.events.append({"t": "event", "kind": "bk_cup_hit",
                                        "pos": [round(sh.pos[0], 2), round(sh.pos[1], 2),
                                                max(0.0, round(sh.pos[2], 2))]})
                    hit = True
                    break
            if hit or _hits_wall(sh.pos) or sh.pos[2] <= 0.0 or now >= sh.die_at:
                dead.append(csid)
        for csid in dead:
            self.bk_cup_shots.pop(csid, None)

    def _hurt_bk_boss(self, dmg, owner_id, now):
        if not self.bk_boss:
            return
        self.bk_boss.hp = max(0, self.bk_boss.hp - dmg)
        if self.bk_boss.hp <= 0:
            owner = self.players.get(owner_id)
            for pl in self.players.values():
                pl.score += 50
            death_pos = [round(self.bk_boss.pos[0], 2), round(self.bk_boss.pos[1], 2)]
            self.events.append({"t": "event", "kind": "bk_defeated",
                                "by": owner.name if owner else "?",
                                "pos": death_pos})
            self.bk_boss = None
            self.bk_minions.clear()
            self.bk_shots.clear()
            self.bk_living_cups.clear()
            self.bk_cup_shots.clear()
            self.black_king = False
            self.cup_spots = [False] * len(CUP_SPOTS)
            # волна стартует после кат-сцены (5с) + вспышки (2.5с) + пауза (2.5с) = 10с
            self._wave_pending = True
            self.next_wave_at = now + 10.0
            # щели не спавнятся во время кат-сцены смерти + запас
            self.next_slit_at = now + 20.0

    def _kill_bk_minion(self, mid, owner_id, now):
        m = self.bk_minions.pop(mid, None)
        if not m:
            return
        owner = self.players.get(owner_id)
        if owner:
            owner.score += 2
            owner.kills_session += 1
        self.events.append({"t": "event", "kind": "bk_minion_killed",
                            "pos": [round(m.pos[0], 2), round(m.pos[1], 2)]})
        # аптечка: редко (5%) — миньонов много, частые дропы ломали баланс
        if random.random() < 0.05:
            did = self._next_drop_id
            self._next_drop_id += 1
            self.drops[did] = {"pos": [m.pos[0], m.pos[1], 0.0], "kind": "health"}

    def drain_events(self):
        ev = self.events
        self.events = []
        return ev
