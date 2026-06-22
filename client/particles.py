"""Лёгкая система партиклов: маленькие кубики с гравитацией, разлётом и угасанием.

Своя реализация (без тяжёлого ParticleEffect) — полный контроль и предсказуемость.
Пул предварительно созданных нод — не пересоздаём геометрию на каждый бёрст.
"""

import random

from panda3d.core import TransparencyAttrib, Vec3

from client.primitives import make_box

_MAX = 150   # потолок одновременных частиц (переопределяется через ParticleSystem)
_POOL = 150  # размер пула белых боксов (переопределяется через ParticleSystem)


class _P:
    __slots__ = ("np", "vel", "age", "life", "size", "col", "grav")

    def __init__(self, np, vel, life, size, col, grav):
        self.np = np
        self.vel = vel
        self.age = 0.0
        self.life = life
        self.size = size
        self.col = col
        self.grav = grav


class ParticleSystem:
    def __init__(self, parent, max_particles=_MAX):
        self.parent = parent
        self.parts = []
        self._pool = []
        self._max = max_particles
        # pre-allocate pool: белые боксы, стэшированные до использования
        for _ in range(max_particles):
            node = make_box(1, 1, 1, (1, 1, 1, 1))
            node.setLightOff(1)
            node.setTransparency(TransparencyAttrib.MAlpha)
            node.reparentTo(parent)
            node.stash()
            self._pool.append(node)

    def _acquire(self, color):
        if self._pool:
            node = self._pool.pop()
            node.unstash()
        else:
            node = make_box(1, 1, 1, (1, 1, 1, 1))
            node.setLightOff(1)
            node.setTransparency(TransparencyAttrib.MAlpha)
            node.reparentTo(self.parent)
        node.setColorScale(color[0], color[1], color[2], 1.0)
        return node

    def _release(self, node):
        node.stash()
        self._pool.append(node)

    def burst(self, pos, count=8, color=(1, 1, 1, 1), speed=4.0,
              size=0.22, life=0.6, grav=-9.0, spread=1.0, up=1.0,
              vel_add=None):
        """Разлёт частиц из точки pos."""
        if len(self.parts) >= self._max:
            return
        avail = self._max - len(self.parts)
        count = min(count, avail)
        for _ in range(count):
            node = self._acquire(color)
            node.setScale(size)
            node.setPos(pos[0], pos[1], pos[2])
            vel = Vec3(random.uniform(-1, 1) * speed * spread,
                       random.uniform(-1, 1) * speed * spread,
                       random.uniform(0.2, 1.0) * speed * up)
            if vel_add:
                vel.x += vel_add[0]; vel.y += vel_add[1]; vel.z += vel_add[2]
            self.parts.append(_P(node, vel, life * random.uniform(0.7, 1.2),
                                 size, color, grav))

    def update(self, dt):
        alive = []
        for p in self.parts:
            p.age += dt
            if p.age >= p.life:
                self._release(p.np)
                continue
            p.vel.z += p.grav * dt
            p.np.setPos(p.np.getPos() + p.vel * dt)
            t = p.age / p.life
            s = p.size * (1.0 - 0.6 * t)
            p.np.setScale(max(0.02, s))
            p.np.setColorScale(p.col[0], p.col[1], p.col[2], 1.0 - t)
            alive.append(p)
        self.parts = alive

    def clear(self):
        for p in self.parts:
            self._release(p.np)
        self.parts = []
