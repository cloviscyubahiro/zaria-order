"""A small QR encoder (byte mode, EC level M, versions 1-10) that emits SVG.

Written from the ISO/IEC 18004 spec rather than pulled from PyPI so the whole
system stays installable by copying a folder. Version 10 holds 213 bytes, far
more than a table URL needs.
"""
from __future__ import annotations

# --- GF(256) -----------------------------------------------------------------

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(n: int) -> list[int]:
    poly = [1]
    for i in range(n):
        nxt = [0] * (len(poly) + 1)
        for j, c in enumerate(poly):
            nxt[j] ^= _mul(c, 1)
            nxt[j + 1] ^= _mul(c, _EXP[i])
        poly = nxt
    return poly


def _rs_encode(data: list[int], ec_len: int) -> list[int]:
    gen = _rs_generator(ec_len)
    rem = [0] * ec_len
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        for i, g in enumerate(gen[1:]):
            rem[i] ^= _mul(g, factor)
    return rem


# --- Version tables (EC level M) ---------------------------------------------
# version -> (ec_per_block, [(block_count, data_codewords_per_block), ...])
_SPEC = {
    1:  (10, [(1, 16)]),
    2:  (16, [(1, 28)]),
    3:  (26, [(1, 44)]),
    4:  (18, [(2, 32)]),
    5:  (24, [(2, 43)]),
    6:  (16, [(4, 27)]),
    7:  (18, [(4, 31)]),
    8:  (22, [(2, 38), (2, 39)]),
    9:  (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]),
}

_ALIGN = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

_EC_M_INDICATOR = 0b00  # L=01, M=00, Q=11, H=10


def _capacity(version: int) -> int:
    ec, groups = _SPEC[version]
    total_data = sum(n * k for n, k in groups)
    header_bits = 4 + (8 if version < 10 else 16)
    return (total_data * 8 - header_bits) // 8


def _pick_version(length: int) -> int:
    for v in range(1, 11):
        if length <= _capacity(v):
            return v
    raise ValueError("Text is too long for this encoder (max 213 bytes).")


# --- Bitstream ---------------------------------------------------------------


