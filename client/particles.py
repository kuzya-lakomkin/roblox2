"""Лёгкая система партиклов: маленькие кубики с гравитацией, разлётом и угасанием.

Своя реализация (без тяжёлого ParticleEffect) — полный контроль и предсказуемость.
"""

import random

from panda3d.core import TransparencyAttrib, Vec3

from client.primitives import make_box

_MAX = 320  # потолок одновременных частиц (защита производительности)


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
    def __init__(self, parent):
        self.parent = parent
        self.parts = []

    def burst(self, pos, count=8, color=(1, 1, 1, 1), speed=4.0,
              size=0.22, life=0.6, grav=-9.0, spread=1.0, up=1.0):
        """Разлёт частиц из точки pos."""
        if len(self.parts) > _MAX:
            return
        for _ in range(count):
            node = make_box(1, 1, 1, color)
            node.setScale(size)
            node.setPos(pos[0], pos[1], pos[2])
            node.setLightOff(1)
            node.setTransparency(TransparencyAttrib.MAlpha)
            node.reparentTo(self.parent)
            vel = Vec3(random.uniform(-1, 1) * speed * spread,
                       random.uniform(-1, 1) * speed * spread,
                       random.uniform(0.2, 1.0) * speed * up)
            self.parts.append(_P(node, vel, life * random.uniform(0.7, 1.2),
                                 size, color, grav))

    def update(self, dt):
        alive = []
        for p in self.parts:
            p.age += dt
            if p.age >= p.life:
                p.np.removeNode()
                continue
            p.vel.z += p.grav * dt
            p.np.setPos(p.np.getPos() + p.vel * dt)
            t = p.age / p.life
            s = p.size * (1.0 - 0.6 * t)
            p.np.setScale(max(0.02, s))
            p.np.setColorScale(1, 1, 1, 1.0 - t)   # плавное угасание
            alive.append(p)
        self.parts = alive

    def clear(self):
        for p in self.parts:
            p.np.removeNode()
        self.parts = []
