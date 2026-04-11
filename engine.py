import math
import struct

from game_map import WALL_COLORS, MARQUEE_ROOF, GROUND_COLORS

NUM_COLS = 60
COL_W = 4
HALF_W = 120
HALF_H = 120
FOV = 1.0472
HALF_FOV = FOV * 0.5
PROJ_DIST = (NUM_COLS * 0.5) / math.tan(HALF_FOV)
MAX_DEPTH = 64
TWO_PI = 6.283185

_col_cos = []
_col_sin = []
for _i in range(NUM_COLS):
    _a = (_i - NUM_COLS * 0.5 + 0.5) * FOV / NUM_COLS
    _col_cos.append(math.cos(_a))
    _col_sin.append(math.sin(_a))


def fast_inv_sqrt(x):
    if x <= 0.0:
        return 0.0
    hx = 0.5 * x
    buf = struct.pack('f', x)
    i = struct.unpack('I', buf)[0]
    i = 0x5f3759df - (i >> 1)
    buf = struct.pack('I', i)
    y = struct.unpack('f', buf)[0]
    y = y * (1.5 - hx * y * y)
    return y


def cast_rays(px, py, pa, get_wall):
    sa = math.sin(pa)
    ca = math.cos(pa)
    cols = []

    for i in range(NUM_COLS):
        ray_dx = ca * _col_cos[i] - sa * _col_sin[i]
        ray_dy = sa * _col_cos[i] + ca * _col_sin[i]

        mx = int(px)
        my = int(py)

        dx_abs = abs(ray_dx)
        dy_abs = abs(ray_dy)
        delta_x = 1e8 if dx_abs < 1e-8 else 1.0 / dx_abs
        delta_y = 1e8 if dy_abs < 1e-8 else 1.0 / dy_abs

        if ray_dx < 0:
            step_x = -1
            side_x = (px - mx) * delta_x
        else:
            step_x = 1
            side_x = (mx + 1.0 - px) * delta_x

        if ray_dy < 0:
            step_y = -1
            side_y = (py - my) * delta_y
        else:
            step_y = 1
            side_y = (my + 1.0 - py) * delta_y

        wt = 0
        side = 0
        for _ in range(MAX_DEPTH):
            if side_x < side_y:
                side_x += delta_x
                mx += step_x
                side = 0
            else:
                side_y += delta_y
                my += step_y
                side = 1

            w = get_wall(mx, my)
            if w > 0:
                wt = w
                break

        if wt:
            if side == 0:
                pd = (mx - px + (1 - step_x) * 0.5)
                pd = pd / ray_dx if dx_abs > 1e-8 else MAX_DEPTH
                hf = (py + pd * ray_dy) % 1.0
            else:
                pd = (my - py + (1 - step_y) * 0.5)
                pd = pd / ray_dy if dy_abs > 1e-8 else MAX_DEPTH
                hf = (px + pd * ray_dx) % 1.0
            if pd < 0.05:
                pd = 0.05
        else:
            pd = MAX_DEPTH
            hf = 0.0

        cols.append((pd, wt, side, hf))

    return cols


def draw_frame(ctx, columns, peers, px, py, pa, jump_ofs,
               health, cd_pct, kills, deaths, name, feed, feed_t, rx=0):
    ctx.save()

    from game_map import get_ground
    gt = get_ground(px, py)
    _draw_sky_floor(ctx, jump_ofs, gt)
    _draw_walls(ctx, columns, jump_ofs)
    _draw_labels(ctx, columns, px, py, pa, jump_ofs)
    _draw_sprites(ctx, peers, columns, px, py, pa, jump_ofs)

    ctx.restore()

    _draw_hud(ctx, health, cd_pct, kills, deaths, name, feed, feed_t, len(peers), rx)
    _draw_minimap(ctx, px, py, pa, peers)


def _draw_sky_floor(ctx, jo, ground_type):
    ctx.rgb(0.25, 0.55, 0.85)
    ctx.rectangle(-HALF_W, -HALF_H, 240, HALF_H + jo).fill()

    gc = GROUND_COLORS.get(ground_type, (0.18, 0.42, 0.12))
    fr, fg, fb = gc

    ctx.rgb(fr * 1.6, fg * 1.2, fb * 1.2)
    ctx.rectangle(-HALF_W, jo, 240, 40).fill()
    ctx.rgb(fr * 1.3, fg * 1.1, fb * 1.1)
    ctx.rectangle(-HALF_W, jo + 40, 240, 30).fill()
    ctx.rgb(fr, fg, fb)
    ctx.rectangle(-HALF_W, jo + 70, 240, 50).fill()