def _build_codewords(payload: bytes, version: int) -> list[int]:
    ec_len, groups = _SPEC[version]
    total_data = sum(n * k for n, k in groups)

    bits: list[int] = []

    def push(value: int, width: int):
        for i in range(width - 1, -1, -1):
            bits.append((value >> i) & 1)

    push(0b0100, 4)                                   # byte mode
    push(len(payload), 8 if version < 10 else 16)     # character count
    for b in payload:
        push(b, 8)

    # Terminator, then pad to a byte boundary, then alternating pad bytes.
    for _ in range(min(4, total_data * 8 - len(bits))):
        bits.append(0)
    while len(bits) % 8:
        bits.append(0)

    codewords = [int("".join(str(b) for b in bits[i:i + 8]), 2)
                 for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    i = 0
    while len(codewords) < total_data:
        codewords.append(pad[i % 2])
        i += 1

    # Split into blocks, compute EC per block.
    blocks, ecs, pos = [], [], 0
    for count, size in groups:
        for _ in range(count):
            chunk = codewords[pos:pos + size]
            pos += size
            blocks.append(chunk)
            ecs.append(_rs_encode(chunk, ec_len))

    # Interleave data, then interleave EC.
    out: list[int] = []
    for i in range(max(len(b) for b in blocks)):
        for b in blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(ec_len):
        for e in ecs:
            out.append(e[i])
    return out


# --- Matrix ------------------------------------------------------------------


def _new_matrix(version: int):
    size = 17 + 4 * version
    m = [[0] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    def finder(r0, c0):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = r0 + dr, c0 + dc
                if not (0 <= r < size and 0 <= c < size):
                    continue
                inside = (0 <= dr <= 6 and 0 <= dc <= 6)
                dark = inside and (
                    dr in (0, 6) or dc in (0, 6) or (2 <= dr <= 4 and 2 <= dc <= 4)
                )
                m[r][c] = 1 if dark else 0
                reserved[r][c] = True

    finder(0, 0)
    finder(0, size - 7)
    finder(size - 7, 0)

    # Timing patterns
    for i in range(size):
        if not reserved[6][i]:
            m[6][i] = 1 if i % 2 == 0 else 0
            reserved[6][i] = True
        if not reserved[i][6]:
            m[i][6] = 1 if i % 2 == 0 else 0
            reserved[i][6] = True

    # Alignment patterns
    centres = _ALIGN[version]
    for r in centres:
        for c in centres:
            if reserved[r][c]:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    dark = max(abs(dr), abs(dc)) != 1
                    m[r + dr][c + dc] = 1 if dark else 0
                    reserved[r + dr][c + dc] = True

    # Format information areas
    for i in range(9):
        for (r, c) in ((8, i), (i, 8)):
            if 0 <= r < size and 0 <= c < size and not reserved[r][c]:
                reserved[r][c] = True
    for i in range(8):
        reserved[8][size - 1 - i] = True
        reserved[size - 1 - i][8] = True

    # Dark module
    m[size - 8][8] = 1
    reserved[size - 8][8] = True

    # Version information (version 7 and up)
    if version >= 7:
        bits = _version_bits(version)
        for i in range(18):
            bit = (bits >> i) & 1
            r, c = i // 3, i % 3 + size - 11
            m[r][c] = bit
            reserved[r][c] = True
            m[c][r] = bit
            reserved[c][r] = True

    return m, reserved, size


def _version_bits(version: int) -> int:
    """18-bit BCH(18,6) version information."""
    code = version << 12
    for i in range(5, -1, -1):
        if code & (1 << (i + 12)):
            code ^= 0x1F25 << i
    return (version << 12) | code


def _format_bits(mask: int) -> int:
    """15-bit BCH(15,5) format information, XORed with the spec's mask."""
    fmt = (_EC_M_INDICATOR << 3) | mask
    code = fmt << 10
    for i in range(4, -1, -1):
        if code & (1 << (i + 10)):
            code ^= 0x537 << i
    return ((fmt << 10) | code) ^ 0x5412


def _place_data(m, reserved, codewords, size):
    bits = []
    for cw in codewords:
        for i in range(7, -1, -1):
            bits.append((cw >> i) & 1)

    idx, col, upward = 0, size - 1, True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for c in (col, col - 1):
                if not reserved[r][c]:
                    m[r][c] = bits[idx] if idx < len(bits) else 0
                    idx += 1
        upward = not upward
        col -= 2


_MASKS = [
    lambda i, j: (i + j) % 2 == 0,
    lambda i, j: i % 2 == 0,
    lambda i, j: j % 3 == 0,
    lambda i, j: (i + j) % 3 == 0,
    lambda i, j: (i // 2 + j // 3) % 2 == 0,
    lambda i, j: (i * j) % 2 + (i * j) % 3 == 0,
    lambda i, j: ((i * j) % 2 + (i * j) % 3) % 2 == 0,
    lambda i, j: ((i + j) % 2 + (i * j) % 3) % 2 == 0,
]


def _penalty(m, size) -> int:
    score = 0

    # Rule 1: runs of five or more
    for line in list(m) + [list(col) for col in zip(*m)]:
        run, prev = 1, line[0]
        for v in line[1:]:
            if v == prev:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run, prev = 1, v
        if run >= 5:
            score += 3 + (run - 5)

    # Rule 2: 2x2 blocks
    for r in range(size - 1):
        for c in range(size - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3

    # Rule 3: finder-like patterns
    pat1 = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    pat2 = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for line in list(m) + [list(col) for col in zip(*m)]:
        for i in range(size - 10):
            window = list(line[i:i + 11])
            if window == pat1 or window == pat2:
                score += 40

    # Rule 4: dark/light balance
    dark = sum(sum(row) for row in m)
    percent = dark * 100 // (size * size)
    score += 10 * (abs(percent - 50) // 5)
    return score


def _apply_format(m, size, mask):
    fmt = _format_bits(mask)
    for i in range(15):
        bit = (fmt >> i) & 1
        if i < 6:
            m[i][8] = bit
        elif i < 8:
            m[i + 1][8] = bit
        else:
            m[size - 15 + i][8] = bit
        if i < 8:
            m[8][size - 1 - i] = bit
        else:
            m[8][15 - i - 1] = bit
    m[size - 8][8] = 1


def matrix(text: str) -> list[list[int]]:
    payload = text.encode("utf-8")
    version = _pick_version(len(payload))
    codewords = _build_codewords(payload, version)

    best, best_score = None, None
    for mask in range(8):
        m, reserved, size = _new_matrix(version)
        _place_data(m, reserved, codewords, size)
        for r in range(size):
            for c in range(size):
                if not reserved[r][c] and _MASKS[mask](r, c):
                    m[r][c] ^= 1
        _apply_format(m, size, mask)
        score = _penalty(m, size)
        if best_score is None or score < best_score:
            best, best_score = m, score
    return best


def svg(text: str, scale: int = 8, quiet: int = 4,
        dark: str = "#0A3254", light: str = "#ffffff") -> str:
    m = matrix(text)
    size = len(m)
    total = (size + quiet * 2) * scale

    rects = []
    for r in range(size):
        c = 0
        while c < size:
            if m[r][c]:
                run = 1
                while c + run < size and m[r][c + run]:
                    run += 1
                x = (c + quiet) * scale
                y = (r + quiet) * scale
                rects.append(f'<rect x="{x}" y="{y}" width="{run * scale}" height="{scale}"/>')
                c += run
            else:
                c += 1

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="{total}" '
        f'viewBox="0 0 {total} {total}" shape-rendering="crispEdges" role="img" '
        f'aria-label="QR code">'
        f'<rect width="{total}" height="{total}" fill="{light}"/>'
        f'<g fill="{dark}">{"".join(rects)}</g></svg>'
    )
