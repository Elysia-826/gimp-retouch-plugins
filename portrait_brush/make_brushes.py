#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the 人像笔刷 brush files. MIT, same as the repo.

Everything is drawn here from a fixed seed. Nothing is copied from another
brush set. Run it again and you get the same bytes:

    python3 portrait_brush/make_brushes.py        # writes portrait_brush/brushes/

Files (GIMP 3.0 and 3.2 both load all three formats):
  portrait-soft-round.vbr   parametric round, hardness 0.15
  portrait-skin-pores.gbr   96x96 RGBA pixmap: neutral grey (mean 128) with
                            small dark pores and fine grain. Grey 128 is
                            "no change" on a grain-merge high-frequency layer
                            and on a soft-light D&B layer, so painting it adds
                            texture without moving the average tone.
  portrait-hair-strand.gih  16 cells, angular: each cell holds three thin
                            parallel strand segments along the stroke
                            direction, so a drag leaves fine parallel hairs.
Pure Python, no numpy.
"""
import math
import os
import random
import struct

SEED = 20261008
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "brushes")

SOFT_NAME = "Portrait Soft Round 人像柔圆"
PORES_NAME = "Portrait Skin Pores 皮肤毛孔"
HAIR_NAME = "Portrait Hair Strand 细发丝"


def gbr(name, w, h, bpp, data, spacing):
    nm = name.encode("utf-8") + b"\0"
    head = struct.pack(">IIIIIII", 28 + len(nm), 2, w, h, bpp, 0x47494D50, spacing)  # 'GIMP'
    assert len(data) == w * h * bpp
    return head + nm + bytes(data)


def smoothstep(e0, e1, x):
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3.0 - 2.0 * t)


def value_noise(rng, w, h, cell):
    gw, gh = w // cell + 2, h // cell + 2
    g = [[rng.uniform(-1.0, 1.0) for _ in range(gw)] for _ in range(gh)]
    out = []
    for y in range(h):
        fy = y / cell; iy = int(fy); ty = smoothstep(0, 1, fy - iy)
        row = []
        for x in range(w):
            fx = x / cell; ix = int(fx); tx = smoothstep(0, 1, fx - ix)
            a = g[iy][ix] + (g[iy][ix + 1] - g[iy][ix]) * tx
            b = g[iy + 1][ix] + (g[iy + 1][ix + 1] - g[iy + 1][ix]) * tx
            row.append(a + (b - a) * ty)
        out.append(row)
    return out


def soft_round():
    # GIMP-VBR 1.0: name, spacing, radius, hardness, aspect ratio, angle
    return ("GIMP-VBR\n1.0\n%s\n10.000000\n50.000000\n0.150000\n1.000000\n0.000000\n" % SOFT_NAME).encode("utf-8")


def skin_pores():
    rng = random.Random(SEED)
    S = 96
    R = S / 2.0
    c = (S - 1) / 2.0
    n1 = value_noise(rng, S, S, 2)
    n2 = value_noise(rng, S, S, 5)
    v = [[6.0 * n1[y][x] + 4.0 * n2[y][x] for x in range(S)] for y in range(S)]
    # pores: small dark gaussian dips with a faint light rim up-left
    npores = 190
    for _ in range(npores):
        while True:
            px, py = rng.uniform(4, S - 5), rng.uniform(4, S - 5)
            if math.hypot(px - c, py - c) < R - 4:
                break
        sig = rng.uniform(0.55, 1.05)
        depth = rng.uniform(30.0, 58.0)
        r = int(sig * 4) + 2
        for y in range(int(py) - r, int(py) + r + 2):
            for x in range(int(px) - r, int(px) + r + 2):
                if 0 <= x < S and 0 <= y < S:
                    d2 = (x - px) ** 2 + (y - py) ** 2
                    v[y][x] -= depth * math.exp(-d2 / (2 * sig * sig))
                    d2r = (x - px + 0.9) ** 2 + (y - py + 0.9) ** 2
                    v[y][x] += 0.22 * depth * math.exp(-d2r / (2 * (1.9 * sig) ** 2))
    alpha = [[0.0] * S for _ in range(S)]
    for y in range(S):
        for x in range(S):
            d = math.hypot(x - c, y - c) / R
            alpha[y][x] = 1.0 - smoothstep(0.55, 1.0, d)
    # make the alpha-weighted mean exactly 128 after clamping
    shift = 0.0
    for _ in range(6):
        sw = sv = 0.0
        for y in range(S):
            for x in range(S):
                a = alpha[y][x]
                if a > 0:
                    q = min(255.0, max(0.0, 128.0 + v[y][x] + shift))
                    sw += a; sv += a * q
        shift += 128.0 - sv / sw
    data = bytearray()
    for y in range(S):
        for x in range(S):
            g = int(round(min(255.0, max(0.0, 128.0 + v[y][x] + shift))))
            data += bytes((g, g, g, int(round(255 * alpha[y][x]))))
    return gbr(PORES_NAME, S, S, 4, data, 50)


def hair_strand():
    rng = random.Random(SEED + 1)
    N, S = 16, 64
    c = (S - 1) / 2.0
    # three strands across the brush: offsets (px), widths, strengths
    strands = [(-6.5, 0.55, 0.85), (0.0, 0.75, 1.0), (5.0, 0.5, 0.75)]
    cells = []
    for k in range(N):
        # GIMP picks cell ix = round((1 - direction + 0.25) * N) % N;
        # direction is the stroke angle / 360 (counter-clockwise, y up).
        theta = 2.0 * math.pi * (0.25 - k / float(N))
        ux, uy = math.cos(theta), -math.sin(theta)       # along the stroke (image coords)
        nx, ny = -uy, ux                                  # across
        wob = [(rng.uniform(-0.35, 0.35), rng.uniform(0.0, 2 * math.pi)) for _ in strands]
        buf = bytearray(S * S)
        for y in range(S):
            for x in range(S):
                dx, dy = x - c, y - c
                along = dx * ux + dy * uy
                across = dx * nx + dy * ny
                taper = 1.0 - smoothstep(0.62 * c, 0.98 * c, abs(along))
                if taper <= 0:
                    continue
                best = 0.0
                for (off, wd, st), (amp, ph) in zip(strands, wob):
                    centre = off + amp * math.sin(along / 9.0 + ph)
                    dist = abs(across - centre)
                    cov = max(0.0, 1.0 - max(0.0, dist - wd * 0.5) / 0.85)
                    best = max(best, st * cov)
                buf[y * S + x] = int(round(255 * best * taper))
        cells.append(gbr("%s %d" % (HAIR_NAME, k), S, S, 1, buf, 6))
    head = ("%s\n%d ncells:%d cellwidth:%d cellheight:%d step:100 dimension:1 rank0:%d placement:constant selection0:angular\n"
            % (HAIR_NAME, N, N, S, S, N)).encode("utf-8")
    return head + b"".join(cells)


def main():
    os.makedirs(OUT, exist_ok=True)
    files = {
        "portrait-soft-round.vbr": soft_round(),
        "portrait-skin-pores.gbr": skin_pores(),
        "portrait-hair-strand.gih": hair_strand(),
    }
    for n, b in files.items():
        with open(os.path.join(OUT, n), "wb") as f:
            f.write(b)
        print("%-26s %7d bytes" % (n, len(b)))


if __name__ == "__main__":
    main()
