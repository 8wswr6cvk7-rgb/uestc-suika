"""芯片进化局：与 index.html 对应的独立 Pygame 版本。"""
from __future__ import annotations

from array import array
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import random

import pygame


ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT = 1060, 760
BOARD_X, BOARD_Y = 300, 92
BOARD_W, BOARD_H = 460, 630
LEFT, RIGHT, FLOOR, DANGER = 20, 440, 608, 135
STEP = 1 / 120
GRAVITY = 1450
DROP_DELAY = 0.42
NAMES = ('', '电子', '空穴', 'PN 结', '二极管', 'MOS 管', '集成电路', '格拉斯哥', '电子科大')
RADII = (0, 19, 27, 37, 49, 63, 79, 98, 119)
AXIS_SCALE = (1, 1, 1.30, 1, 1.35, 1, 1.25, 0.88, 1)
RX = tuple(r * scale for r, scale in zip(RADII, AXIS_SCALE))
RY = tuple(r / scale for r, scale in zip(RADII, AXIS_SCALE))
ELLIPSE_SEGMENTS = 20
SOLVER_PASSES = 4
COLORS = (
    (0, 0, 0), (118, 220, 246), (255, 203, 129), (247, 140, 170),
    (169, 186, 255), (155, 233, 186), (125, 203, 238),
    (245, 194, 109), (255, 158, 114),
)
BG = (11, 19, 38)
TEXT = (246, 247, 252)
MUTED = (153, 169, 199)
CYAN = (114, 222, 244)
ORANGE = (255, 173, 101)
RED = (255, 114, 136)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def read_best(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return max(0, int(data.get('highscore', 0)))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def save_best(path: Path, value: int) -> None:
    try:
        path.write_text(json.dumps({'highscore': value}, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


@dataclass(eq=False)
class Ball:
    level: int
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    age: float = 0.0
    angle: float = 0.0
    spin: float = 0.0
    squash: float = 0.0
    pop: float = 0.0
    last_impact: float = -10.0
    _geometry_key: tuple | None = field(default=None, init=False, repr=False)
    _geometry_value: tuple = field(default=(), init=False, repr=False)

    @property
    def r(self) -> int:
        return RADII[self.level]

    @property
    def rx(self) -> float:
        return RX[self.level]

    @property
    def ry(self) -> float:
        return RY[self.level]

    @property
    def is_circle(self) -> bool:
        return AXIS_SCALE[self.level] == 1

    @property
    def mass(self) -> float:
        return self.rx * self.ry

    @property
    def inertia(self) -> float:
        return self.mass * (self.rx * self.rx + self.ry * self.ry) / 4

    @property
    def half_width(self) -> float:
        c, s = math.cos(self.angle), math.sin(self.angle)
        return math.hypot(self.rx * c, self.ry * s)

    @property
    def half_height(self) -> float:
        c, s = math.cos(self.angle), math.sin(self.angle)
        return math.hypot(self.rx * s, self.ry * c)

    def geometry(self) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        key = (self.x, self.y, self.angle)
        if key != self._geometry_key:
            c, s = math.cos(self.angle), math.sin(self.angle)
            vertices = []
            for i in range(ELLIPSE_SEGMENTS):
                t = math.tau * i / ELLIPSE_SEGMENTS
                px, py = self.rx * math.cos(t), self.ry * math.sin(t)
                vertices.append((self.x + c * px - s * py, self.y + s * px + c * py))
            axes = []
            # 对边平行，保留一半法线即可完成分离轴检测。
            for index, (px, py) in enumerate(vertices[:ELLIPSE_SEGMENTS // 2]):
                qx, qy = vertices[(index + 1) % ELLIPSE_SEGMENTS]
                nx, ny = -(qy - py), qx - px
                length = math.hypot(nx, ny)
                axes.append((nx / length, ny / length))
            self._geometry_key, self._geometry_value = key, (vertices, axes)
        return self._geometry_value


def support_point(ball: Ball, nx: float, ny: float) -> tuple[float, float]:
    """旋转椭圆沿一个方向的边缘，用于墙面的接触位置。"""
    c, s = math.cos(ball.angle), math.sin(ball.angle)
    lx, ly = c * nx + s * ny, -s * nx + c * ny
    length = math.hypot(ball.rx * lx, ball.ry * ly)
    px, py = ball.rx * ball.rx * lx / length, ball.ry * ball.ry * ly / length
    return ball.x + c * px - s * py, ball.y + s * px + c * py


def contact_between(a: Ball, b: Ball) -> tuple[float, float, float, float, float] | None:
    """圆形解析检测；椭圆使用20边形的分离轴检测。"""
    dx, dy = b.x - a.x, b.y - a.y
    bound = max(a.rx, a.ry) + max(b.rx, b.ry)
    if dx * dx + dy * dy >= bound * bound:
        return None
    if a.is_circle and b.is_circle:
        distance = math.hypot(dx, dy)
        if distance >= a.r + b.r:
            return None
        nx, ny = (dx / distance, dy / distance) if distance > 0.001 else (0, 1)
        cx = (a.x + nx * a.r + b.x - nx * b.r) / 2
        cy = (a.y + ny * a.r + b.y - ny * b.r) / 2
        return nx, ny, a.r + b.r - distance, cx, cy
    va, aa = ([], []) if a.is_circle else a.geometry()
    vb, ab = ([], []) if b.is_circle else b.geometry()
    axes = aa + ab
    if a.is_circle or b.is_circle:
        circle, vertices = (a, vb) if a.is_circle else (b, va)
        px, py = min(vertices, key=lambda point: (point[0] - circle.x) ** 2 + (point[1] - circle.y) ** 2)
        length = math.hypot(px - circle.x, py - circle.y)
        if length > 0.001:
            axes.append(((px - circle.x) / length, (py - circle.y) / length))
    depth, normal = math.inf, (0.0, 1.0)
    for nx, ny in axes:
        if a.is_circle:
            middle = a.x * nx + a.y * ny
            amin, amax = middle - a.r, middle + a.r
        else:
            projections = [x * nx + y * ny for x, y in va]
            amin, amax = min(projections), max(projections)
        if b.is_circle:
            middle = b.x * nx + b.y * ny
            bmin, bmax = middle - b.r, middle + b.r
        else:
            projections = [x * nx + y * ny for x, y in vb]
            bmin, bmax = min(projections), max(projections)
        overlap = min(amax - bmin, bmax - amin)
        if overlap <= 0:
            return None
        if overlap < depth:
            depth, normal = overlap, (nx, ny)
    nx, ny = normal
    if dx * nx + dy * ny < 0:
        nx, ny = -nx, -ny

    ax, ay = support_point(a, nx, ny)
    bx, by = support_point(b, -nx, -ny)
    if a.is_circle:
        return nx, ny, depth, ax, ay
    if b.is_circle:
        return nx, ny, depth, bx, by
    return nx, ny, depth, (ax + bx) / 2, (ay + by) / 2


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    ttl: float
    color: tuple[int, int, int]
    size: float


@dataclass
class Ring:
    x: float
    y: float
    r: float
    life: float
    ttl: float
    color: tuple[int, int, int]


@dataclass
class FloatLabel:
    x: float
    y: float
    value: int
    life: float
    ttl: float
    color: tuple[int, int, int]


class GameState:
    def __init__(self, score_path: Path | None = None, rng: random.Random | None = None):
        self.score_path = score_path or ROOT / 'highscore.json'
        self.rng = rng or random.Random()
        self.best = read_best(self.score_path)
        self.reset()

    def random_level(self) -> int:
        value = self.rng.random()
        return 1 if value < 0.48 else 2 if value < 0.81 else 3

    def reset(self) -> None:
        self.balls: list[Ball] = []
        self.particles: list[Particle] = []
        self.rings: list[Ring] = []
        self.labels: list[FloatLabel] = []
        self.sounds: list[tuple[str, int]] = []
        self.score = 0
        self.current = self.random_level()
        self.next = self.random_level()
        self.max_reached = 1
        self.aim_x = BOARD_W / 2
        self.cooldown = 0.0
        self.warning = 0.0
        self.combo = 0
        self.combo_clock = 0.0
        self.elapsed = 0.0
        self.paused = False
        self.ended = False

    def make_ball(self, level: int, x: float, y: float, vx: float = 0, vy: float = 0) -> Ball:
        half_width = RX[level]
        return Ball(level, clamp(x, LEFT + half_width, RIGHT - half_width), y, vx, vy,
                    spin=(self.rng.random() - 0.5) * 1.1)

    def drop(self) -> bool:
        if self.paused or self.ended or self.cooldown > 0:
            return False
        half_width = RX[self.current]
        x = clamp(self.aim_x, LEFT + half_width, RIGHT - half_width)
        self.balls.append(self.make_ball(self.current, x, 61))
        self.sounds.append(('drop', self.current))
        self.current, self.next = self.next, self.random_level()
        self.cooldown = DROP_DELAY
        return True

    def impact(self, ball: Ball, strength: float, nx: float, ny: float) -> None:
        if strength < 210 or self.elapsed - ball.last_impact < 0.13:
            return
        ball.last_impact = self.elapsed
        ball.squash = min(0.24, strength / 1900)
        if strength > 380:
            for _ in range(3):
                self.particles.append(Particle(
                    ball.x - nx * min(ball.rx, ball.ry) * 0.75,
                    ball.y - ny * min(ball.rx, ball.ry) * 0.75,
                    (self.rng.random() - 0.5) * 90, -30 - self.rng.random() * 55,
                    0.25, 0.25, COLORS[ball.level], 2,
                ))

    def collide_walls(self, ball: Ball) -> None:
        def respond(nx: float, ny: float, restitution: float) -> None:
            px, py = support_point(ball, -nx, -ny)
            rx, ry = px - ball.x, py - ball.y
            cvx, cvy = ball.vx - ball.spin * ry, ball.vy + ball.spin * rx
            speed = cvx * nx + cvy * ny
            if speed >= 0:
                return
            self.impact(ball, -speed, -nx, -ny)
            cross = rx * ny - ry * nx
            denominator = 1 / ball.mass + cross * cross / ball.inertia
            bounce = restitution if speed < -70 else 0
            impulse = -(1 + bounce) * speed / denominator
            ball.vx += impulse * nx / ball.mass
            ball.vy += impulse * ny / ball.mass
            ball.spin += impulse * cross / ball.inertia
            tx, ty = -ny, nx
            tangent = (ball.vx - ball.spin * ry) * tx + (ball.vy + ball.spin * rx) * ty
            cross_t = rx * ty - ry * tx
            friction = clamp(-tangent / (1 / ball.mass + cross_t * cross_t / ball.inertia),
                             -impulse * 0.32, impulse * 0.32)
            ball.vx += friction * tx / ball.mass
            ball.vy += friction * ty / ball.mass
            ball.spin += friction * cross_t / ball.inertia

        half_width, half_height = ball.half_width, ball.half_height
        if ball.x - half_width < LEFT:
            ball.x = LEFT + half_width
            respond(1, 0, 0.5)
        if ball.x + half_width > RIGHT:
            ball.x = RIGHT - half_width
            respond(-1, 0, 0.5)
        if ball.y + half_height > FLOOR:
            ball.y = FLOOR - half_height
            respond(0, -1, 0.47)

    def burst(self, x: float, y: float, level: int) -> None:
        count = 23 if level >= 7 else 11 + level
        for index in range(count):
            angle = math.tau * index / count + self.rng.random() * 0.35
            speed = 70 + self.rng.random() * (220 if level >= 7 else 150)
            life = 0.4 + self.rng.random() * 0.3
            self.particles.append(Particle(
                x, y, math.cos(angle) * speed, math.sin(angle) * speed,
                life, life, COLORS[level], 2 + self.rng.random() * 3,
            ))
        self.rings.append(Ring(x, y, 15, 0.42, 0.42, COLORS[level]))

    def merge(self, a: Ball, b: Ball) -> None:
        level = a.level + 1
        x = clamp((a.x + b.x) / 2, LEFT + RX[level], RIGHT - RX[level])
        y = min((a.y + b.y) / 2, FLOOR - RY[level])
        vy = min(-120, (a.vy + b.vy) * 0.15 - 120)
        born = self.make_ball(level, x, y, (a.vx + b.vx) * 0.25, vy)
        ax, ay, bx, by = a.x - born.x, a.y - born.y, b.x - born.x, b.y - born.y
        angular_momentum = (a.inertia * a.spin + b.inertia * b.spin
                            + a.mass * (ax * a.vy - ay * a.vx)
                            + b.mass * (bx * b.vy - by * b.vx))
        born.spin = clamp(angular_momentum / born.inertia, -8, 8)
        born.pop = 0.22
        self.balls.append(born)
        self.combo = self.combo + 1 if self.combo_clock > 0 else 1
        self.combo_clock = 1.65
        gained = round(10 * 2 ** (level - 1) * (1 + min(self.combo - 1, 5) * 0.25))
        self.score += gained
        if self.score > self.best:
            self.best = self.score
            save_best(self.score_path, self.best)
        self.max_reached = max(self.max_reached, level)
        self.burst(x, y, level)
        self.labels.append(FloatLabel(x, y - 10, gained, 0.9, 0.9, COLORS[level]))
        self.sounds.append(('merge', level))

    def resolve_pairs(self) -> None:
        taken: set[Ball] = set()
        matches: list[tuple[Ball, Ball]] = []
        for i, a in enumerate(self.balls):
            if a in taken:
                continue
            for b in self.balls[i + 1:]:
                if b in taken:
                    continue
                contact = contact_between(a, b)
                if contact is None:
                    continue
                if a.level == b.level and a.level < 8:
                    taken.update((a, b))
                    matches.append((a, b))
                    break
                nx, ny, penetration, cx, cy = contact
                inv_a, inv_b = 1 / a.mass, 1 / b.mass
                inv_total = inv_a + inv_b
                push = max(0, penetration - 0.1) * 0.68 / inv_total
                a.x -= nx * push * inv_a
                a.y -= ny * push * inv_a
                b.x += nx * push * inv_b
                b.y += ny * push * inv_b
                rax, ray = cx - a.x, cy - a.y
                rbx, rby = cx - b.x, cy - b.y
                rvx = (b.vx - b.spin * rby) - (a.vx - a.spin * ray)
                rvy = (b.vy + b.spin * rbx) - (a.vy + a.spin * rax)
                normal_speed = rvx * nx + rvy * ny
                if normal_speed >= 0:
                    continue
                elasticity = 0.59 if normal_speed < -85 else 0.08
                cross_a, cross_b = rax * ny - ray * nx, rbx * ny - rby * nx
                normal_mass = inv_total + cross_a * cross_a / a.inertia + cross_b * cross_b / b.inertia
                impulse = -(1 + elasticity) * normal_speed / normal_mass
                a.vx -= impulse * inv_a * nx
                a.vy -= impulse * inv_a * ny
                b.vx += impulse * inv_b * nx
                b.vy += impulse * inv_b * ny
                a.spin -= impulse * cross_a / a.inertia
                b.spin += impulse * cross_b / b.inertia
                tx, ty = -ny, nx
                rvx = (b.vx - b.spin * rby) - (a.vx - a.spin * ray)
                rvy = (b.vy + b.spin * rbx) - (a.vy + a.spin * rax)
                tangent_speed = rvx * tx + rvy * ty
                cross_ta, cross_tb = rax * ty - ray * tx, rbx * ty - rby * tx
                tangent_mass = inv_total + cross_ta * cross_ta / a.inertia + cross_tb * cross_tb / b.inertia
                friction = clamp(-tangent_speed / tangent_mass, -impulse * 0.34, impulse * 0.34)
                a.vx -= friction * inv_a * tx
                a.vy -= friction * inv_a * ty
                b.vx += friction * inv_b * tx
                b.vy += friction * inv_b * ty
                a.spin -= friction * cross_ta / a.inertia
                b.spin += friction * cross_tb / b.inertia
                self.impact(a, -normal_speed, nx, ny)
                self.impact(b, -normal_speed, -nx, -ny)
        if matches:
            self.balls = [ball for ball in self.balls if ball not in taken]
            for a, b in matches:
                self.merge(a, b)

    def update_effects(self, dt: float) -> None:
        for particle in self.particles:
            particle.x += particle.vx * dt
            particle.y += particle.vy * dt
            particle.vy += 180 * dt
            particle.life -= dt
        for ring in self.rings:
            ring.r += 260 * dt
            ring.life -= dt
        for label in self.labels:
            label.y -= 48 * dt
            label.life -= dt
        self.particles = [p for p in self.particles if p.life > 0]
        self.rings = [r for r in self.rings if r.life > 0]
        self.labels = [l for l in self.labels if l.life > 0]

    def step(self, dt: float = STEP) -> None:
        if self.paused or self.ended:
            return
        self.elapsed += dt
        self.cooldown = max(0, self.cooldown - dt)
        self.combo_clock = max(0, self.combo_clock - dt)
        for ball in self.balls:
            ball.age += dt
            ball.vy += GRAVITY * dt
            ball.vx *= 0.998
            ball.vy *= 0.999
            ball.x += ball.vx * dt
            ball.y += ball.vy * dt
            ball.angle += ball.spin * dt
            ball.spin *= 0.991
            ball.squash *= 0.88
            ball.pop = max(0, ball.pop - dt)
            self.collide_walls(ball)
        for _ in range(SOLVER_PASSES):
            self.resolve_pairs()
            for ball in self.balls:
                self.collide_walls(ball)
        self.update_effects(dt)
        overflowing = any(ball.age > 0.85 and ball.y - ball.half_height < DANGER for ball in self.balls)
        self.warning = self.warning + dt if overflowing else max(0, self.warning - dt * 2)
        if self.warning >= 2:
            self.warning = 2
            self.ended = True
            self.sounds.append(('over', 0))


class SoundBank:
    def __init__(self):
        self.enabled = False
        self.available = False
        self.cache: dict[tuple[int, int], pygame.mixer.Sound] = {}

    def toggle(self) -> bool:
        if self.enabled:
            self.enabled = False
            return False
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=22050, size=-16, channels=1)
            self.available = True
            self.enabled = True
        except pygame.error:
            self.available = False
            self.enabled = False
        return self.enabled

    def play(self, kind: str, level: int = 0) -> None:
        if not self.enabled or not self.available:
            return
        frequency = 260 if kind == 'drop' else 175 if kind == 'over' else 260 + level * 76
        duration = 0.09 if kind == 'drop' else 0.55 if kind == 'over' else 0.18
        key = (frequency, round(duration * 100))
        if key not in self.cache:
            sample_rate, _, channels = pygame.mixer.get_init()
            count = int(sample_rate * duration)
            samples = array('h')
            for i in range(count):
                t = i / sample_rate
                envelope = (1 - i / count) ** 2
                waveform = math.sin(math.tau * frequency * t)
                samples.extend([int(32767 * 0.12 * envelope * waveform)] * channels)
            self.cache[key] = pygame.mixer.Sound(buffer=samples.tobytes())
        self.cache[key].play()


class Renderer:
    def __init__(self):
        self.font_cache: dict[tuple[int, bool], pygame.font.Font] = {}
        self.icon_cache: dict[int, pygame.Surface] = {}
        self.orbs: dict[int, pygame.Surface] = {}
        self.rotated: dict[tuple[int, int], pygame.Surface] = {}
        self.background = self.make_background()
        self.board_background = self.make_board_background()
        for level in range(1, 9):
            path = ROOT / f'lv{level}.png'
            self.icon_cache[level] = pygame.image.load(str(path)).convert_alpha()
            self.orbs[level] = self.make_orb(level)

    def font(self, size: int, bold: bool = False) -> pygame.font.Font:
        key = (size, bold)
        if key not in self.font_cache:
            self.font_cache[key] = pygame.font.SysFont('stheitimedium', size, bold=bold)
        return self.font_cache[key]

    def text(self, target: pygame.Surface, value: str, size: int, color: tuple,
             x: float, y: float, bold: bool = False, align: str = 'left') -> None:
        image = self.font(size, bold).render(str(value), True, color)
        rect = image.get_rect()
        if align == 'center':
            rect.midtop = (round(x), round(y))
        elif align == 'right':
            rect.topright = (round(x), round(y))
        else:
            rect.topleft = (round(x), round(y))
        target.blit(image, rect)

    @staticmethod
    def mix(a: tuple[int, int, int], b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
        return tuple(round(a[i] + (b[i] - a[i]) * amount) for i in range(3))

    def make_background(self) -> pygame.Surface:
        surface = pygame.Surface((WIDTH, HEIGHT)).convert()
        for y in range(HEIGHT):
            color = self.mix((20, 38, 67), BG, min(1, y / HEIGHT * 1.25))
            pygame.draw.line(surface, color, (0, y), (WIDTH, y))
        return surface

    def make_board_background(self) -> pygame.Surface:
        surface = pygame.Surface((BOARD_W, BOARD_H)).convert()
        for y in range(BOARD_H):
            color = self.mix((23, 54, 87), (13, 27, 50), y / BOARD_H)
            pygame.draw.line(surface, color, (0, y), (BOARD_W, y))
        for x in range(25, BOARD_W, 35):
            pygame.draw.line(surface, (24, 55, 81), (x, 0), (x, BOARD_H))
        for y in range(24, BOARD_H, 35):
            pygame.draw.line(surface, (24, 55, 81), (0, y), (BOARD_W, y))
        pygame.draw.rect(surface, (22, 54, 79), (0, FLOOR, BOARD_W, BOARD_H - FLOOR))
        pygame.draw.line(surface, (76, 156, 181), (LEFT, FLOOR), (RIGHT, FLOOR), 3)
        pygame.draw.line(surface, (42, 107, 136), (LEFT, 0), (LEFT, FLOOR), 3)
        pygame.draw.line(surface, (42, 107, 136), (RIGHT, 0), (RIGHT, FLOOR), 3)
        return surface

    def make_orb(self, level: int) -> pygame.Surface:
        final_size = (math.ceil(RX[level] * 2) + 26, math.ceil(RY[level] * 2) + 26)
        rx, ry = RX[level] * 2, RY[level] * 2
        surface = pygame.Surface((final_size[0] * 2, final_size[1] * 2), pygame.SRCALPHA)
        cx, cy = surface.get_rect().center
        color = COLORS[level]

        def ellipse_rect(grow=0):
            return pygame.Rect(round(cx - rx - grow), round(cy - ry - grow),
                               round(2 * (rx + grow)), round(2 * (ry + grow)))

        for grow, alpha in ((11, 8), (7, 15), (3, 25)):
            pygame.draw.ellipse(surface, (*color, alpha), ellipse_rect(grow * 2))
        pygame.draw.ellipse(surface, (21, 43, 72), ellipse_rect())
        pygame.draw.ellipse(surface, (35, 68, 102),
                            (cx - rx * 0.93, cy - ry * 0.93, rx * 1.52, ry * 1.52))
        pygame.draw.ellipse(surface, color, ellipse_rect(), max(4, round(min(rx, ry) * 0.052)))
        pygame.draw.arc(surface, (227, 248, 255, 110),
                        pygame.Rect(cx - rx * 0.81, cy - ry * 0.81, rx * 1.62, ry * 1.62),
                        math.pi * 1.12, math.pi * 1.65, max(2, round(min(rx, ry) * 0.035)))
        factor = 1.65 if level == 8 else 1.49
        source = self.icon_cache[level]
        scale = min(rx * factor / source.get_width(), ry * factor / source.get_height())
        icon = pygame.transform.smoothscale(source,
                    (max(1, round(source.get_width() * scale)), max(1, round(source.get_height() * scale))))
        surface.blit(icon, icon.get_rect(center=(cx, cy)))
        return pygame.transform.smoothscale(surface, final_size)

    def orb_image(self, level: int, angle: float = 0) -> pygame.Surface:
        degree = round(math.degrees(angle) / 3) * 3 % 360
        key = (level, degree)
        if key not in self.rotated:
            if len(self.rotated) >= 512:
                self.rotated.pop(next(iter(self.rotated)))
            self.rotated[key] = pygame.transform.rotozoom(self.orbs[level], -degree, 1)
        return self.rotated[key]

    def thumbnail(self, level: int, size: int) -> pygame.Surface:
        image = self.orbs[level]
        scale = size / max(image.get_size())
        icon = pygame.transform.smoothscale(image,
                    (max(1, round(image.get_width() * scale)), max(1, round(image.get_height() * scale))))
        square = pygame.Surface((size, size), pygame.SRCALPHA)
        square.blit(icon, icon.get_rect(center=(size // 2, size // 2)))
        return square

    @staticmethod
    def panel(surface: pygame.Surface, rect: pygame.Rect, fill=(20, 33, 59), border=(53, 71, 102), radius=18) -> None:
        pygame.draw.rect(surface, fill, rect, border_radius=radius)
        pygame.draw.rect(surface, border, rect, 1, border_radius=radius)

    def draw_ball(self, board: pygame.Surface, ball: Ball) -> None:
        sprite = self.orb_image(ball.level, ball.angle)
        scale = 1 + math.sin((1 - ball.pop / 0.22) * math.pi) * 0.18 if ball.pop > 0 else 1
        if ball.squash > 0.005 or scale != 1:
            width = max(1, round(sprite.get_width() * scale * (1 + ball.squash * 0.5)))
            height = max(1, round(sprite.get_height() * scale * (1 - ball.squash * 0.65)))
            sprite = pygame.transform.smoothscale(sprite, (width, height))
        board.blit(sprite, sprite.get_rect(center=(round(ball.x), round(ball.y))))

    def draw_board(self, state: GameState) -> pygame.Surface:
        board = self.board_background.copy()
        line_color = RED if state.warning > 0 else (190, 134, 111)
        for x in range(LEFT + 2, RIGHT - 2, 15):
            pygame.draw.line(board, line_color, (x, DANGER), (min(x + 8, RIGHT), DANGER),
                             3 if state.warning else 2)
        self.text(board, '警戒线', 12, line_color, LEFT + 10, DANGER - 24, True)
        self.text(board, 'DROP ZONE', 10, (110, 170, 194), RIGHT - 8, 13, True, 'right')
        if not state.paused and not state.ended:
            x = round(clamp(state.aim_x, LEFT + RX[state.current], RIGHT - RX[state.current]))
            for y in range(round(61 + RY[state.current]), FLOOR, 14):
                pygame.draw.line(board, (76, 141, 168), (x, y), (x, min(y + 6, FLOOR)), 1)
            preview = self.orbs[state.current].copy()
            if state.cooldown > 0:
                preview.set_alpha(130)
            board.blit(preview, preview.get_rect(center=(x, 61)))
        for ball in state.balls:
            self.draw_ball(board, ball)
        for ring in state.rings:
            radius = round(ring.r)
            if radius <= 0:
                continue
            color = (*ring.color, round(180 * ring.life / ring.ttl))
            size = radius * 2 + 8
            layer = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.draw.circle(layer, color, (size // 2, size // 2), radius, 3)
            board.blit(layer, (round(ring.x - size / 2), round(ring.y - size / 2)))
        for particle in state.particles:
            alpha = round(255 * clamp(particle.life / particle.ttl, 0, 1))
            radius = max(1, round(particle.size))
            layer = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
            pygame.draw.circle(layer, (*particle.color, alpha), (radius + 1, radius + 1), radius)
            board.blit(layer, (round(particle.x - radius), round(particle.y - radius)))
        for label in state.labels:
            image = self.font(21, True).render(f'+{label.value}', True, label.color)
            image.set_alpha(round(255 * label.life / label.ttl))
            board.blit(image, image.get_rect(midtop=(round(label.x), round(label.y))))
        return board

    def draw_button(self, surface: pygame.Surface, rect: pygame.Rect, icon: str, active=False) -> None:
        fill = (36, 66, 92) if active else (26, 42, 72)
        self.panel(surface, rect, fill=fill, border=(71, 112, 144), radius=11)
        if icon == 'restart':
            cx, cy = rect.center
            pygame.draw.arc(surface, TEXT, (cx - 10, cy - 10, 20, 20),
                            math.pi * 0.12, math.pi * 1.83, 2)
            pygame.draw.polygon(surface, TEXT,
                                ((cx + 11, cy - 5), (cx + 11, cy + 3), (cx + 4, cy - 1)))
        else:
            self.text(surface, icon, 22, CYAN if active else TEXT, rect.centerx, rect.y + 7, True, 'center')

    def draw(self, state: GameState, sound_on: bool) -> pygame.Surface:
        scene = self.background.copy()
        self.panel(scene, pygame.Rect(25, 15, 49, 49), (19, 56, 85), (63, 119, 146), 15)
        self.text(scene, '芯', 28, CYAN, 49, 22, True, 'center')
        self.text(scene, 'UESTC · MERGE LAB', 10, CYAN, 87, 15, True)
        self.text(scene, '芯片进化局', 27, TEXT, 87, 28, True)
        self.text(scene, '从一颗电子，合成电子科大', 12, MUTED, 258, 40)
        self.draw_button(scene, pygame.Rect(886, 21, 42, 42), '♫' if sound_on else '♪', sound_on)
        self.draw_button(scene, pygame.Rect(936, 21, 42, 42), '▶' if state.paused else 'Ⅱ', state.paused)
        self.draw_button(scene, pygame.Rect(986, 21, 42, 42), 'restart')

        self.panel(scene, pygame.Rect(25, 82, 240, 650))
        self.text(scene, '实验记录', 16, TEXT, 42, 100, True)
        self.panel(scene, pygame.Rect(40, 136, 210, 138), (27, 67, 100), (62, 107, 136), 15)
        self.text(scene, '当前得分', 13, (169, 199, 221), 55, 151, True)
        self.text(scene, f'{state.score:,}', 42, TEXT, 55, 175, True)
        self.text(scene, f'最高纪录  ·  {state.best:,}', 13, (201, 222, 234), 55, 244)
        self.text(scene, '下一颗', 16, TEXT, 42, 308, True)
        self.panel(scene, pygame.Rect(40, 345, 210, 90), (14, 33, 61), (48, 78, 108), 13)
        next_icon = self.thumbnail(state.next, 68)
        scene.blit(next_icon, next_icon.get_rect(center=(83, 390)))
        self.text(scene, NAMES[state.next], 17, TEXT, 128, 365, True)
        self.text(scene, '提前规划落点', 12, MUTED, 128, 394)
        pygame.draw.line(scene, (56, 77, 105), (41, 473), (249, 473))
        self.text(scene, '玩法', 15, TEXT, 42, 493, True)
        for index, value in enumerate(('移动鼠标瞄准，点击投放', '同级相碰，合成进化', '椭圆会翻转，留意落点', '越线持续两秒才结束')):
            self.text(scene, '· ' + value, 13, MUTED, 42, 525 + index * 28)
        self.text(scene, '← → 移动   空格投放', 12, (184, 222, 237), 42, 664)
        self.text(scene, 'P 暂停   R 重开   M 音效', 12, (184, 222, 237), 42, 687)

        self.panel(scene, pygame.Rect(290, 58, 480, 684))
        self.text(scene, 'LAB / 01 · 合成舱', 12, MUTED, 306, 72, True)
        status_color = RED if state.warning > 0 else (79, 224, 187)
        pygame.draw.circle(scene, status_color, (599, 79), 4)
        status = f'越线警报  {max(0, 2 - state.warning):.1f}s' if state.warning > 0 else '实验进行中'
        self.text(scene, status, 12, status_color, 609, 71, True)
        scene.blit(self.draw_board(state), (BOARD_X, BOARD_Y))
        pygame.draw.rect(scene, (66, 101, 137), (BOARD_X, BOARD_Y, BOARD_W, BOARD_H), 1, border_radius=13)
        hint = ('电子科大合成成功！' if state.max_reached >= 8 else
                '再进一步，就能合成电子科大！' if state.max_reached == 7 else '同级相碰，合成进化')
        self.text(scene, hint, 12, MUTED, BOARD_X + 7, 725)
        if state.combo > 1 and state.combo_clock > 0:
            self.text(scene, f'连锁 ×{state.combo}', 13, ORANGE, BOARD_X + BOARD_W - 7, 724, True, 'right')

        self.panel(scene, pygame.Rect(795, 82, 240, 650))
        self.text(scene, '进化图鉴', 16, TEXT, 812, 100, True)
        self.text(scene, '01 — 08', 12, MUTED, 1015, 102, False, 'right')
        for level in range(1, 9):
            y = 137 + (level - 1) * 66
            reached = level <= state.max_reached
            fill = (23, 43, 71) if reached else (17, 30, 54)
            border = (76, 121, 145) if reached else (52, 69, 99)
            self.panel(scene, pygame.Rect(810, y, 210, 58), fill, border, 12)
            if level == state.max_reached:
                pygame.draw.rect(scene, CYAN, (810, y + 7, 3, 44), border_radius=2)
            icon = self.thumbnail(level, 47)
            if not reached:
                icon = icon.copy()
                icon.set_alpha(75)
            scene.blit(icon, (817, y + 5))
            self.text(scene, f'LEVEL {level:02d}', 11, CYAN if reached else (120, 139, 170), 870, y + 8, True)
            self.text(scene, NAMES[level], 14, TEXT if reached else (127, 145, 172), 870, y + 26, True)
        self.text(scene, '解锁新形态，点亮整条进化链', 11, MUTED, 915, 691, False, 'center')

        if state.paused or state.ended:
            overlay = pygame.Surface((BOARD_W, BOARD_H), pygame.SRCALPHA)
            overlay.fill((8, 21, 42, 215))
            scene.blit(overlay, (BOARD_X, BOARD_Y))
            box = pygame.Rect(365, 280, 330, 222)
            self.panel(scene, box, (28, 52, 83), (91, 121, 152), 18)
            if state.ended:
                self.text(scene, '✦', 34, ORANGE, 530, 294, True, 'center')
                self.text(scene, '本轮实验结束', 27, TEXT, 530, 341, True, 'center')
                self.text(scene, f'获得 {state.score:,} 分  ·  最高合成 {NAMES[state.max_reached]}',
                          14, (189, 205, 225), 530, 384, False, 'center')
                button_text = '再试一次'
            else:
                self.text(scene, 'Ⅱ', 34, ORANGE, 530, 294, True, 'center')
                self.text(scene, '实验暂停', 27, TEXT, 530, 341, True, 'center')
                self.text(scene, '球已经停住，随时可以继续。', 14,
                          (189, 205, 225), 530, 384, False, 'center')
                button_text = '继续实验'
            pygame.draw.rect(scene, (112, 224, 231), (437, 431, 186, 46), border_radius=11)
            self.text(scene, button_text, 17, (17, 32, 57), 530, 441, True, 'center')
        return scene


def logical_pos(pos: tuple[int, int], window_size: tuple[int, int]) -> tuple[float, float]:
    sw, sh = window_size
    scale = min(sw / WIDTH, sh / HEIGHT)
    ox, oy = (sw - WIDTH * scale) / 2, (sh - HEIGHT * scale) / 2
    return (pos[0] - ox) / scale, (pos[1] - oy) / scale


def present(window: pygame.Surface, scene: pygame.Surface) -> None:
    sw, sh = window.get_size()
    scale = min(sw / WIDTH, sh / HEIGHT)
    dw, dh = round(WIDTH * scale), round(HEIGHT * scale)
    window.fill(BG)
    image = scene if (dw, dh) == (WIDTH, HEIGHT) else pygame.transform.smoothscale(scene, (dw, dh))
    window.blit(image, ((sw - dw) // 2, (sh - dh) // 2))
    pygame.display.flip()


def main() -> None:
    pygame.init()
    window = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
    pygame.display.set_caption('芯片进化局 · 合成电子科大')
    renderer = Renderer()
    state = GameState()
    sound = SoundBank()
    clock = pygame.time.Clock()
    accumulator = 0.0
    running = True
    while running:
        dt = min(0.05, clock.tick(60) / 1000)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                window = pygame.display.set_mode((max(420, event.w), max(330, event.h)), pygame.RESIZABLE)
            elif event.type == pygame.MOUSEMOTION:
                x, _ = logical_pos(event.pos, window.get_size())
                state.aim_x = clamp(x - BOARD_X, LEFT + RX[state.current], RIGHT - RX[state.current])
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                x, y = logical_pos(event.pos, window.get_size())
                if pygame.Rect(886, 21, 42, 42).collidepoint(x, y):
                    sound.toggle()
                elif pygame.Rect(936, 21, 42, 42).collidepoint(x, y):
                    if not state.ended:
                        state.paused = not state.paused
                elif pygame.Rect(986, 21, 42, 42).collidepoint(x, y):
                    state.reset()
                    accumulator = 0
                elif state.paused or state.ended:
                    if pygame.Rect(437, 431, 186, 46).collidepoint(x, y):
                        if state.ended:
                            state.reset()
                            accumulator = 0
                        else:
                            state.paused = False
                elif pygame.Rect(BOARD_X, BOARD_Y, BOARD_W, BOARD_H).collidepoint(x, y):
                    state.aim_x = clamp(x - BOARD_X, LEFT + RX[state.current], RIGHT - RX[state.current])
                    state.drop()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r:
                    state.reset()
                    accumulator = 0
                elif event.key in (pygame.K_p, pygame.K_ESCAPE) and not state.ended:
                    state.paused = not state.paused
                elif event.key == pygame.K_m:
                    sound.toggle()
                elif event.key == pygame.K_LEFT:
                    state.aim_x = clamp(state.aim_x - 24, LEFT + RX[state.current], RIGHT - RX[state.current])
                elif event.key == pygame.K_RIGHT:
                    state.aim_x = clamp(state.aim_x + 24, LEFT + RX[state.current], RIGHT - RX[state.current])
                elif event.key == pygame.K_SPACE:
                    state.drop()
            elif event.type == pygame.WINDOWFOCUSLOST and not state.ended:
                state.paused = True
        if not state.paused and not state.ended:
            accumulator = min(0.1, accumulator + dt)
            while accumulator >= STEP and not state.ended:
                state.step(STEP)
                accumulator -= STEP
        for kind, level in state.sounds:
            sound.play(kind, level)
        state.sounds.clear()
        present(window, renderer.draw(state, sound.enabled))
    pygame.quit()


if __name__ == '__main__':
    main()