def _draw_walls(ctx, columns, jo):
    for i in range(NUM_COLS):
        pd, wt, side, hf = columns[i]
        if wt == 0:
            continue

        x = -HALF_W + i * COL_W

        wh = PROJ_DIST / pd
        if wh > 240:
            wh = 240

        colors = WALL_COLORS.get(wt, ((0.5, 0.5, 0.5), (0.35, 0.35, 0.35)))
        r, g, b = colors[side]

        fog = 1.0 - pd / MAX_DEPTH
        if fog < 0.08:
            fog = 0.08

        y = -wh * 0.5 + jo

        roof = MARQUEE_ROOF.get(wt)
        if wt == 2 or roof:
            if roof:
                rr, rg, rb = roof[side]
            else:
                rr, rg, rb = r * 0.7, g * 0.7, b * 0.7
            max_rh = wh * 0.35
            if side == 1:
                slope = 1.0 - abs(hf - 0.5) * 2.0
                rh = max_rh * slope
                body_y = y + max_rh
                body_h = wh - max_rh
                ctx.rgb(rr * fog, rg * fog, rb * fog)
                if body_h > 0.5:
                    ctx.rectangle(x, body_y, COL_W, body_h).fill()
                if rh > 0.5:
                    ctx.rgb(r * fog, g * fog, b * fog)
                    ctx.rectangle(x, y + max_rh - rh, COL_W, rh).fill()
            else:
                roof_h = max_rh
                ctx.rgb(0.25 * fog, 0.55 * fog, 0.85 * fog)
                ctx.rectangle(x, y, COL_W, roof_h).fill()
                ctx.rgb(r * fog, g * fog, b * fog)
                ctx.rectangle(x, y + roof_h, COL_W, wh - roof_h).fill()
        elif wt == 3:
            cf = 0.85 if i % 3 == 0 else 1.0
            ctx.rgb(r * fog * cf, g * fog * cf, b * fog * cf)
            ctx.rectangle(x, y, COL_W, wh).fill()
            if wh > 8:
                ctx.rgb(r * fog * 0.5, g * fog * 0.5, b * fog * 0.5)
                ctx.rectangle(x, y + wh * 0.48, COL_W, max(1, wh * 0.04)).fill()
        else:
            ctx.rgb(r * fog, g * fog, b * fog)
            ctx.rectangle(x, y, COL_W, wh).fill()


def _draw_labels(ctx, columns, px, py, pa, jo):
    from game_map import MAP_LABELS
    ca = math.cos(pa)
    sa = math.sin(pa)

    for cx, cy, nx, ny, text in MAP_LABELS:
        dx = px - cx
        dy = py - cy
        dot = dx * nx + dy * ny
        if dot < 0.2:
            continue

        rx = cx - px
        ry = cy - py
        tz = rx * ca + ry * sa
        if tz < 0.4 or tz > 20.0:
            continue
        tx = -rx * sa + ry * ca
        sx = tx / tz * PROJ_DIST

        if sx < -HALF_W - 30 or sx > HALF_W + 30:
            continue

        ci = int((sx + HALF_W) / COL_W)
        if 0 <= ci < NUM_COLS and columns[ci][0] < tz - 0.05:
            continue

        fsize = 28.0 / tz
        if fsize < 4:
            continue
        if fsize > 16:
            fsize = 16

        ctx.font_size = fsize
        tw = ctx.text_width(text)

        fog = 1.0 - tz / 22.0
        if fog < 0.15:
            fog = 0.15

        ctx.rgb(0.95 * fog, 0.9 * fog, 0.65 * fog)
        ctx.move_to(sx - tw * 0.5, jo).text(text)


