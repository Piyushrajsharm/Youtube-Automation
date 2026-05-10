from __future__ import annotations

import math
import numpy as np
from PIL import Image, ImageDraw


class Particle:
    __slots__ = (
        "x", "y", "z", "vx", "vy", "vz",
        "size", "alpha", "color", "lifetime", "age",
        "type", "glow", "trail",
    )

    def __init__(
        self,
        x: float, y: float, z: float,
        vx: float, vy: float, vz: float,
        size: float, alpha: float,
        color: tuple[int, int, int],
        lifetime: float,
        ptype: str = "dust",
        glow: bool = False,
        trail: bool = False,
    ):
        self.x = x
        self.y = y
        self.z = z
        self.vx = vx
        self.vy = vy
        self.vz = vz
        self.size = size
        self.alpha = alpha
        self.color = color
        self.lifetime = lifetime
        self.age = 0.0
        self.type = ptype
        self.glow = glow
        self.trail = trail

    def update(self, dt: float, turbulence: float = 0.0) -> bool:
        self.age += dt
        if self.age >= self.lifetime:
            return False

        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt

        if self.type == "dust":
            self.vx += np.random.normal(0, turbulence) * dt
            self.vy += np.random.normal(0, turbulence * 0.5) * dt
        elif self.type == "spark":
            self.vy += 40 * dt
            self.vx *= 0.98
            self.vy *= 0.98
        elif self.type == "ember":
            self.vy -= 15 * dt
            self.vx += math.sin(self.age * 3) * 5 * dt
        elif self.type == "bokeh":
            self.vx *= 0.995
            self.vy *= 0.995

        life_ratio = 1 - self.age / self.lifetime
        if self.type in ("spark", "ember"):
            self.alpha = max(0, self.alpha * life_ratio)
            self.size *= (1 - dt * 0.3)
        else:
            self.alpha = self.alpha * (0.7 + 0.3 * life_ratio)

        return self.size > 0.5 and self.alpha > 0.01


