import app
import math
import sys
import os
import random

from events.input import Buttons, BUTTON_TYPES

try:
    from time import ticks_ms, ticks_diff
except ImportError:
    from time import time as _t
    def ticks_ms():
        return int(_t() * 1000)
    def ticks_diff(a, b):
        return a - b

if sys.implementation.name == "micropython":
    _apps = os.listdir("/apps")
    _dir = "/apps/tildenstein"
    for _d in _apps:
        if "tildenstein" in _d.lower():
            _dir = "/apps/" + _d
            break
    if _dir not in sys.path:
        sys.path.insert(0, _dir)
    ASSET_PATH = _dir + "/"
else:
    ASSET_PATH = "./"

import game_map
import engine
import net

try:
    import imu
    _HAS_IMU = True
except ImportError:
    _HAS_IMU = False

try:
    from tildagonos import tildagonos
    from system.eventbus import eventbus
    from system.patterndisplay.events import PatternDisable, PatternEnable
    _HAS_LEDS = True
except ImportError:
    _HAS_LEDS = False

STATE_TITLE = 0
STATE_CONFIG = 1
STATE_GAME = 2
STATE_DEAD = 3
STATE_CREDITS = 4

MOVE_SPEED = 1.0
IMU_REST_OFFSET = -5.5
IMU_DEAD_ACC = 0.8
IMU_DEAD_GYRO = 3.0
MOVE_INVERT = -1
TURN_INVERT = -1
DEG2RAD = 0.01745329

RAIL_CD = 500
RAIL_DMG = 25
RAIL_RANGE = 20.0
HIT_ANGLE = 0.087

JUMP_DUR = 300
JUMP_CD = 1000
REGEN_DELAY = 5000
BCAST_INT = 200