def _draw_sprites(ctx, peers, columns, px, py, pa, jo):
    ca = math.cos(pa)
    sa = math.sin(pa)
    vis = []

    for p in peers:
        dx = p['x'] - px
        dy = p['y'] - py
        tz = dx * ca + dy * sa
        if tz < 0.2:
            continue
        tx = -dx * sa + dy * ca
        sx = tx / tz * PROJ_DIST
        sc = 40.0 / tz
        vis.append((tz, sx, sc, p))

    vis.sort(key=lambda v: -v[0])

    for tz, sx, sc, p in vis:
        ci = int((sx + HALF_W) / COL_W)
        if 0 <= ci < NUM_COLS and columns[ci][0] < tz:
            continue
        spy = jo - (sc * 0.5 if p.get('flags', 0) & 2 else 0)
        _draw_spider(ctx, sx, spy, sc, p.get('hit', 0))


def _draw_spider(ctx, sx, sy, size, hit):
    if size < 3:
        return
    if size > 100:
        size = 100

    # SVG was authored at size=80 centred on (60, 52) in a 120x109 viewBox.
    # Scale all SVG coords: p(x,y) -> sx + (x-60)*s, sy + (y-52)*s
    s = size / 80.0

    def p(x, y):
        return sx + (x - 60.0) * s, sy + (y - 52.0) * s

    if hit and hit > 0:
        body_col = (1.0, 0.2, 0.2)
    else:
        body_col = (0.0, 0.0, 0.0)

    lw = max(3.2 * s, 1.0)

    # --- Legs (8 cubic bezier strokes, x0,y0, cx1,cy1, cx2,cy2, x1,y1 in SVG space) ---
    ctx.rgb(*body_col)
    ctx.line_width = lw
    leg_data = [
        (50.952603,57.806468,  41.571568,60.977522,  28.457379,69.121436,  37.705052,76.964920),
        (47.517295,46.059998,  38.466578,44.926659,  35.541441,51.768845,  31.541441,48.768845),
        (48.442185,53.522115,  43.012751,53.522115,  35.541441,62.190279,  31.541441,62.190279),
        (54.166186,64.412831,  50.356536,69.967186,  57.257141,82.400699,  57.757141,86.900771),
        (69.749891,40.644116,  68.507,37.831,        76.500417,34.948359,  76.500417,34.948359),
        (73.125155,45.601534,  75.259895,41.536667,  81.035928,37.104231,  88.208362,41.010171),
        (75.259894,51.117561,  83.145467,43.550228,  86.151561,49.285143,  95.697227,54.250646),
        (72.914201,57.806468,  84.411191,49.769159,  86.230652,55.667723,  93.004086,72.099563),
    ]
    ctx.begin_path()
    for x0,y0, cx1,cy1, cx2,cy2, x1,y1 in leg_data:
        ax0,ay0 = p(x0,y0)
        acx1,acy1 = p(cx1,cy1)
        acx2,acy2 = p(cx2,cy2)
        ax1,ay1 = p(x1,y1)
        ctx.move_to(ax0, ay0)
        ctx.curve_to(acx1, acy1, acx2, acy2, ax1, ay1)
    ctx.stroke()

    # --- Body (filled irregular shape approximated as scaled path) ---
    # Original SVG path: complex shape; approximate with a filled ellipse matching bounds
    # Body centre ~(64, 52), width ~38, height ~36 in SVG coords
    ctx.rgb(*body_col)
    ctx.begin_path()
    ctx.arc(sx + (64.0 - 60.0) * s, sy + (52.0 - 52.0) * s, 19.0 * s, 0, TWO_PI, True)
    ctx.fill()

    # --- Eyes (red rounded rects) ---
    ctx.rgb(1.0, 0.0, 0.0)
    for ex, ey_svg, ew, eh in [
        (60.254557, 47.443881, 4.976816, 5.760002),
        (66.495468, 47.443881, 4.976816, 5.760002),
    ]:
        rx, ry = p(ex, ey_svg)
        rw = ew * s
        rh = eh * s
        ctx.begin_path()
        ctx.arc(rx + rw * 0.5, ry + rh * 0.5, rw * 0.5, 0, TWO_PI, True)
        ctx.fill()

    # --- Smile ---
    ctx.rgb(1.0, 1.0, 1.0)
    ctx.line_width = max(2.0 * s, 0.5)
    ctx.begin_path()
    ctx.move_to(*p(60.377908, 58.06299))
    ctx.curve_to(*p(59.553329, 60.078395), *p(64.270903, 61.499004), *p(64.870903, 58.06299))
    ctx.stroke()