class ParticleSystem:
    def __init__(self, seed: int = 42):
        self.particles: list[Particle] = []
        self.rng = np.random.default_rng(seed)
        self.trail_history: dict[int, list[tuple[float, float]]] = {}

    def emit_dust(
        self,
        count: int,
        width: int,
        height: int,
        colors: list[tuple[int, int, int]] | None = None,
        size_range: tuple[float, float] = (1.0, 4.0),
        lifetime_range: tuple[float, float] = (3.0, 8.0),
        velocity_range: tuple[float, float] = (-8, 8),
    ) -> None:
        if colors is None:
            colors = [(180, 200, 220), (200, 210, 230), (160, 180, 200)]

        for _ in range(count):
            self.particles.append(Particle(
                x=self.rng.uniform(0, width),
                y=self.rng.uniform(0, height),
                z=self.rng.uniform(0.2, 1.0),
                vx=self.rng.uniform(*velocity_range),
                vy=self.rng.uniform(*velocity_range),
                vz=self.rng.uniform(-2, 2),
                size=self.rng.uniform(*size_range),
                alpha=self.rng.uniform(0.15, 0.5),
                color=colors[self.rng.integers(0, len(colors))],
                lifetime=self.rng.uniform(*lifetime_range),
                ptype="dust",
            ))

    def emit_sparks(
        self,
        count: int,
        origin_x: float,
        origin_y: float,
        color: tuple[int, int, int] = (255, 200, 100),
        speed: float = 80.0,
        size_range: tuple[float, float] = (1.5, 3.5),
        lifetime_range: tuple[float, float] = (0.5, 1.5),
    ) -> None:
        for _ in range(count):
            angle = self.rng.uniform(0, math.tau)
            speed_var = speed * self.rng.uniform(0.4, 1.0)
            self.particles.append(Particle(
                x=origin_x,
                y=origin_y,
                z=0.8,
                vx=math.cos(angle) * speed_var,
                vy=math.sin(angle) * speed_var,
                vz=0,
                size=self.rng.uniform(*size_range),
                alpha=self.rng.uniform(0.6, 1.0),
                color=color,
                lifetime=self.rng.uniform(*lifetime_range),
                ptype="spark",
                glow=True,
            ))

    def emit_embers(
        self,
        count: int,
        width: int,
        height: int,
        color: tuple[int, int, int] = (255, 150, 50),
        size_range: tuple[float, float] = (2.0, 5.0),
        lifetime_range: tuple[float, float] = (2.0, 5.0),
    ) -> None:
        for _ in range(count):
            self.particles.append(Particle(
                x=self.rng.uniform(width * 0.2, width * 0.8),
                y=self.rng.uniform(height * 0.5, height),
                z=self.rng.uniform(0.3, 0.7),
                vx=self.rng.uniform(-10, 10),
                vy=self.rng.uniform(-30, -10),
                vz=0,
                size=self.rng.uniform(*size_range),
                alpha=self.rng.uniform(0.3, 0.7),
                color=color,
                lifetime=self.rng.uniform(*lifetime_range),
                ptype="ember",
                glow=True,
            ))

    def emit_bokeh(
        self,
        count: int,
        width: int,
        height: int,
        colors: list[tuple[int, int, int]] | None = None,
        size_range: tuple[float, float] = (15, 50),
        lifetime_range: tuple[float, float] = (5.0, 10.0),
    ) -> None:
        if colors is None:
            colors = [(100, 200, 255), (255, 200, 100), (255, 100, 150)]

        for _ in range(count):
            self.particles.append(Particle(
                x=self.rng.uniform(0, width),
                y=self.rng.uniform(0, height),
                z=self.rng.uniform(0.05, 0.3),
                vx=self.rng.uniform(-3, 3),
                vy=self.rng.uniform(-3, 3),
                vz=0,
                size=self.rng.uniform(*size_range),
                alpha=self.rng.uniform(0.03, 0.12),
                color=colors[self.rng.integers(0, len(colors))],
                lifetime=self.rng.uniform(*lifetime_range),
                ptype="bokeh",
            ))

    def update(self, dt: float, turbulence: float = 0.0) -> None:
        self.particles = [
            p for p in self.particles if p.update(dt, turbulence)
        ]

    def render(
        self,
        width: int,
        height: int,
    ) -> Image.Image:
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img, "RGBA")

        sorted_particles = sorted(self.particles, key=lambda p: p.z)

        for p in sorted_particles:
            if p.alpha < 0.01 or p.size < 0.5:
                continue

            px, py = int(p.x), int(p.y)
            if not (0 <= px < width and 0 <= py < height):
                continue

            alpha = int(min(255, p.alpha * 255))
            size = max(1, int(p.size))
            color = p.color

            if p.type == "bokeh":
                for ring in range(3):
                    r = size * (1 - ring * 0.25)
                    ring_alpha = int(alpha * (0.3 - ring * 0.08))
                    if ring_alpha > 0:
                        draw.ellipse(
                            (px - r, py - r, px + r, py + r),
                            outline=(*color, ring_alpha),
                            width=max(1, int(size * 0.1)),
                        )
            elif p.glow:
                for glow_ring in range(3):
                    r = size * (1 + glow_ring * 0.8)
                    glow_alpha = int(alpha * (0.6 - glow_ring * 0.18))
                    if glow_alpha > 0:
                        draw.ellipse(
                            (px - r, py - r, px + r, py + r),
                            fill=(*color, glow_alpha),
                        )
            else:
                draw.ellipse(
                    (px - size, py - size, px + size, py + size),
                    fill=(*color, alpha),
                )

        return img


def create_scene_particles(
    width: int,
    height: int,
    scene_type: str,
    time: float,
    colors: dict[str, tuple[int, int, int]],
    dt: float = 0.033,
) -> Image.Image:
    seed = int(time * 1000) % 100000
    system = ParticleSystem(seed=seed)

    primary = colors.get("primary", (0, 245, 212))
    secondary = colors.get("secondary", (255, 214, 102))
    accent = colors.get("accent", (255, 54, 121))

    system.emit_dust(
        count=40,
        width=width,
        height=height,
        colors=[primary, secondary, (180, 200, 220)],
        size_range=(1.0, 3.5),
        velocity_range=(-12, 12),
    )

    if scene_type in ("reveal", "hero", "cta"):
        system.emit_bokeh(
            count=12,
            width=width,
            height=height,
            colors=[primary, secondary],
            size_range=(20, 60),
        )

    if scene_type in ("warning", "danger"):
        system.emit_sparks(
            count=20,
            origin_x=width * 0.5,
            origin_y=height * 0.5,
            color=accent,
            speed=100,
        )
        system.emit_embers(
            count=15,
            width=width,
            height=height,
            color=accent,
        )

    if scene_type in ("payoff", "reveal"):
        system.emit_sparks(
            count=15,
            origin_x=width * 0.5,
            origin_y=height * 0.6,
            color=secondary,
            speed=60,
        )

    system.update(dt, turbulence=2.0)

    return system.render(width, height)
