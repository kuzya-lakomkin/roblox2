"""Навигационная сетка и поле потока (flow field) для тараканов и босса.

Арена дискретизируется в сетку клеток; клетки внутри стен помечаются непроходимыми.
Многоисточниковый BFS от всех живых игроков заполняет для каждой клетки расстояние до
ближайшего игрока (графовый алгоритм поиска по графу клеток). Мобы читают градиент поля и
идут к ближайшему игроку, аккуратно ОБХОДЯ стены. Поле общее для всех мобов — считается
один раз за тик. Чистый Python, без Panda3D (импортируется и на сервере).
"""

import math
import random
from collections import deque

from common import config as C
from common.citydata import building_rects, in_any_building


class NavGrid:
    def __init__(self, cell=2.0, pad=0.9):
        self.cell = cell
        self.size = C.WORLD_SIZE
        self.cols = int(2 * self.size / cell) + 1
        rects = building_rects(pad=pad)
        self.blocked = []
        self.free_points = []     # центры проходимых клеток (для спавна на поверхности)
        for j in range(self.cols):
            row = []
            for i in range(self.cols):
                x, y = self.cell_center(i, j)
                b = in_any_building(x, y, rects)
                row.append(b)
                if not b and abs(x) < self.size - 1.0 and abs(y) < self.size - 1.0:
                    self.free_points.append((x, y))
            self.blocked.append(row)
        self.dist = None

    def cell_center(self, i, j):
        return (-self.size + (i + 0.5) * self.cell,
                -self.size + (j + 0.5) * self.cell)

    def to_cell(self, x, y):
        i = int((x + self.size) / self.cell)
        j = int((y + self.size) / self.cell)
        i = max(0, min(self.cols - 1, i))
        j = max(0, min(self.cols - 1, j))
        return i, j

    def _nearest_free_cell(self, i, j):
        """Ближайшая проходимая клетка (если игрок стоит над стеной/на платформе)."""
        if not self.blocked[j][i]:
            return i, j
        for r in range(1, self.cols):
            for di in range(-r, r + 1):
                for nj in (j - r, j + r):
                    ni = i + di
                    if 0 <= ni < self.cols and 0 <= nj < self.cols and not self.blocked[nj][ni]:
                        return ni, nj
            for dj in range(-r + 1, r):
                for ni in (i - r, i + r):
                    nj = j + dj
                    if 0 <= ni < self.cols and 0 <= nj < self.cols and not self.blocked[nj][ni]:
                        return ni, nj
        return i, j

    def compute(self, sources):
        """Пересчитать поле расстояний от источников (позиции игроков)."""
        cols = self.cols
        INF = 1 << 30
        dist = [[INF] * cols for _ in range(cols)]
        blocked = self.blocked
        q = deque()
        for s in sources:
            i, j = self._nearest_free_cell(*self.to_cell(s[0], s[1]))
            if dist[j][i] != 0:
                dist[j][i] = 0
                q.append((i, j))
        while q:
            i, j = q.popleft()
            d = dist[j][i] + 1
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                if 0 <= ni < cols and 0 <= nj < cols and not blocked[nj][ni] and dist[nj][ni] > d:
                    dist[nj][ni] = d
                    q.append((ni, nj))
        self.dist = dist

    def direction(self, x, y):
        """Единичный вектор к ближайшему игроку по градиенту поля (обходя стены) или None."""
        if not self.dist:
            return None
        cols = self.cols
        i, j = self.to_cell(x, y)
        bestd = self.dist[j][i]
        best = None
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                ni, nj = i + di, j + dj
                if not (0 <= ni < cols and 0 <= nj < cols) or self.blocked[nj][ni]:
                    continue
                # не срезать угол по диагонали сквозь стену
                if di != 0 and dj != 0 and (self.blocked[j][i + di] or self.blocked[j + dj][i]):
                    continue
                d = self.dist[nj][ni]
                if d < bestd:
                    bestd = d
                    best = (ni, nj)
        if best is None:
            return None
        cx, cy = self.cell_center(*best)
        dx, dy = cx - x, cy - y
        n = math.hypot(dx, dy) or 1.0
        return (dx / n, dy / n)

    def random_free_point(self):
        if self.free_points:
            return random.choice(self.free_points)
        return (0.0, 0.0)