def _draw_hud(ctx, health, cd_pct, kills, deaths, name, feed, feed_t, peer_count, rx):
    ctx.rgb(0.0, 1.0, 0.0)
    ctx.line_width = 1
    ctx.begin_path()
    ctx.move_to(-6, 0)
    ctx.line_to(6, 0)
    ctx.move_to(0, -6)
    ctx.line_to(0, 6)
    ctx.stroke()

    bw = 80
    bh = 6
    bx = -bw * 0.5
    by = 90
    ctx.rgb(0.2, 0.0, 0.0).rectangle(bx, by, bw, bh).fill()
    hw = bw * health / 100
    if health > 50:
        ctx.rgb(0.0, 0.8, 0.0)
    elif health > 25:
        ctx.rgb(0.8, 0.6, 0.0)
    else:
        ctx.rgb(0.8, 0.0, 0.0)
    ctx.rectangle(bx, by, hw, bh).fill()

    if cd_pct > 0.01:
        cw = 24 * cd_pct
        ctx.rgb(0.3, 0.3, 0.7).rectangle(-cw * 0.5, 10, cw, 3).fill()

    ctx.font_size = 10
    kd = "K:{} D:{}".format(kills, deaths)
    ctx.rgb(0.6, 0.6, 0.6).move_to(-95, -88).text(kd)

    nw = ctx.text_width(name)
    ctx.rgb(0.0, 0.7, 1.0).move_to(95 - nw, -88).text(name)

    pc = str(peer_count + 1)
    pw = ctx.text_width(pc)
    ctx.rgb(0.5, 0.5, 0.5).move_to(-pw * 0.5, -88).text(pc)

    if feed and feed_t and feed_t > 0:
        ctx.font_size = 12
        fw = ctx.text_width(feed)
        ctx.rgb(1.0, 0.3, 0.3).move_to(-fw * 0.5, -65).text(feed)


def _draw_minimap(ctx, px, py, pa, peers):
    from game_map import MAP_W, MAP_H, MAP_DATA, GROUND_DATA

    mx = 75
    my = 60
    mr = 22
    scale = mr / 8.0

    ctx.rgba(0.0, 0.0, 0.0, 0.4)
    ctx.begin_path()
    ctx.arc(mx, my, mr + 2, 0, TWO_PI, True)
    ctx.fill()

    ctx.rgb(0.15, 0.2, 0.15)
    ctx.begin_path()
    ctx.arc(mx, my, mr, 0, TWO_PI, True)
    ctx.fill()

    _mm_ground = {1: (0.10, 0.35, 0.55), 2: (0.30, 0.28, 0.25), 3: (0.15, 0.40, 0.55)}
    hs = scale * 0.4

    for wy in range(max(0, int(py) - 8), min(MAP_H, int(py) + 8)):
        for wx in range(max(0, int(px) - 8), min(MAP_W, int(px) + 8)):
            dx = (wx + 0.5 - px) * scale
            dy = (wy + 0.5 - py) * scale
            sx = mx + dx
            sy = my + dy
            if (sx - mx) ** 2 + (sy - my) ** 2 >= mr * mr:
                continue

            wv = MAP_DATA[wy * MAP_W + wx]
            if wv > 0:
                ctx.rgb(0.35, 0.4, 0.35)
                ctx.rectangle(sx - hs, sy - hs, hs * 2, hs * 2).fill()
            else:
                gv = GROUND_DATA[wy * MAP_W + wx]
                gc = _mm_ground.get(gv)
                if gc:
                    ctx.rgb(*gc)
                    ctx.rectangle(sx - hs, sy - hs, hs * 2, hs * 2).fill()

    for p in peers:
        dx = (p['x'] - px) * scale
        dy = (p['y'] - py) * scale
        sx = mx + dx
        sy = my + dy
        if (sx - mx) ** 2 + (sy - my) ** 2 < mr * mr:
            ctx.rgb(1.0, 0.2, 0.2)
            ctx.rectangle(sx - 1.5, sy - 1.5, 3, 3).fill()

    ctx.rgb(0.0, 1.0, 0.5)
    ctx.begin_path()
    ctx.arc(mx, my, 2, 0, TWO_PI, True)
    ctx.fill()
    fx = mx + math.cos(pa) * 5
    fy = my + math.sin(pa) * 5
    ctx.line_width = 1
    ctx.begin_path()
    ctx.move_to(mx, my)
    ctx.line_to(fx, fy)
    ctx.stroke()
