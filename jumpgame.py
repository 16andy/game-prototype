"""
LEAP RUNNER - a charge-and-jump platformer made with pygame.

HOW TO PLAY
  * Hold the JUMP button (bottom-right) with the mouse, or hold SPACE,
    to charge your jump. Release to leap.
  * The longer you hold, the FARTHER and HIGHER you jump.
  * Clear pits, water and obstacles (rocks, crates, spikes).
    Falling in or bumping into anything ends the run.
  * A / D or LEFT / RIGHT lets you shuffle a few steps (and turn around).
  * Big jumps (70%+ charge) earn a front flip.
  * R or SPACE / click to restart after a game over. ESC quits.

Requires: pip install pygame
"""
import math
import random
import sys

import pygame

# ---------------------------------------------------------------- settings
W, H = 960, 540
FPS = 60
GROUND_Y = 400            # y of the walking surface
GRAVITY = 0.5
CHARGE_TIME = 1.1         # seconds to reach full power
MIN_VX, MAX_VX = 3.0, 12.0
MIN_VY, MAX_VY = 6.0, 14.0
WALK_SPEED = 2.6
PLAYER_HALF_W = 11
PLAYER_H = 50
FLIP_THRESHOLD = 0.7

# colours
SKY_TOP = (105, 175, 255)
SKY_BOTTOM = (205, 238, 255)
HILL_FAR = (150, 200, 170)
HILL_NEAR = (110, 175, 120)
GRASS = (92, 196, 84)
GRASS_DARK = (62, 150, 62)
DIRT = (152, 102, 62)
DIRT_DARK = (112, 74, 44)
PIT = (22, 18, 28)
WATER = (40, 120, 220)
WATER_LIGHT = (140, 200, 255)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
TEXT_DARK = (35, 40, 60)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def lerp_color(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def jump_velocity(charge):
    """Map a 0..1 charge to (horizontal speed, upward speed)."""
    return (MIN_VX + (MAX_VX - MIN_VX) * charge,
            MIN_VY + (MAX_VY - MIN_VY) * charge)


# ---------------------------------------------------------------- world
class Segment:
    """A horizontal slice of the level: 'ground', 'gap' or 'water'."""

    def __init__(self, kind, x0, x1):
        self.kind, self.x0, self.x1 = kind, x0, x1


class Obstacle:
    def __init__(self, kind, x, w, h):
        self.kind, self.x, self.w, self.h = kind, x, w, h
        # pre-baked jagged outline for rocks so they don't wobble each frame
        rnd = random.Random(int(x))
        self.rock_pts = []
        n = 9
        for i in range(n + 1):
            a = math.pi * i / n
            r = 1 - rnd.uniform(0, 0.18)
            self.rock_pts.append((0.5 - 0.5 * math.cos(a) * r, 1 - math.sin(a) * r))

    @property
    def hitbox(self):
        shrink = 6 if self.kind in ("rock", "spikes") else 2
        return pygame.Rect(self.x + shrink, GROUND_Y - self.h + shrink,
                           self.w - 2 * shrink, self.h - shrink)


class World:
    def __init__(self):
        self.segments = [Segment("ground", -600, 480)]
        self.obstacles = []
        self.end_x = 480

    def generate_until(self, limit):
        while self.end_x < limit:
            diff = clamp(self.end_x / 9000, 0, 1)   # gets harder with distance
            # hazard
            hz_w = random.randint(int(70 + 60 * diff), int(170 + 180 * diff))
            kind = random.choice(["gap", "water"])
            self.segments.append(Segment(kind, self.end_x, self.end_x + hz_w))
            self.end_x += hz_w
            # landing ground
            gw = random.randint(int(240 - 60 * diff), 460)
            seg = Segment("ground", self.end_x, self.end_x + gw)
            self.segments.append(seg)
            if gw >= 320 and random.random() < 0.35 + 0.45 * diff:
                okind = random.choice(["rock", "crate", "spikes"])
                if okind == "rock":
                    ow, oh = random.randint(40, 60), random.randint(30, 55)
                elif okind == "crate":
                    ow = random.choice([40, 46])
                    stack = 2 if (diff > 0.3 and gw >= 400 and random.random() < 0.5) else 1
                    oh = ow * stack
                else:
                    ow, oh = random.choice([48, 72, 96]), 26
                # keep obstacles in the middle so there's room on both sides
                lo = int(seg.x0 + gw * 0.35)
                hi = max(lo, int(seg.x1 - gw * 0.35 - ow))
                ox = random.randint(lo, hi)
                self.obstacles.append(Obstacle(okind, ox, ow, oh))
            self.end_x += gw

    def segment_at(self, x):
        for s in self.segments:
            if s.x0 <= x < s.x1:
                return s
        return None

    def prune(self, cam_x):
        self.segments = [s for s in self.segments if s.x1 > cam_x - 600]
        self.obstacles = [o for o in self.obstacles if o.x + o.w > cam_x - 600]


# ---------------------------------------------------------------- effects
class Particle:
    def __init__(self, x, y, vx, vy, life, color, size, grav=0.3, shape="circle"):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.life = self.max_life = life
        self.color, self.size, self.grav, self.shape = color, size, grav, shape

    def update(self):
        self.vx *= 0.98
        self.vy += self.grav
        self.x += self.vx
        self.y += self.vy
        self.life -= 1

    def draw(self, surf, cam_x, off):
        k = self.life / self.max_life
        r = max(1, self.size * (0.4 + 0.6 * k))
        sx, sy = self.x - cam_x + off[0], self.y + off[1]
        if self.shape == "star":
            pts = []
            for i in range(8):
                a = i * math.pi / 4 + self.life * 0.2
                rr = r * (1.0 if i % 2 == 0 else 0.4)
                pts.append((sx + math.cos(a) * rr, sy + math.sin(a) * rr))
            pygame.draw.polygon(surf, self.color, pts)
        elif self.shape == "ring":
            pygame.draw.circle(surf, self.color, (int(sx), int(sy)), int(r), 1)
        else:
            pygame.draw.circle(surf, self.color, (int(sx), int(sy)), int(r))


class FloatText:
    def __init__(self, text, x, y, color):
        self.text, self.x, self.y, self.color = text, x, y, color
        self.life = 60


# ---------------------------------------------------------------- player
class Player:
    def __init__(self):
        self.x = 160.0
        self.y = float(GROUND_Y)
        self.vx = self.vy = 0.0
        self.state = "ground"      # ground, air, fall, sink, crash
        self.charging = False
        self.charge = 0.0
        self.facing = 1
        self.walk_phase = 0.0
        self.walking = False
        self.angle = 0.0
        self.flipping = False
        self.spin_rate = 0.0
        self.land_squash = 1.0
        self.jump_charge = 0.0
        self.dead_seg = None

    def rect_at(self, x, y):
        return pygame.Rect(x - PLAYER_HALF_W, y - PLAYER_H, PLAYER_HALF_W * 2, PLAYER_H)


def build_player_sprite(pose, phase, facing, dead=False):
    """Draw the little runner onto a 70x90 surface. Feet sit at y=88."""
    s = pygame.Surface((70, 90), pygame.SRCALPHA)
    f = facing
    cx = 35
    hip = (cx, 60)
    shoulder = (cx, 42)
    pants, pants_back = (55, 70, 140), (40, 50, 105)
    shirt = (235, 92, 62)
    skin, skin_back = (255, 212, 172), (225, 180, 145)
    shoe = (40, 35, 40)

    # ---- leg & arm targets for each pose: list of (knee, foot), (elbow, hand)
    if pose == "walk":
        a = math.sin(phase) * 0.65
        legs = []
        for ang in (a, -a):
            knee = (hip[0] + math.sin(ang) * 13 * f, hip[1] + 12)
            foot = (hip[0] + math.sin(ang) * 22 * f, 86 - max(0, -math.cos(phase)) * 2)
            legs.append((knee, foot))
        arms = []
        for ang in (-a, a):
            elbow = (shoulder[0] + math.sin(ang) * 8 * f, shoulder[1] + 10)
            hand = (shoulder[0] + math.sin(ang) * 15 * f, shoulder[1] + 18)
            arms.append((elbow, hand))
    elif pose == "crouch":
        legs = [((cx + 11 * f, 70), (cx + 6 * f, 86)), ((cx - 2 * f, 72), (cx - 6 * f, 86))]
        arms = [((cx - 10 * f, 48), (cx - 18 * f, 54)), ((cx - 7 * f, 50), (cx - 15 * f, 57))]
    elif pose == "air":
        legs = [((cx + 12 * f, 66), (cx + 4 * f, 78)), ((cx + 6 * f, 70), (cx - 4 * f, 80))]
        arms = [((cx + 10 * f, 32), (cx + 14 * f, 20)), ((cx - 8 * f, 32), (cx - 12 * f, 20))]
    elif pose == "flail":
        w = math.sin(phase * 2) * 8
        legs = [((cx + 8, 72 + w * 0.3), (cx + 14, 84)), ((cx - 8, 72 - w * 0.3), (cx - 14, 84))]
        arms = [((cx + 12, 34 + w), (cx + 20, 24 + w)), ((cx - 12, 34 - w), (cx - 20, 24 - w))]
    else:  # stand / idle
        legs = [((cx + 4 * f, 73), (cx + 5 * f, 86)), ((cx - 4 * f, 73), (cx - 5 * f, 86))]
        arms = [((cx + 6 * f, 51), (cx + 8 * f, 59)), ((cx - 6 * f, 51), (cx - 8 * f, 59))]

    def limb(start, mid, end, color, width):
        pygame.draw.line(s, color, start, mid, width)
        pygame.draw.line(s, color, mid, end, width)
        pygame.draw.circle(s, color, (int(mid[0]), int(mid[1])), width // 2)

    # back limbs (darker) first
    limb(hip, legs[1][0], legs[1][1], pants_back, 7)
    pygame.draw.ellipse(s, shoe, (legs[1][1][0] - 5 + 2 * f, legs[1][1][1] - 3, 10, 6))
    limb(shoulder, arms[1][0], arms[1][1], skin_back, 5)

    # body
    pygame.draw.rect(s, shirt, (cx - 11, 34, 22, 30), border_radius=8)
    pygame.draw.rect(s, (200, 70, 50), (cx - 11, 56, 22, 6), border_radius=3)  # belt

    # front limbs
    limb(hip, legs[0][0], legs[0][1], pants, 7)
    pygame.draw.ellipse(s, shoe, (legs[0][1][0] - 5 + 2 * f, legs[0][1][1] - 3, 10, 6))
    limb(shoulder, arms[0][0], arms[0][1], skin, 5)

    # head
    head = (cx, 22)
    pygame.draw.circle(s, skin, head, 13)
    # cap
    pygame.draw.circle(s, (40, 110, 210), head, 13, draw_top_left=True, draw_top_right=True)
    pygame.draw.rect(s, (40, 110, 210), (cx - 13, 20, 26, 3))
    visor_x = cx + 6 if f > 0 else cx - 20
    pygame.draw.rect(s, (30, 85, 170), (visor_x, 20, 14, 4), border_radius=2)
    # face
    ex = cx + 5 * f
    if dead:
        pygame.draw.line(s, BLACK, (ex - 3, 22), (ex + 3, 28), 2)
        pygame.draw.line(s, BLACK, (ex + 3, 22), (ex - 3, 28), 2)
    else:
        pygame.draw.circle(s, WHITE, (ex, 26), 4)
        pygame.draw.circle(s, BLACK, (ex + f, 26), 2)
        pygame.draw.line(s, (150, 80, 70), (cx + 2 * f, 32), (cx + 8 * f, 31), 2)
    return s


# ---------------------------------------------------------------- game
class Game:
    def __init__(self, screen):
        self.screen = screen
        self.clock = pygame.time.Clock()
        self.font_big = pygame.font.Font(None, 84)
        self.font_med = pygame.font.Font(None, 42)
        self.font_small = pygame.font.Font(None, 28)
        self.button_rect = pygame.Rect(W - 175, H - 105, 150, 80)
        self.sky = self._make_sky()
        self.clouds = [[random.uniform(0, W + 400), random.uniform(30, 200),
                        random.uniform(0.6, 1.4), random.uniform(0.1, 0.35)] for _ in range(7)]
        self.best = 0
        self.mode = "title"   # title, play, dying, over
        self.reset()

    # ---------- setup
    def _make_sky(self):
        surf = pygame.Surface((W, H))
        for y in range(H):
            pygame.draw.line(surf, lerp_color(SKY_TOP, SKY_BOTTOM, y / H), (0, y), (W, y))
        return surf

    def reset(self):
        self.world = World()
        self.player = Player()
        self.cam_x = self.player.x - 280
        self.world.generate_until(self.cam_x + W + 800)
        self.particles = []
        self.texts = []
        self.shake = 0.0
        self.t = 0
        self.distance = 0
        self.jumps = 0
        self.death_reason = ""
        self.death_timer = 0
        self.button_down = False

    def start(self):
        self.reset()
        self.mode = "play"

    # ---------- input
    def press(self):
        if self.mode in ("title", "over"):
            self.start()
            return
        p = self.player
        if self.mode == "play" and p.state == "ground" and not p.charging:
            p.charging = True
            p.charge = 0.0
            self.button_down = True

    def release(self):
        self.button_down = False
        p = self.player
        if self.mode == "play" and p.charging and p.state == "ground":
            self.do_jump(p.charge)
        p.charging = False

    def handle_event(self, e):
        if e.type == pygame.QUIT:
            return False
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                return False
            if e.key in (pygame.K_SPACE, pygame.K_w, pygame.K_UP):
                self.press()
            elif e.key == pygame.K_r and self.mode == "over":
                self.start()
        elif e.type == pygame.KEYUP and e.key in (pygame.K_SPACE, pygame.K_w, pygame.K_UP):
            self.release()
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.mode in ("title", "over") or self.button_rect.collidepoint(e.pos):
                self.press()
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            self.release()
        return True

    # ---------- actions
    def do_jump(self, charge):
        p = self.player
        vx, vy = jump_velocity(charge)
        p.vx, p.vy = vx * p.facing, -vy
        p.state = "air"
        p.jump_charge = charge
        p.charge = 0.0
        airtime = 2 * vy / GRAVITY
        p.flipping = charge >= FLIP_THRESHOLD
        p.spin_rate = -360.0 / airtime * p.facing
        p.angle = 0.0
        self.jumps += 1
        for _ in range(8):
            self.particles.append(Particle(p.x, GROUND_Y, random.uniform(-2, 2) - p.facing,
                                           random.uniform(-2, -0.5), 25, (200, 175, 130),
                                           random.uniform(3, 6), 0.1))

    def land(self, seg):
        p = self.player
        p.state = "ground"
        p.y = GROUND_Y
        p.vx = p.vy = 0
        p.angle = 0
        p.flipping = False
        p.land_squash = 0.62
        strength = 6 + int(p.jump_charge * 10)
        for _ in range(strength):
            self.particles.append(Particle(p.x + random.uniform(-10, 10), GROUND_Y,
                                           random.uniform(-3, 3), random.uniform(-2.5, -0.5), 28,
                                           (205, 180, 135), random.uniform(3, 7), 0.12))
        if p.jump_charge > 0.6:
            self.shake = max(self.shake, 4)
        # little rewards
        edge_dist = min(p.x - seg.x0, seg.x1 - p.x)
        if edge_dist < 22:
            self.texts.append(FloatText("Close one!", p.x, GROUND_Y - 80, (255, 220, 60)))
        elif p.jump_charge >= FLIP_THRESHOLD:
            self.texts.append(FloatText("Flip!", p.x, GROUND_Y - 80, (255, 255, 255)))

    def kill(self, seg):
        p = self.player
        p.charging = False
        p.dead_seg = seg
        self.mode = "dying"
        self.death_timer = 0
        if seg is not None and seg.kind == "water":
            p.state = "sink"
            p.vy = 1.2
            self.death_reason = "Splash! You fell in the water."
            sy = GROUND_Y + 20
            for _ in range(32):
                self.particles.append(Particle(p.x + random.uniform(-12, 12), sy,
                                               random.uniform(-3.5, 3.5), random.uniform(-9, -3), 45,
                                               random.choice([WATER_LIGHT, WHITE, (90, 160, 240)]),
                                               random.uniform(3, 6), 0.35))
            for r in range(3):
                self.particles.append(Particle(p.x, sy, 0, 0, 40 + r * 10, WHITE, 6 + r * 6, 0, "ring"))
            self.shake = 6
        else:
            p.state = "fall"
            self.death_reason = "Whoops! You fell into a pit."

    def crash(self, obstacle):
        p = self.player
        p.state = "crash"
        p.charging = False
        p.vx = -p.facing * 3.5
        p.vy = -6
        p.flipping = False
        self.mode = "dying"
        self.death_timer = 0
        names = {"rock": "Bonk! You smacked into a rock.",
                 "crate": "Thud! You hit a crate.",
                 "spikes": "Ouch! You landed on spikes."}
        self.death_reason = names[obstacle.kind]
        self.shake = 14
        for _ in range(14):
            self.particles.append(Particle(p.x + p.facing * 10, p.y - 30,
                                           random.uniform(-4, 4), random.uniform(-6, -1), 40,
                                           random.choice([(255, 230, 60), (255, 180, 40), WHITE]),
                                           random.uniform(5, 9), 0.25, "star"))

    def hits_obstacle(self, rect):
        for o in self.world.obstacles:
            if rect.colliderect(o.hitbox):
                return o
        return None

    # ---------- update
    def update(self):
        self.t += 1
        for c in self.clouds:
            c[0] -= c[3]
            if c[0] < -300:
                c[0] = W + random.uniform(100, 400)
                c[1] = random.uniform(30, 200)

        if self.mode == "title":
            return

        p = self.player
        keys = pygame.key.get_pressed()

        if p.state == "ground":
            move = 0
            if self.mode == "play" and not p.charging:
                if keys[pygame.K_LEFT] or keys[pygame.K_a]:
                    move -= 1
                if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                    move += 1
            p.walking = move != 0
            if move:
                p.facing = move
                nx = p.x + move * WALK_SPEED
                if not self.hits_obstacle(p.rect_at(nx, p.y)):
                    p.x = nx
                    p.walk_phase += 0.28
                seg = self.world.segment_at(p.x)
                if seg is None or seg.kind != "ground":
                    p.vx = move * 1.5
                    self.kill(seg)
            if p.charging:
                p.charge = min(1.0, p.charge + 1.0 / (CHARGE_TIME * FPS))
                if p.charge >= 1.0 and self.t % 3 == 0:
                    self.particles.append(Particle(p.x + random.uniform(-18, 18), p.y - random.uniform(0, 45),
                                                   0, random.uniform(-1.5, -0.5), 22, (255, 240, 120), 3, 0, "star"))
            p.land_squash += (1 - p.land_squash) * 0.18

        elif p.state == "air":
            p.vy += GRAVITY
            p.x += p.vx
            p.y += p.vy
            if p.flipping:
                p.angle += p.spin_rate
            else:
                p.angle = clamp(-p.vy * 1.8, -22, 22) * p.facing
            if self.t % 2 == 0:  # motion trail
                self.particles.append(Particle(p.x, p.y - 25, 0, 0, 12, (255, 255, 255),
                                               3 + 4 * p.jump_charge, 0))
            ob = self.hits_obstacle(p.rect_at(p.x, p.y))
            if ob:
                self.crash(ob)
            elif p.vy > 0 and p.y >= GROUND_Y:
                seg = self.world.segment_at(p.x)
                if seg and seg.kind == "ground":
                    self.land(seg)
                else:
                    self.kill(seg)

        elif p.state == "fall":
            p.vy += GRAVITY
            p.x += p.vx * 0.5
            p.y += p.vy
            p.angle += 6 * p.facing
            if p.dead_seg:
                p.x = clamp(p.x, p.dead_seg.x0 + PLAYER_HALF_W, p.dead_seg.x1 - PLAYER_HALF_W)

        elif p.state == "sink":
            p.y += p.vy
            p.vy = max(0.6, p.vy * 0.97)
            p.x += p.vx * 0.2
            p.angle += (12 * p.facing - p.angle) * 0.05
            if p.dead_seg:
                p.x = clamp(p.x, p.dead_seg.x0 + PLAYER_HALF_W, p.dead_seg.x1 - PLAYER_HALF_W)
            if self.t % 6 == 0 and p.y < H + 40:
                self.particles.append(Particle(p.x + random.uniform(-8, 8), p.y - 40, 0,
                                               -1.2, 40, WATER_LIGHT, random.uniform(2, 4), -0.02, "ring"))

        elif p.state == "crash":
            p.vy += GRAVITY
            p.x += p.vx
            p.y += p.vy
            p.angle += 9 * p.facing
            if p.vy > 0 and p.y >= GROUND_Y:
                seg = self.world.segment_at(p.x)
                if seg and seg.kind == "ground" and p.y < GROUND_Y + 20:
                    p.y = GROUND_Y
                    p.vy = -abs(p.vy) * 0.35
                    p.vx *= 0.6
                    if abs(p.vy) < 1:
                        p.vy = 0
                        p.angle = 90 * -p.facing
                        p.state = "ko"

        # distance score
        if self.mode == "play":
            self.distance = max(self.distance, int((p.x - 160) / 20))

        # death timing
        if self.mode == "dying":
            self.death_timer += 1
            if self.death_timer > 100:
                self.mode = "over"
                self.best = max(self.best, self.distance)

        # camera
        lead = 280 if p.facing > 0 else 520
        target = p.x - lead
        self.cam_x += (target - self.cam_x) * (0.08 if self.mode == "play" else 0.03)
        self.world.generate_until(self.cam_x + W + 800)
        self.world.prune(self.cam_x)

        # effects
        for part in self.particles:
            part.update()
        self.particles = [q for q in self.particles if q.life > 0]
        for ft in self.texts:
            ft.life -= 1
            ft.y -= 1
        self.texts = [ft for ft in self.texts if ft.life > 0]
        self.shake *= 0.85

    # ---------- drawing
    def draw_cloud(self, x, y, s):
        for dx, dy, r in ((0, 0, 26), (28, -10, 32), (60, 0, 26), (30, 8, 26)):
            pygame.draw.circle(self.screen, WHITE, (int(x + dx * s), int(y + dy * s)), int(r * s))

    def draw_hills(self, factor, base, amp, color):
        pts = [(0, H)]
        for x in range(0, W + 41, 40):
            wx = x + self.cam_x * factor
            y = base + math.sin(wx * 0.004) * amp + math.sin(wx * 0.011) * amp * 0.45
            pts.append((x, y))
        pts.append((W, H))
        pygame.draw.polygon(self.screen, color, pts)

    def draw_ground(self, seg, off):
        sx0 = int(seg.x0 - self.cam_x + off[0])
        sx1 = int(seg.x1 - self.cam_x + off[0])
        gy = GROUND_Y + off[1]
        w = sx1 - sx0
        if seg.kind == "ground":
            pygame.draw.rect(self.screen, DIRT, (sx0, gy, w, H - gy + 20))
            # dirt specks
            start = int(seg.x0 // 37) * 37
            for wx in range(start, int(seg.x1), 37):
                if wx < seg.x0 + 8 or wx > seg.x1 - 8:
                    continue
                py = gy + 30 + (wx * 7919) % 90
                pygame.draw.circle(self.screen, DIRT_DARK, (int(wx - self.cam_x + off[0]), py), 3)
            pygame.draw.rect(self.screen, GRASS_DARK, (sx0, gy, w, 16))
            pygame.draw.rect(self.screen, GRASS, (sx0, gy, w, 12))
            # grass tufts
            start = int(seg.x0 // 22) * 22
            for wx in range(start, int(seg.x1), 22):
                if wx < seg.x0 + 4 or wx > seg.x1 - 10:
                    continue
                x = wx - self.cam_x + off[0]
                sway = math.sin(self.t * 0.05 + wx) * 1.5
                pygame.draw.polygon(self.screen, GRASS, [(x, gy + 2), (x + 3 + sway, gy - 7), (x + 6, gy + 2)])
            # cliff edges
            pygame.draw.rect(self.screen, DIRT_DARK, (sx0, gy + 12, 5, H))
            pygame.draw.rect(self.screen, DIRT_DARK, (sx1 - 5, gy + 12, 5, H))
        elif seg.kind == "gap":
            pygame.draw.rect(self.screen, PIT, (sx0, gy, w, H - gy + 20))
            for i in range(4):
                c = lerp_color(DIRT_DARK, PIT, (i + 1) / 5)
                pygame.draw.rect(self.screen, c, (sx0, gy + i * 10, w, 10))
        elif seg.kind == "water":
            pygame.draw.rect(self.screen, DIRT_DARK, (sx0, gy, w, H - gy + 20))

    def draw_water(self, seg, off):
        sx0 = seg.x0 - self.cam_x + off[0]
        w = int(seg.x1 - seg.x0)
        top = GROUND_Y + 20 + off[1]
        surf = pygame.Surface((w, H - top + 30), pygame.SRCALPHA)
        pts = [(0, surf.get_height())]
        for x in range(0, w + 1, 8):
            wx = seg.x0 + x
            y = 6 + math.sin(self.t * 0.08 + wx * 0.05) * 3 + math.sin(self.t * 0.05 + wx * 0.11) * 1.5
            pts.append((x, y))
        pts.append((w, surf.get_height()))
        pygame.draw.polygon(surf, (*WATER, 215), pts)
        pygame.draw.lines(surf, (*WATER_LIGHT, 255), False, pts[1:-1], 3)
        # sparkles
        for i in range(w // 50):
            x = (i * 53 + self.t) % max(1, w)
            y = 18 + (i * 29) % 40
            pygame.draw.line(surf, (*WATER_LIGHT, 150), (x, y), (x + 8, y), 2)
        self.screen.blit(surf, (sx0, top - 6))

    def draw_obstacle(self, o, off):
        x = o.x - self.cam_x + off[0]
        y = GROUND_Y - o.h + off[1]
        if o.kind == "rock":
            pts = [(x + px * o.w, y + py * o.h) for px, py in o.rock_pts]
            pygame.draw.polygon(self.screen, (120, 120, 130), pts)
            pygame.draw.polygon(self.screen, (80, 80, 90), pts, 3)
            pygame.draw.circle(self.screen, (160, 160, 170), (int(x + o.w * 0.35), int(y + o.h * 0.35)), max(3, o.w // 8))
        elif o.kind == "crate":
            for i in range(o.h // o.w):
                r = pygame.Rect(x, GROUND_Y + off[1] - (i + 1) * o.w, o.w, o.w)
                pygame.draw.rect(self.screen, (190, 135, 70), r)
                pygame.draw.rect(self.screen, (120, 80, 40), r, 4)
                pygame.draw.line(self.screen, (120, 80, 40), r.topleft, r.bottomright, 4)
                pygame.draw.line(self.screen, (120, 80, 40), r.topright, r.bottomleft, 4)
        elif o.kind == "spikes":
            pygame.draw.rect(self.screen, (90, 90, 100), (x, GROUND_Y - 6 + off[1], o.w, 6))
            n = o.w // 12
            for i in range(n):
                bx = x + i * 12
                tri = [(bx, GROUND_Y - 4 + off[1]), (bx + 6, y), (bx + 12, GROUND_Y - 4 + off[1])]
                pygame.draw.polygon(self.screen, (200, 205, 215), tri)
                pygame.draw.polygon(self.screen, (100, 100, 115), tri, 2)

    def draw_trajectory_hint(self, off):
        """Short dotted preview of the jump arc while charging."""
        p = self.player
        vx, vy = jump_velocity(p.charge)
        vx *= p.facing
        vy = -vy
        x, y = p.x, GROUND_Y - 25
        steps = int((2 * -vy / GRAVITY) * 0.32)
        for i in range(steps):
            vy += GRAVITY
            x += vx
            y += vy
            if i % 3 == 0:
                fade = 1 - i / max(1, steps)
                col = lerp_color((255, 255, 255), SKY_BOTTOM, 1 - fade)
                pygame.draw.circle(self.screen, col, (int(x - self.cam_x + off[0]), int(y + off[1])), 3)

    def draw_player(self, off):
        p = self.player
        dead = p.state in ("crash", "ko", "fall", "sink")
        if p.state == "ground":
            if p.charging:
                pose = "crouch"
            elif p.walking:
                pose = "walk"
            else:
                pose = "stand"
        elif p.state == "air":
            pose = "air"
        elif p.state in ("fall", "sink", "crash"):
            pose = "flail"
        else:
            pose = "stand"
        sprite = build_player_sprite(pose, self.t * 0.3 if pose == "flail" else p.walk_phase,
                                     p.facing, dead=dead)

        # squash & stretch
        sqx = sqy = 1.0
        if p.state == "ground":
            if p.charging:
                sqy = 1 - 0.28 * p.charge
                sqx = 1 + 0.18 * p.charge
            else:
                sqy = p.land_squash
                sqx = 2 - p.land_squash
                if not p.walking:  # idle breathing
                    sqy *= 1 + math.sin(self.t * 0.08) * 0.02
        elif p.state == "air":
            st = clamp(abs(p.vy) / 14, 0, 1) * 0.12
            sqy, sqx = 1 + st, 1 - st * 0.6

        sw, sh = max(1, int(70 * sqx)), max(1, int(90 * sqy))
        img = pygame.transform.smoothscale(sprite, (sw, sh))
        if p.angle:
            img = pygame.transform.rotate(img, p.angle)

        jitter = 0
        if p.charging and p.charge >= 1:
            jitter = random.uniform(-1.5, 1.5)
        sx = p.x - self.cam_x + off[0] + jitter
        sy = p.y + off[1]
        # shadow on solid ground
        if p.state in ("ground", "air", "crash", "ko"):
            seg = self.world.segment_at(p.x)
            if seg and seg.kind == "ground" and p.y <= GROUND_Y + 1:
                height = GROUND_Y - p.y
                sw2 = max(8, 34 - height * 0.08)
                sh_surf = pygame.Surface((int(sw2), 8), pygame.SRCALPHA)
                pygame.draw.ellipse(sh_surf, (0, 0, 0, 70), sh_surf.get_rect())
                self.screen.blit(sh_surf, (sx - sw2 / 2, GROUND_Y + off[1] - 4))
        rect = img.get_rect(center=(sx, sy - 43 * sqy))
        self.screen.blit(img, rect)

        # power meter above the head
        if p.charging:
            bw, bh = 56, 9
            bx, by = sx - bw / 2, sy - 90 * sqy - 14
            pygame.draw.rect(self.screen, (30, 30, 40), (bx - 2, by - 2, bw + 4, bh + 4), border_radius=5)
            col = lerp_color((90, 220, 90), (255, 210, 50), min(1, p.charge * 2)) if p.charge < 0.5 \
                else lerp_color((255, 210, 50), (240, 70, 50), (p.charge - 0.5) * 2)
            pygame.draw.rect(self.screen, col, (bx, by, bw * p.charge, bh), border_radius=4)

    def draw_button(self):
        r = self.button_rect
        pressed = self.button_down and self.player.charging
        rr = r.move(0, 4) if pressed else r
        if not pressed:
            pygame.draw.rect(self.screen, (150, 40, 30), r.move(0, 6), border_radius=18)
        pygame.draw.rect(self.screen, (235, 75, 55), rr, border_radius=18)
        # charge fill rising inside the button
        ch = self.player.charge if self.player.charging else 0
        if ch > 0:
            fill = pygame.Rect(rr.x, rr.bottom - rr.h * ch, rr.w, rr.h * ch)
            fill_surf = pygame.Surface(fill.size, pygame.SRCALPHA)
            pygame.draw.rect(fill_surf, (255, 220, 70, 170), fill_surf.get_rect(), border_radius=18)
            self.screen.blit(fill_surf, fill.topleft)
        pygame.draw.rect(self.screen, (255, 255, 255), rr, 3, border_radius=18)
        label = self.font_med.render("JUMP", True, WHITE)
        self.screen.blit(label, label.get_rect(center=rr.center))
        hint = self.font_small.render("hold & release", True, WHITE)
        self.screen.blit(hint, hint.get_rect(midbottom=(r.centerx, r.top - 6)))

    def text_center(self, text, font, y, color=WHITE, shadow=True):
        if shadow:
            s = font.render(text, True, (20, 25, 45))
            self.screen.blit(s, s.get_rect(center=(W // 2 + 3, y + 3)))
        s = font.render(text, True, color)
        self.screen.blit(s, s.get_rect(center=(W // 2, y)))

    def draw(self):
        off = (random.uniform(-self.shake, self.shake), random.uniform(-self.shake, self.shake)) \
            if self.shake > 0.5 else (0, 0)
        scr = self.screen
        scr.blit(self.sky, (0, 0))
        pygame.draw.circle(scr, (255, 245, 190), (W - 140, 90), 48)
        pygame.draw.circle(scr, (255, 235, 140), (W - 140, 90), 40)
        for c in self.clouds:
            x = (c[0] - self.cam_x * 0.05) % (W + 400) - 200
            self.draw_cloud(x, c[1], c[2])
        self.draw_hills(0.15, 300, 40, HILL_FAR)
        self.draw_hills(0.4, 345, 30, HILL_NEAR)

        visible = [s for s in self.world.segments
                   if s.x1 > self.cam_x - 50 and s.x0 < self.cam_x + W + 50]
        for seg in visible:
            self.draw_ground(seg, off)
        for o in self.world.obstacles:
            if self.cam_x - 100 < o.x < self.cam_x + W + 100:
                self.draw_obstacle(o, off)

        if self.player.charging:
            self.draw_trajectory_hint(off)
        self.draw_player(off)

        for seg in visible:
            if seg.kind == "water":
                self.draw_water(seg, off)
        for part in self.particles:
            part.draw(scr, self.cam_x, off)
        for ft in self.texts:
            s = self.font_med.render(ft.text, True, ft.color)
            s.set_alpha(int(255 * ft.life / 60))
            scr.blit(s, s.get_rect(center=(ft.x - self.cam_x, ft.y)))

        # HUD
        if self.mode != "title":
            d = self.font_med.render(f"Distance: {self.distance} m", True, WHITE)
            scr.blit(self.font_med.render(f"Distance: {self.distance} m", True, TEXT_DARK), (22, 20))
            scr.blit(d, (20, 18))
            b = self.font_small.render(f"Best: {self.best} m   Jumps: {self.jumps}", True, TEXT_DARK)
            scr.blit(b, (22, 56))
            self.draw_button()
            tip = self.font_small.render("SPACE also works  -  A/D to step", True, (240, 230, 210))
            scr.blit(tip, (20, H - 34))

        if self.mode == "title":
            shade = pygame.Surface((W, H), pygame.SRCALPHA)
            shade.fill((10, 20, 50, 110))
            scr.blit(shade, (0, 0))
            bob = math.sin(self.t * 0.06) * 6
            self.text_center("LEAP RUNNER", self.font_big, 150 + bob, (255, 230, 90))
            self.text_center("Hold JUMP to charge, release to leap.", self.font_med, 240)
            self.text_center("The longer you hold, the farther you fly.", self.font_med, 280)
            self.text_center("Clear the pits, water and obstacles!", self.font_med, 320)
            if (self.t // 30) % 2 == 0:
                self.text_center("Click or press SPACE to start", self.font_med, 400, (255, 230, 90))

        if self.mode == "over":
            shade = pygame.Surface((W, H), pygame.SRCALPHA)
            shade.fill((10, 10, 30, 140))
            scr.blit(shade, (0, 0))
            panel = pygame.Rect(0, 0, 560, 300)
            panel.center = (W // 2, H // 2 - 10)
            pygame.draw.rect(scr, (250, 245, 235), panel, border_radius=20)
            pygame.draw.rect(scr, (235, 75, 55), panel, 5, border_radius=20)
            title = self.font_big.render("GAME OVER", True, (235, 75, 55))
            scr.blit(title, title.get_rect(center=(W // 2, panel.top + 55)))
            for i, line in enumerate([self.death_reason,
                                      f"Distance: {self.distance} m    Jumps: {self.jumps}",
                                      f"Best: {self.best} m" + ("   NEW RECORD!" if self.distance >= self.best and self.distance > 0 else "")]):
                s = self.font_small.render(line, True, TEXT_DARK)
                scr.blit(s, s.get_rect(center=(W // 2, panel.top + 120 + i * 36)))
            if (self.t // 30) % 2 == 0:
                s = self.font_small.render("Click, SPACE or R to try again", True, (200, 60, 45))
                scr.blit(s, s.get_rect(center=(W // 2, panel.bottom - 34)))

    # ---------- loop
    def run(self):
        running = True
        while running:
            for e in pygame.event.get():
                if not self.handle_event(e):
                    running = False
            self.update()
            self.draw()
            pygame.display.flip()
            self.clock.tick(FPS)
        pygame.quit()
        sys.exit()


def main():
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Leap Runner")
    Game(screen).run()


if __name__ == "__main__":
    main()