class TildensteinApp(app.App):
    def __init__(self):
        self.button_states = Buttons(self)
        self.state = STATE_TITLE

        self.px = 16.0
        self.py = 16.0
        self.pa = 0.0
        self.health = 100
        self.kills = 0
        self.deaths = 0

        self.player_name = self._load_name()
        self.cfg_chars = list((self.player_name + "      ")[:6])
        self.cfg_pos = 0

        self.shoot_cd = 0
        self.jump_t = 0
        self.jump_cd = 0
        self.last_dmg_time = 0
        self.regen_acc = 0
        self.dead_t = 0
        self.flash_t = 0
        self.hit_flash = 0

        self.kill_feed = ""
        self.feed_t = 0
        self.water_acc = 0

        self.net_mgr = net.NetManager()
        self.bcast_t = 0
        self._net_dmg = 0
        self._led_offset = 0
        self._led_chase_t = 0

        self.columns = [(32.0, 0, 0, 0.0)] * engine.NUM_COLS
        self.title_pulse = 0.0
        self.tilt_x = 0.0
        self.tilt_y = 0.0

        if _HAS_LEDS:
            eventbus.emit(PatternDisable())

    # --- Update dispatch ---

    def update(self, delta):
        self._up_net(delta)
        if self.state == STATE_TITLE:
            self._up_title(delta)
        elif self.state == STATE_CONFIG:
            self._up_config(delta)
        elif self.state == STATE_GAME:
            self._up_game(delta)
        elif self.state == STATE_DEAD:
            self._up_dead(delta)
        elif self.state == STATE_CREDITS:
            self._up_credits(delta)

    def _up_net(self, delta):
        self.bcast_t += delta
        if self.bcast_t >= BCAST_INT:
            fl = 0
            if self.state == STATE_GAME:
                if self.shoot_cd > RAIL_CD - 100:
                    fl |= 1
                if self.jump_t > 0:
                    fl |= 2
            self.net_mgr.broadcast(
                self.player_name, self.px, self.py,
                self.pa, self.health, fl)
            self.bcast_t = 0
        self._net_dmg = self.net_mgr.receive(self.player_name)

    def _up_title(self, delta):
        self.title_pulse += delta * 0.003
        if self.button_states.get(BUTTON_TYPES["CANCEL"]):
            self.button_states.clear()
            self._leds_restore()
            self.minimise()
            return
        if self.button_states.get(BUTTON_TYPES["LEFT"]):
            self.button_states.clear()
            self.state = STATE_CONFIG
            return
        if self.button_states.get(BUTTON_TYPES["DOWN"]):
            self.button_states.clear()
            self.state = STATE_CREDITS
            return
        for btn in ("UP", "RIGHT", "CONFIRM"):
            if self.button_states.get(BUTTON_TYPES[btn]):
                self.button_states.clear()
                self._respawn()
                self.state = STATE_GAME
                return

    def _up_config(self, delta):
        if self.button_states.get(BUTTON_TYPES["UP"]):
            self.button_states.clear()
            c = self.cfg_chars[self.cfg_pos]
            self.cfg_chars[self.cfg_pos] = chr(
                ord('a') + (ord(c) - ord('a') + 1) % 26
            ) if 'a' <= c <= 'z' else 'a'

        if self.button_states.get(BUTTON_TYPES["DOWN"]):
            self.button_states.clear()
            c = self.cfg_chars[self.cfg_pos]
            self.cfg_chars[self.cfg_pos] = chr(
                ord('a') + (ord(c) - ord('a') - 1) % 26
            ) if 'a' <= c <= 'z' else 'z'

        if self.button_states.get(BUTTON_TYPES["RIGHT"]):
            self.button_states.clear()
            self.cfg_pos = (self.cfg_pos + 1) % 6

        if self.button_states.get(BUTTON_TYPES["CONFIRM"]):
            self.button_states.clear()
            self.player_name = "".join(self.cfg_chars)
            self._save_name()
            self.state = STATE_TITLE

        if self.button_states.get(BUTTON_TYPES["CANCEL"]):
            self.button_states.clear()
            self.cfg_chars = list((self.player_name + "      ")[:6])
            self.state = STATE_TITLE

    def _up_game(self, delta):
        dt = delta * 0.001

        acc = (0.0, 0.0, 0.0)
        gyro = (0.0, 0.0, 0.0)
        if _HAS_IMU:
            try:
                acc = imu.acc_read()
                gyro = imu.gyro_read()
            except Exception:
                pass

        # Turning
        gz = gyro[2] * TURN_INVERT
        if abs(gz) > IMU_DEAD_GYRO:
            self.pa += (gz - (IMU_DEAD_GYRO if gz > 0 else -IMU_DEAD_GYRO)
                        ) * DEG2RAD * dt

        # Movement (offset compensates for badge resting angle on lanyard)
        ay = acc[0] * MOVE_INVERT - IMU_REST_OFFSET
        if abs(ay) > IMU_DEAD_ACC:
            inp = ay - (IMU_DEAD_ACC if ay > 0 else -IMU_DEAD_ACC)
            spd = inp * MOVE_SPEED * dt
            if self.jump_t > 0:
                spd *= 1.5
            nx = self.px + math.cos(self.pa) * spd
            ny = self.py + math.sin(self.pa) * spd
            self.px, self.py = game_map.try_move(self.px, self.py, nx, ny)

        # Shoot (B = RIGHT)
        if self.button_states.get(BUTTON_TYPES["RIGHT"]):
            self.button_states.clear()
            if self.shoot_cd <= 0:
                self._shoot()
                self.shoot_cd = RAIL_CD

        # Jump (F = CANCEL)
        if self.button_states.get(BUTTON_TYPES["CANCEL"]):
            self.button_states.clear()
            if self.jump_t <= 0 and self.jump_cd <= 0:
                self.jump_t = JUMP_DUR

        # Config (E = LEFT)
        if self.button_states.get(BUTTON_TYPES["LEFT"]):
            self.button_states.clear()
            self.state = STATE_CONFIG
            return

        # Pause (C = CONFIRM)
        if self.button_states.get(BUTTON_TYPES["CONFIRM"]):
            self.button_states.clear()
            self.state = STATE_TITLE
            return

        # Timers
        if self.shoot_cd > 0:
            self.shoot_cd -= delta
        if self.jump_t > 0:
            self.jump_t -= delta
            if self.jump_t <= 0:
                self.jump_cd = JUMP_CD
        if self.jump_cd > 0:
            self.jump_cd -= delta
        if self.flash_t > 0:
            self.flash_t -= delta
        if self.hit_flash > 0:
            self.hit_flash -= 1
        if self.feed_t > 0:
            self.feed_t -= 1
        else:
            self.kill_feed = ""

        if game_map.get_ground(self.px, self.py) == 1:
            self.water_acc += delta
            if self.water_acc >= 1000:
                self.water_acc -= 1000
                self.health -= 5
                self.last_dmg_time = ticks_ms()
                self.hit_flash = 3
                if self.health <= 0:
                    self.health = 0
                    self.deaths += 1
                    self.state = STATE_DEAD
                    self.dead_t = 3000
                    return
        else:
            self.water_acc = 0

        dmg = self._net_dmg
        if dmg > 0 and self.jump_t <= 0:
            self.health -= dmg
            self.last_dmg_time = ticks_ms()
            self.hit_flash = 5
            self._leds_red()
            if self.health <= 0:
                self.health = 0
                self.deaths += 1
                self.state = STATE_DEAD
                self.dead_t = 3000
                return

        # Regen
        now = ticks_ms()
        if self.health < 100 and ticks_diff(now, self.last_dmg_time) > REGEN_DELAY:
            self.regen_acc += delta
            if self.regen_acc >= 1000:
                self.health = min(100, self.health + 1)
                self.regen_acc -= 1000

        # Raycast
        self.columns = engine.cast_rays(
            self.px, self.py, self.pa, game_map.get_wall)

        self._leds_ambient()

    def _up_dead(self, delta):
        self.dead_t -= delta
        if self.dead_t <= 0:
            self._respawn()
            self.state = STATE_GAME

    def _up_credits(self, delta):
        try:
            acc = imu.acc_read()
            self.tilt_x = acc[0] * 0.5
            self.tilt_y = acc[1] * 0.5
        except Exception:
            pass
        for btn in BUTTON_TYPES.values():
            if self.button_states.get(btn):
                self.button_states.clear()
                self.state = STATE_TITLE
                return

    # --- Shooting ---

    def _shoot(self):
        self.flash_t = 400
        self._leds_white()

        best_d = RAIL_RANGE
        best_p = None
        for p in self.net_mgr.get_peers():
            if p.get('flags', 0) & 2:
                continue
            dx = p['x'] - self.px
            dy = p['y'] - self.py
            d = math.sqrt(dx * dx + dy * dy)
            if d > RAIL_RANGE or d < 0.5:
                continue
            at = math.atan2(dy, dx)
            diff = at - self.pa
            while diff > math.pi:
                diff -= 6.283185
            while diff < -math.pi:
                diff += 6.283185
            if abs(diff) < HIT_ANGLE and d < best_d:
                best_d = d
                best_p = p

        if best_p:
            self.net_mgr.send_damage(best_p['name'], RAIL_DMG)
            best_p['hit'] = 5
            if best_p['health'] <= RAIL_DMG:
                self.kills += 1
                self.kill_feed = "FRAGGED " + best_p['name']
            else:
                self.kill_feed = "HIT " + best_p['name']
            self.feed_t = 40

    # --- Spawn ---

    def _respawn(self):
        self.px, self.py, self.pa = game_map.random_spawn()
        self.health = 100
        self.shoot_cd = 0
        self.jump_t = 0
        self.jump_cd = 0
        self.regen_acc = 0
        self.water_acc = 0

    # --- Draw dispatch ---

    def draw(self, ctx):
        ctx.save()
        if self.state == STATE_TITLE:
            self._dr_title(ctx)
        elif self.state == STATE_CONFIG:
            self._dr_config(ctx)
        elif self.state == STATE_GAME:
            self._dr_game(ctx)
        elif self.state == STATE_DEAD:
            self._dr_dead(ctx)
        elif self.state == STATE_CREDITS:
            self._dr_credits(ctx)
        ctx.restore()

    def _dr_title(self, ctx):
        ctx.rgb(0.02, 0.02, 0.06).rectangle(-120, -120, 240, 240).fill()

        pulse = 0.8 + 0.2 * math.sin(self.title_pulse)

        ctx.font_size = 20
        t = "TILDENSTEIN 3D"
        tw = ctx.text_width(t)
        ctx.rgb(0.0 * pulse, 0.85 * pulse, 1.0 * pulse)
        ctx.move_to(-tw * 0.5, -12).text(t)

        ctx.font_size = 11
        m = "MESH MULTIPLAYER FPS"
        mw = ctx.text_width(m)
        ctx.rgb(0.6, 0.45, 0.2).move_to(-mw * 0.5, 7).text(m)

        ctx.font_size = 12
        e = "EMF CAMP ARENA"
        ew = ctx.text_width(e)
        ctx.rgb(0.35, 0.55, 0.35).move_to(-ew * 0.5, 44).text(e)

        ctx.font_size = 11
        kd = "FRAGS: {}  DEATHS: {}".format(self.kills, self.deaths)
        kw = ctx.text_width(kd)
        ctx.rgb(0.5, 0.5, 0.5).move_to(-kw * 0.5, 58).text(kd)

        ctx.font_size = 11
        h1 = "ANY BTN: PLAY"
        hw1 = ctx.text_width(h1)
        ctx.rgb(0.3, 0.3, 0.3).move_to(-hw1 * 0.5, 74).text(h1)
        h2 = "E: NAME  F: QUIT"
        hw2 = ctx.text_width(h2)
        ctx.rgb(0.3, 0.3, 0.3).move_to(-hw2 * 0.5, 87).text(h2)
        h3 = "D: CREDITS"
        hw3 = ctx.text_width(h3)
        ctx.rgb(0.3, 0.3, 0.3).move_to(-hw3 * 0.5, 100).text(h3)

        ctx.font_size = 12
        nm = "[ {} ]".format(self.player_name.strip())
        nw = ctx.text_width(nm)
        ctx.rgb(0.0, 0.6, 0.8).move_to(-nw * 0.5, -55).text(nm)

    def _dr_config(self, ctx):
        ctx.rgb(0.02, 0.02, 0.06).rectangle(-120, -120, 240, 240).fill()

        ctx.font_size = 14
        t = "ENTER YOUR NAME"
        tw = ctx.text_width(t)
        ctx.rgb(0.0, 0.8, 1.0).move_to(-tw * 0.5, -50).text(t)

        ctx.font_size = 26
        total = 6 * 28
        sx = -total * 0.5
        for i in range(6):
            x = sx + i * 28
            c = self.cfg_chars[i]
            if i == self.cfg_pos:
                ctx.rgb(0.0, 0.9, 0.5).rectangle(x, -12, 24, 34).fill()
                ctx.rgb(0.0, 0.0, 0.0)
            else:
                ctx.rgb(0.7, 0.7, 0.7)
            cw = ctx.text_width(c)
            ctx.move_to(x + 12 - cw * 0.5, 16).text(c)

        ctx.font_size = 9
        ctx.rgb(0.35, 0.35, 0.35)
        h = "A/D:CHAR  B:NEXT  C:SAVE  F:BACK"
        hw = ctx.text_width(h)
        ctx.move_to(-hw * 0.5, 60).text(h)

    def _dr_game(self, ctx):
        jo = 0.0
        if self.jump_t > 0:
            t = self.jump_t / JUMP_DUR
            jo = math.sin(t * 3.14159) * 15

        peers = self.net_mgr.get_peers()
        engine.draw_frame(
            ctx, self.columns, peers,
            self.px, self.py, self.pa, jo,
            self.health,
            max(0.0, self.shoot_cd) / RAIL_CD,
            self.kills, self.deaths, self.player_name,
            self.kill_feed, self.feed_t,
            self.net_mgr.rx_count)

        if self.flash_t > 0:
            p = self.flash_t / 400.0
            bx, by = 0, 120 + jo
            ah = 24
            if p > 0.5:
                a = (p - 0.5) * 0.4
                ctx.rgba(1, 1, 1, a).rectangle(-120, -120, 240, 240).fill()
            ctx.rgb(0.0, 0.0, 0.0)
            ctx.begin_path()
            ctx.move_to(bx - 54, by)
            ctx.line_to(bx, by - ah)
            ctx.line_to(bx + 54, by)
            ctx.fill()
            ctx.line_width = max(1, int(p * 4))
            ctx.rgba(1.0, 1.0, 1.0, min(1.0, p * 1.5))
            ctx.begin_path()
            ctx.move_to(bx, by - ah)
            ctx.line_to(0, jo)
            ctx.stroke()

        if self.hit_flash > 0:
            a = self.hit_flash / 5.0 * 0.25
            ctx.rgba(1, 0, 0, a).rectangle(-120, -120, 240, 240).fill()

    def _dr_dead(self, ctx):
        ctx.rgb(0.12, 0.0, 0.0).rectangle(-120, -120, 240, 240).fill()

        ctx.font_size = 24
        t = "YOU DIED"
        tw = ctx.text_width(t)
        ctx.rgb(1.0, 0.1, 0.1).move_to(-tw * 0.5, -10).text(t)

        ctx.font_size = 12
        secs = max(1, int(self.dead_t / 1000) + 1)
        s = "Respawning in {}...".format(secs)
        sw = ctx.text_width(s)
        ctx.rgb(0.6, 0.3, 0.3).move_to(-sw * 0.5, 20).text(s)

        ctx.font_size = 11
        kd = "K:{} D:{}".format(self.kills, self.deaths)
        kw = ctx.text_width(kd)
        ctx.rgb(0.5, 0.5, 0.5).move_to(-kw * 0.5, 50).text(kd)

    def _dr_credits(self, ctx):
        ctx.rgb(0.01, 0.02, 0.04).rectangle(-120, -120, 240, 240).fill()

        tx = self.tilt_x
        ty = self.tilt_y

        ox = tx * 1.8
        oy = ty * 1.8

        lw, lh = 160, 90
        ctx.image(ASSET_PATH + "logo.jpg", -lw * 0.5 + ox, -80 + oy, lw, lh)

        ctx.font_size = 11
        lines = [
            ("@webboggles", 0.0, 0.83, 1.0),
            ("weborder.uk", 0.0, 0.65, 0.8),
            ("", 0, 0, 0),
            ("ESP-NOW Mesh", 0.5, 0.4, 0.2),
            ("Raycasting Engine", 0.5, 0.4, 0.2),
        ]
        y = 25
        for txt, r, g, b in lines:
            if not txt:
                y += 8
                continue
            w = ctx.text_width(txt)
            ctx.rgb(r, g, b).move_to(-w * 0.5 + tx * 0.5, y + ty * 0.5).text(txt)
            y += 15

        ctx.font_size = 9
        h = "ANY BTN: BACK"
        hw = ctx.text_width(h)
        ctx.rgb(0.3, 0.3, 0.3).move_to(-hw * 0.5, 95).text(h)

    # --- Name persistence ---

    def _load_name(self):
        try:
            with open(ASSET_PATH + "name.txt", "r") as f:
                n = f.read().strip()[:6]
                if n:
                    return n.lower()
        except Exception:
            pass
        name = "".join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(4))
        return (name + "  ")[:6]

    def _save_name(self):
        try:
            with open(ASSET_PATH + "name.txt", "w") as f:
                f.write(self.player_name)
        except Exception:
            pass

    # --- Lifecycle ---

    def background(self):
        self._leds_restore()

    # --- LEDs ---

    def _leds_restore(self):
        if _HAS_LEDS:
            eventbus.emit(PatternEnable())

    def _leds_white(self):
        pass

    def _leds_red(self):
        pass

    def _leds_ambient(self):
        if not _HAS_LEDS:
            return
        if self.hit_flash > 0:
            on = self.hit_flash % 2 == 1
            for i in range(12):
                tildagonos.leds[i + 1] = (80, 0, 0) if on else (0, 0, 0)
            tildagonos.leds.write()
            return
        if self.flash_t > 0:
            on = int(self.flash_t / 80) % 2 == 0
            for i in range(12):
                tildagonos.leds[i + 1] = (0, 0, 40) if on else (0, 0, 0)
            tildagonos.leds.write()
            return
        for i in range(12):
            tildagonos.leds[i + 1] = (0, 0, 0)
        TWO_PI = 6.283185
        for p in self.net_mgr.peers.values():
            dx = p['x'] - self.px
            dy = p['y'] - self.py
            a = (math.atan2(dy, dx) - self.pa) % TWO_PI
            idx = int(a / TWO_PI * 12 + 0.5) % 12
            led = idx % 12
            tildagonos.leds[led + 1] = (80, 0, 0)
        tildagonos.leds.write()


__app_export__ = TildensteinApp
