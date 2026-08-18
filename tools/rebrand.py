#!/usr/bin/env python3
"""Rebrand the site: rebuild every image asset from one master logo, and sync
the company name and domain through every page that mentions them.

    python tools/rebrand.py                     # apply tools/brand.json
    python tools/rebrand.py --dry-run           # show what would change
    python tools/rebrand.py --name "AiRakhi" --logo new-logo.png --crop none
    python tools/rebrand.py --map               # ruler over the logo, to pick --crop
    python tools/rebrand.py --check             # verify only, change nothing

Everything is driven by tools/brand.json; the flags above just override it for
one run. The script is idempotent -- running it twice in a row is a no-op the
second time, which is what makes it safe to run whenever you are unsure.

--- Why cropping is a setting, not magic -------------------------------------

The master file is usually a *lockup*: emblem on top, wordmark under it, maybe
a tagline under that. The site header needs the emblem alone. There is no
reliable way to find where an emblem ends and lettering begins for an arbitrary
piece of artwork -- a detailed illustration and a row of letters look alike to
every cheap heuristic -- so the split is an explicit setting you can see and
change, and `--map` prints a ruler over the logo so choosing it takes seconds.

    crop = "none"        use the whole artwork (correct for a plain mark --
                         this is the safe default for a brand-new logo)
    crop = "auto"        keep existing transparency if the file has any;
                         otherwise split at the first band of clear background;
                         otherwise fall back to "none" and say so
    crop = "top:606"     everything above y=606 is the emblem
    crop = "box:x,y,w,h" exact rectangle

--- Why the background knockout is two flood fills ---------------------------

The artwork sits on a solid white field but does not meet it with a clean edge:
it carries a soft grey glow that fades out over ~20px. A global
white-to-transparent threshold would punch holes in the *light areas inside*
the emblem (VR headsets, glows) and leave the outer glow behind as a bright
halo, which is glaring on a dark header. So we flood inward from the border
through "pale and near-neutral" pixels -- that, by definition, is background --
and grade alpha by how far from white each of those pixels is. Pixels the
flood never reaches stay fully opaque.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = Path(__file__).with_name("brand.json")
ASSETS = ROOT / "assets"
PREVIEW = Path(__file__).with_name("preview")

# Assets produced, and the width each is rendered at.
MARK_WIDTH = 320
ICONS = ((180, "apple-touch-icon.png"), (64, "favicon.png"), (32, "favicon-32.png"))
CARD = (1200, 630)

# Background detection. A pixel is "pale" (candidate background) when its
# darkest channel is bright and it is close to neutral grey.
PALE_MIN, PALE_SAT = 200, 28
# Min-channel values that map to alpha 0 and alpha 255 in the graded rim.
CLEAR, OPAQUE = 252, 175

FONT_SERIF = ("georgiab.ttf", "timesbd.ttf", "DejaVuSerif-Bold.ttf", "Georgia Bold.ttf")
FONT_SANS = ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "Helvetica.ttc")
FONT_DIRS = ("C:/Windows/Fonts", "/usr/share/fonts", "/Library/Fonts", "/System/Library/Fonts")


class Fail(Exception):
    """A problem worth stopping for, reported without a traceback."""


# ---------------------------------------------------------------- config ----


def load_brand(args) -> dict:
    if not CONFIG.exists():
        raise Fail(f"missing config: {CONFIG}")
    try:
        brand = json.loads(CONFIG.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise Fail(f"{CONFIG.name} is not valid JSON -- {e}")

    for key in ("name", "logo", "crop", "tagline", "domain", "host", "base_url"):
        val = getattr(args, key, None)
        if val:
            brand[key] = val

    # Where the site is really served from. Defaults to the canonical host, but
    # a GitHub project page lives under /<repo>/, which a bare host cannot say.
    brand["base_url"] = (brand.get("base_url") or f'https://{brand["host"]}/')
    if not brand["base_url"].endswith("/"):
        brand["base_url"] += "/"
    if not re.match(r"^https?://", brand["base_url"]):
        raise Fail(f'base_url {brand["base_url"]!r} must start with http:// or https://')
    brand["og_image"] = brand.get("og_image", "assets/og-cover.jpg").lstrip("/")

    for key in ("name", "logo", "domain", "host"):
        if not brand.get(key):
            raise Fail(f'brand.json is missing "{key}"')

    # The wordmark is drawn in two colours. Split at the last lowercase ->
    # uppercase seam ("AiRakhi" -> "Ai" + "Rakhi"); fall back to halves.
    if args.name or not brand.get("name_split"):
        name = brand["name"]
        seams = [m.start() for m in re.finditer(r"(?<=[a-z0-9])(?=[A-Z])", name)]
        i = seams[-1] if seams else max(1, len(name) // 2)
        brand["name_split"] = [name[:i], name[i:]]

    head, tail = brand["name_split"]
    if head + tail != brand["name"]:
        raise Fail(f'name_split {brand["name_split"]!r} does not spell {brand["name"]!r}')

    brand["colors"] = {
        "ink": "#240A10", "cream": "#F7EAE6", "rose": "#F0657A", "gold": "#DFB05A",
        **brand.get("colors", {}),
    }
    return brand


def parse_crop(spec: str):
    """'none' | 'auto' | 'top:N' | 'box:x,y,w,h' -> ('mode', payload)."""
    spec = str(spec).strip().lower()
    if spec in ("none", "whole", "full"):
        return "none", None
    if spec == "auto":
        return "auto", None
    if spec.startswith("top:"):
        try:
            return "top", int(spec[4:])
        except ValueError:
            raise Fail(f"crop {spec!r}: 'top:' needs a whole number of pixels, e.g. top:606")
    if spec.startswith("box:"):
        parts = spec[4:].split(",")
        if len(parts) != 4:
            raise Fail(f"crop {spec!r}: 'box:' needs x,y,w,h")
        try:
            x, y, w, h = (int(p) for p in parts)
        except ValueError:
            raise Fail(f"crop {spec!r}: 'box:' values must be whole numbers")
        if w <= 0 or h <= 0:
            raise Fail(f"crop {spec!r}: width and height must be positive")
        return "box", (x, y, w, h)
    raise Fail(f"crop {spec!r} is not one of: none, auto, top:N, box:x,y,w,h")


def hexrgb(s: str):
    s = s.lstrip("#")
    if len(s) != 6:
        raise Fail(f"colour {s!r} must be a 6-digit hex like #240A10")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


# ------------------------------------------------------------ image core ----


def flood(mask, seed, np):
    """Grow `seed` through `mask` until stable. Run-based, so it converges in a
    handful of sweeps instead of one per pixel of path length."""
    cur = seed & mask
    h = mask.shape[0]
    for _ in range(64):
        before = cur.sum()
        for order in (range(h), range(h - 1, -1, -1)):
            for y in order:
                row = mask[y]
                line = cur[y]
                if y > 0:
                    line |= cur[y - 1] & row
                if y < h - 1:
                    line |= cur[y + 1] & row
                idx = np.where(row)[0]
                if idx.size:
                    breaks = np.where(np.diff(idx) > 1)[0]
                    starts = np.concatenate(([0], breaks + 1))
                    ends = np.concatenate((breaks, [idx.size - 1]))
                    for s, e in zip(starts, ends):
                        seg = slice(idx[s], idx[e] + 1)
                        if line[seg].any():
                            line[seg] = True
                cur[y] = line
        if cur.sum() == before:
            break
    return cur


def knockout(im, np, Image):
    """RGB artwork on a pale field -> RGBA with the field cleared.

    Returns (rgba, alpha, background_mask). If the source already carries real
    transparency we trust it and skip the flood entirely."""
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA")
        alpha = np.array(rgba.getchannel("A"))
        if (alpha < 250).mean() > 0.01:
            return rgba, alpha, alpha < 16

    rgb = im.convert("RGB")
    a = np.array(rgb).astype(np.int16)
    mn = a.min(axis=2)
    sat = a.max(axis=2) - mn
    pale = (mn >= PALE_MIN) & (sat <= PALE_SAT)

    edge = np.zeros_like(pale)
    edge[0, :] = edge[-1, :] = True
    edge[:, 0] = edge[:, -1] = True
    background = flood(pale, edge, np)

    grad = np.clip((CLEAR - mn) * (255.0 / (CLEAR - OPAQUE)), 0, 255)
    alpha = np.where(background, grad, 255).astype(np.uint8)
    rgba = Image.fromarray(np.dstack([np.array(rgb), alpha]), "RGBA")
    return rgba, alpha, background


def auto_split(alpha, np) -> int | None:
    """Find a band of clear background separating a top emblem from lettering.

    Only fires on a genuine gap -- a run of rows with (almost) no ink. Lockups
    drawn with breathing room have one; tightly kerned ones do not, and for
    those this returns None so the caller can fall back and say so."""
    ink = (alpha > 16).sum(axis=1)
    rows = np.flatnonzero(ink)
    if rows.size == 0:
        return None
    top, bot = int(rows[0]), int(rows[-1])
    height = bot - top + 1
    quiet = ink <= max(2, int(0.004 * alpha.shape[1]))

    y = top + int(0.20 * height)  # never split off a sliver
    limit = top + int(0.85 * height)
    gap_needed = max(6, int(0.015 * height))
    while y < limit:
        if quiet[y]:
            end = y
            while end < limit and quiet[end]:
                end += 1
            if end - y >= gap_needed:
                return y
            y = end
        y += 1
    return None


def isolate(rgba, alpha, background, mode, payload, np, Image, log):
    """Apply the crop mode and return the emblem as a tightly trimmed RGBA."""
    h, w = alpha.shape

    if mode == "auto":
        cut = auto_split(alpha, np)
        if cut is None:
            log("crop auto: no clear gap in the artwork -- using the whole thing."
                "\n            If it is a lockup, run --map and set crop to top:<y>.")
            mode = "none"
        else:
            log(f"crop auto: clear background band found at y={cut}")
            mode, payload = "top", cut

    if mode == "box":
        x, y, bw, bh = payload
        if x < 0 or y < 0 or x + bw > w or y + bh > h:
            raise Fail(f"crop box {payload} falls outside the {w}x{h} logo")
        keep = np.zeros_like(background)
        keep[y:y + bh, x:x + bw] = True
    elif mode == "top":
        cut = payload
        if not 0 < cut <= h:
            raise Fail(f"crop top:{cut} is outside the logo's {h}px height")
        # Flood from the widest row above the cut, so specks that belong to the
        # lettering below cannot survive inside the crop box.
        band = alpha > 16
        band[cut:, :] = False
        rows = band.sum(axis=1)
        if not rows.any():
            raise Fail(f"crop top:{cut} leaves nothing above the cut -- try a larger value")
        seed = np.zeros_like(band)
        seed[int(np.argmax(rows))] = band[int(np.argmax(rows))]
        emblem = flood(band, seed, np)
        # Keep the few pixels of feathered rim hugging the mark; without the
        # proximity limit, stray graded pixels show up as specks under it.
        keep = emblem | (dilate(emblem, 4, np) & background)
    else:  # none
        keep = np.ones_like(background)

    masked = np.where(keep, alpha, 0).astype(np.uint8)
    if not (masked > 8).any():
        raise Fail("the crop selected no visible pixels -- check the crop setting")

    out = Image.fromarray(np.dstack([np.array(rgba.convert("RGB")), masked]), "RGBA")
    return trim(out), mode


def dilate(mask, n, np):
    out = mask.copy()
    for _ in range(n):
        grown = out.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            grown |= np.roll(out, (dy, dx), (0, 1))
        out = grown
    return out


def trim(img):
    box = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if box is None:
        raise Fail("the artwork is fully transparent")
    return img.crop(box)


def square(img, Image, pad=0.06):
    w, h = img.size
    side = int(max(w, h) * (1 + pad * 2))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - w) // 2, (side - h) // 2), img)
    return canvas


def fit(img, width, Image):
    w, h = img.size
    return img.resize((width, max(1, round(width * h / w))), Image.LANCZOS)


def load_font(names, size, ImageFont, log):
    for directory in FONT_DIRS:
        base = Path(directory)
        if not base.is_dir():
            continue
        for name in names:
            for path in (base / name, *base.glob(f"**/{name}")):
                try:
                    return ImageFont.truetype(str(path), size)
                except (OSError, ValueError):
                    continue
    log(f"note: none of {names[0]}... found -- the social card falls back to a bitmap font")
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 9.2 has no sized default
        return ImageFont.load_default()


# ------------------------------------------------------------- asset run ----


def build_assets(brand, dry_run, log) -> list[str]:
    try:
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as e:
        raise Fail(
            f"missing Python package: {e.name}\n"
            f"    fix it with:  python -m pip install --upgrade pillow numpy"
        )

    src = ROOT / brand["logo"]
    if not src.exists():
        raise Fail(f"logo not found: {src}\n    put the file there, or pass --logo <path>")
    try:
        im = Image.open(src)
        im.load()
    except Exception as e:
        raise Fail(f"cannot read {src.name} as an image -- {e}")
    if min(im.size) < 256:
        raise Fail(f"{src.name} is {im.size[0]}x{im.size[1]}; use at least 512x512 for crisp icons")
    log(f"source     {src.name}  {im.size[0]}x{im.size[1]}  {im.mode}")

    mode, payload = parse_crop(brand["crop"])
    rgba, alpha, background = knockout(im, np, Image)
    emblem, used = isolate(rgba, alpha, background, mode, payload, np, Image, log)
    log(f"emblem     {emblem.size[0]}x{emblem.size[1]}  (crop {used})")

    ink = hexrgb(brand["colors"]["ink"])
    cream = hexrgb(brand["colors"]["cream"])
    rose = hexrgb(brand["colors"]["rose"])
    gold = hexrgb(brand["colors"]["gold"])

    written = []

    def save(img, name, **kw):
        written.append(name)
        if not dry_run:
            ASSETS.mkdir(exist_ok=True)
            img.save(ASSETS / name, optimize=True, **kw)

    # The header/footer mark keeps its natural aspect, so it renders as large as
    # the header allows instead of being padded into a square.
    save(fit(emblem, MARK_WIDTH, Image), "logo-mark.png")

    # Icons are square and composited onto ink, because iOS and Android flatten
    # transparency onto white.
    sq = square(emblem, Image)
    for size, name in ICONS:
        icon = Image.new("RGBA", (size, size), ink + (255,))
        icon.alpha_composite(sq.resize((size, size), Image.LANCZOS))
        save(icon.convert("RGB"), name)

    # Social card. A lockup's own wordmark is drawn for a white page and goes
    # invisible on ink, so the card re-sets the name in the site's colours.
    cw, ch = CARD
    card = Image.new("RGBA", CARD, ink + (255,))
    mark = fit(emblem, int(cw * 0.36), Image)
    if mark.size[1] > ch * 0.52:
        mark = mark.resize(
            (max(1, round(mark.size[0] * (ch * 0.52) / mark.size[1])), int(ch * 0.52)),
            Image.LANCZOS,
        )
    top = int(ch * 0.12)
    card.alpha_composite(mark, ((cw - mark.size[0]) // 2, top))

    d = ImageDraw.Draw(card)
    serif = load_font(FONT_SERIF, 84, ImageFont, log)
    sans = load_font(FONT_SANS, 30, ImageFont, log)

    head, tail = brand["name_split"]
    w_head = d.textlength(head, font=serif)
    w_tail = d.textlength(tail, font=serif)
    x = (cw - (w_head + w_tail)) / 2
    y = top + mark.size[1] + 22
    d.text((x, y), head, font=serif, fill=cream + (255,))
    d.text((x + w_head, y), tail, font=serif, fill=rose + (255,))

    tag = brand.get("tagline", "")
    if tag:
        d.text(((cw - d.textlength(tag, font=sans)) / 2, y + 104), tag, font=sans, fill=gold + (255,))

    written.append("og-cover.jpg")
    if not dry_run:
        card.convert("RGB").save(
            ASSETS / "og-cover.jpg", quality=88, optimize=True, progressive=True
        )

    return written


def write_map(brand, log):
    """Draw a labelled ruler over the master logo so picking crop top:N is a
    matter of reading a number off the image."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    src = ROOT / brand["logo"]
    im = Image.open(src).convert("RGB")
    w, h = im.size
    scale = 640 / w
    canvas = im.resize((640, round(h * scale)), Image.LANCZOS).convert("RGB")
    d = ImageDraw.Draw(canvas, "RGBA")
    font = load_font(FONT_SANS, 13, ImageFont, log)

    step = 50 if h <= 1400 else 100
    for y in range(0, h, step):
        yy = round(y * scale)
        d.line([(0, yy), (640, yy)], fill=(0, 0, 0, 90), width=1)
        d.rectangle([0, yy, 44, yy + 16], fill=(0, 0, 0, 170))
        d.text((4, yy + 1), str(y), font=font, fill=(255, 255, 255, 255))

    mode, payload = parse_crop(brand["crop"])
    if mode == "top":
        yy = round(payload * scale)
        d.line([(0, yy), (640, yy)], fill=(255, 40, 90, 255), width=3)
        d.text((470, max(0, yy - 18)), f"crop top:{payload}", font=font, fill=(255, 40, 90, 255))

    PREVIEW.mkdir(exist_ok=True)
    out = PREVIEW / "crop-map.png"
    canvas.save(out)
    log(f"wrote      {out.relative_to(ROOT)}  (read the y value where the emblem ends)")
    return out


def write_preview(brand, log):
    """Compose every generated asset on the site's ink background, so one look
    confirms the rebrand before it is committed."""
    from PIL import Image, ImageDraw, ImageFont

    ink = hexrgb(brand["colors"]["ink"])
    cream = hexrgb(brand["colors"]["cream"])
    canvas = Image.new("RGB", (980, 700), ink)
    d = ImageDraw.Draw(canvas)
    font = load_font(FONT_SANS, 15, ImageFont, log)

    x, y = 30, 26
    for name in ("logo-mark.png", "apple-touch-icon.png", "favicon.png", "favicon-32.png"):
        path = ASSETS / name
        if not path.exists():
            continue
        img = Image.open(path).convert("RGBA")
        d.text((x, y), f"{name}  {img.size[0]}x{img.size[1]}", font=font, fill=cream)
        canvas.paste(img, (x, y + 22), img)
        y += img.size[1] + 46

    card = ASSETS / "og-cover.jpg"
    if card.exists():
        img = Image.open(card).convert("RGB")
        img = img.resize((540, round(540 * img.size[1] / img.size[0])), Image.LANCZOS)
        d.text((400, 26), f"og-cover.jpg  {CARD[0]}x{CARD[1]}", font=font, fill=cream)
        canvas.paste(img, (400, 48))

    PREVIEW.mkdir(exist_ok=True)
    out = PREVIEW / "assets.png"
    canvas.save(out)
    log(f"wrote      {out.relative_to(ROOT)}")
    return out


# ------------------------------------------------------------ text sync ----


def build_replacements(brand) -> dict[str, str]:
    """alias -> replacement, for one single-pass regex."""
    repl: dict[str, str] = {}
    for alias in brand.get("name_aliases", []) + [brand["name"]]:
        repl[alias] = brand["name"]
    for alias in brand.get("domain_aliases", []) + [brand["domain"], brand["host"]]:
        repl[alias] = brand["host"] if alias.lower().startswith("www.") else brand["domain"]
    return {k: v for k, v in repl.items() if k}


def sync_text(brand, dry_run, log):
    repl = build_replacements(brand)
    protect = sorted(brand.get("protect", []), key=len, reverse=True)

    # Longest alias first, so "www.airakhi.online" wins over "airakhi.online"
    # and nothing gets substituted twice in one pass.
    alt = "|".join(re.escape(a) for a in sorted(repl, key=len, reverse=True))
    brand_re = re.compile(alt)
    prot_re = re.compile("|".join(re.escape(p) for p in protect)) if protect else None

    head, tail = brand["name_split"]
    rose = "var(--rose)"
    wordmark_re = re.compile(r'(<span class="name"([^>]*)>).*?</span></span>', re.S)
    wordmark_to = (
        rf'\1{re.escape(head)}<span style="color:{rose}">{re.escape(tail)}</span></span>'
    )

    total, touched = 0, []
    for rel in brand.get("sync_files", []):
        path = ROOT / rel
        if not path.exists():
            log(f"skip       {rel} (not present)")
            continue
        original = path.read_text(encoding="utf-8")

        # Freeze protected phrases so a brand alias inside one cannot be hit.
        frozen, guards = original, []
        if prot_re:
            def freeze(m):
                guards.append(m.group(0))
                return f"\x00{len(guards) - 1}\x00"
            frozen = prot_re.sub(freeze, frozen)

        updated, n = brand_re.subn(lambda m: repl[m.group(0)], frozen)
        updated, n2 = wordmark_re.subn(wordmark_to, updated)
        if guards:
            updated = re.sub(r"\x00(\d+)\x00", lambda m: guards[int(m.group(1))], updated)

        if updated != original:
            changed = sum(1 for a, b in zip(original.splitlines(), updated.splitlines()) if a != b)
            touched.append((rel, changed))
            total += changed
            if not dry_run:
                path.write_text(updated, encoding="utf-8", newline="")
        _ = n, n2

    if touched:
        for rel, changed in touched:
            log(f"{'would edit' if dry_run else 'edited    '} {rel}  ({changed} lines)")
    else:
        log("text       already in sync -- nothing to change")
    return total


def sync_urls(brand, dry_run, log):
    """Point every absolute self-reference at the URL the site is really served
    from.

    These are the tags nobody notices until they are wrong. A canonical aimed at
    a parked domain hands your ranking to the parking page; an og:image that
    404s means every WhatsApp and LinkedIn share of a launch page goes out with
    a blank rectangle. Both fail silently -- the page itself looks perfect.

    Kept separate from the brand-name sweep because these are structural URLs,
    not prose: each one is matched by the tag it lives in and replaced whole,
    never by substring, so re-running can never double up a path."""
    base = brand["base_url"]
    og = base + brand["og_image"]

    rules = [
        ("index.html",  r'(<link rel="canonical" href=")([^"]*)(">)',            base),
        ("index.html",  r'(<meta property="og:url" content=")([^"]*)(">)',       base),
        ("index.html",  r'(<meta property="og:image" content=")([^"]*)(">)',     og),
        ("index.html",  r'(<meta name="twitter:image" content=")([^"]*)(">)',    og),
        ("sitemap.xml", r'(<loc>)([^<]*)(</loc>)',                               base),
        ("robots.txt",  r'(Sitemap:[ \t]*)(\S+)()',                    base + "sitemap.xml"),
        ("404.html",    r'(<a href=")(https?://[^"]*)(">)',                      base),
    ]

    # Social profiles live in brand.json too, matched on the class rather than
    # the old URL, so moving a handle is a one-line edit and never a find-and-
    # replace through the markup.
    for network, url in (brand.get("social") or {}).items():
        if url:
            rules.append(
                ("index.html", rf'(<a class="social" href=")([^"]*)(" target)', url)
            )

    # The GA4 measurement ID appears twice per page -- once in the loader URL,
    # once in the config call -- and a page where those two disagree still
    # loads, still shows no error, and quietly reports to the wrong property.
    # Both are pinned to brand.json so they cannot drift apart.
    ga4 = (brand.get("analytics") or {}).get("ga4", "")
    if ga4:
        for page in ("index.html", "404.html"):
            rules.append((page, r'(gtag/js\?id=)([^"]*)(")', ga4))
            rules.append((page, r"(gtag\('config', ')([^']*)('\))", ga4))

    changes: dict[str, list[tuple[str, str]]] = {}
    for rel, pattern, target in rules:
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")

        def swap(m):
            if m.group(2) != target:
                changes.setdefault(rel, []).append((m.group(2), target))
            return m.group(1) + target + m.group(3)

        updated = re.sub(pattern, swap, text)
        if updated != text and not dry_run:
            path.write_text(updated, encoding="utf-8", newline="")

    if changes:
        verb = "would repoint" if dry_run else "repointed"
        for rel, pairs in changes.items():
            for old, new in pairs:
                log(f"{verb} {rel}")
                log(f"           {old}  ->  {new}")
    else:
        log(f"urls       already point at {base}")
    return sum(len(v) for v in changes.values())


def flag_manual(brand, log):
    """Identifiers a text sweep must not touch on its own: localStorage keys and
    the like, where a blind rename would silently drop returning visitors."""
    slugs = set()
    for alias in brand.get("name_aliases", []):
        low = alias.lower()
        slugs.add(re.sub(r"[^a-z0-9]", "", low))   # "Bandhan.ai" -> "bandhanai"
        slugs.add(re.split(r"[^a-z0-9]", low)[0])  # "Bandhan.ai" -> "bandhan"
    slugs.discard(brand["name"].lower())
    slugs.discard("")
    hits = []
    for rel in brand.get("sync_files", []):
        path = ROOT / rel
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for slug in slugs:
                if slug and re.search(rf'["\']{re.escape(slug)}_\w+["\']', line):
                    hits.append(f"{rel}:{i}  {line.strip()[:88]}")
    if hits:
        log("\nleft alone on purpose (storage keys -- renaming these logs returning visitors out):")
        for h in hits:
            log(f"  {h}")


# --------------------------------------------------------------- verify ----


def verify(brand, log) -> list[str]:
    problems = []
    for name in ["logo-mark.png", "og-cover.jpg"] + [n for _, n in ICONS]:
        path = ASSETS / name
        if not path.exists():
            problems.append(f"missing asset: assets/{name}")
        elif path.stat().st_size < 400:
            problems.append(f"suspiciously small: assets/{name} ({path.stat().st_size} bytes)")

    index = ROOT / "index.html"
    if index.exists():
        text = index.read_text(encoding="utf-8")
        if brand["name"] not in text:
            problems.append(f'index.html never mentions "{brand["name"]}"')
        for alias in brand.get("name_aliases", []):
            if alias != brand["name"] and re.search(rf"\b{re.escape(alias)}\b", text):
                problems.append(f'index.html still contains the old name "{alias}"')
        for ref in ("assets/logo-mark.png", "assets/favicon.png", "assets/apple-touch-icon.png"):
            if ref not in text:
                problems.append(f"index.html no longer references {ref}")

        # The silent-failure tags. Wrong here and the page still looks perfect.
        base, og = brand["base_url"], brand["base_url"] + brand["og_image"]
        for label, pattern, want in (
            ("canonical", r'<link rel="canonical" href="([^"]*)"', base),
            ("og:url", r'<meta property="og:url" content="([^"]*)"', base),
            ("og:image", r'<meta property="og:image" content="([^"]*)"', og),
            ("twitter:image", r'<meta name="twitter:image" content="([^"]*)"', og),
        ):
            m = re.search(pattern, text)
            if not m:
                problems.append(f"index.html has no {label} tag")
            elif m.group(1) != want:
                problems.append(f"{label} points at {m.group(1)} -- should be {want}")

        for network, url in (brand.get("social") or {}).items():
            if url and url not in text:
                problems.append(f"index.html does not link to the {network} profile {url}")

    ga4 = (brand.get("analytics") or {}).get("ga4", "")
    for page in ("index.html", "404.html"):
        path = ROOT / page
        if not path.exists():
            continue
        body = path.read_text(encoding="utf-8")
        found = set(re.findall(r"G-[A-Z0-9]{6,}", body))
        if ga4:
            if not found:
                problems.append(f"{page} carries no analytics tag")
            elif found != {ga4}:
                problems.append(f"{page} reports to {sorted(found)} -- should be only {ga4}")
        elif found:
            problems.append(f"{page} still has analytics {sorted(found)} but brand.json sets none")

    sm = ROOT / "sitemap.xml"
    if sm.exists():
        m = re.search(r"<loc>([^<]*)</loc>", sm.read_text(encoding="utf-8"))
        if m and m.group(1) != brand["base_url"]:
            problems.append(f"sitemap.xml lists {m.group(1)} -- should be {brand['base_url']}")

    if problems:
        log("\nFAILED:")
        for p in problems:
            log(f"  - {p}")
    else:
        log("\nverified   assets present, markup consistent, no stale brand names")
    return problems


# ----------------------------------------------------------------- main ----


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="rebrand.py",
        description="Rebuild brand assets and sync the company name across the site.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Defaults come from tools/brand.json. Edit that file to make a change stick.",
    )
    p.add_argument("--name", help='company name, e.g. "AiRakhi"')
    p.add_argument("--logo", help="master logo, relative to the repo root")
    p.add_argument("--crop", help="none | auto | top:N | box:x,y,w,h")
    p.add_argument("--tagline", help="one line under the name on the social card")
    p.add_argument("--domain", help='registrable domain, e.g. "airakhi.online"')
    p.add_argument("--host", help='canonical host, e.g. "www.airakhi.online"')
    p.add_argument("--base-url", dest="base_url",
                   help="URL the site is really served from, e.g. https://user.github.io/repo/")
    p.add_argument("--only", choices=("assets", "text"), help="run just one half")
    p.add_argument("--dry-run", action="store_true", help="report changes, write nothing")
    p.add_argument("--check", action="store_true", help="verify the current state and exit")
    p.add_argument("--map", action="store_true", help="write a ruler over the logo and exit")
    p.add_argument("--preview", action="store_true", help="also render tools/preview/assets.png")
    p.add_argument("--save", action="store_true", help="write the overrides back to brand.json")
    p.add_argument("--traceback", action="store_true", help="show the full Python traceback")
    args = p.parse_args(argv)

    def log(msg=""):
        print(msg, flush=True)

    try:
        brand = load_brand(args)

        if args.map:
            write_map(brand, log)
            return 0

        log(f'brand      {brand["name"]}   ({brand["name_split"][0]}|{brand["name_split"][1]})')
        log(f'domain     {brand["host"]}')
        log("")

        if args.check:
            return 2 if verify(brand, log) else 0

        if args.only != "text":
            names = build_assets(brand, args.dry_run, log)
            verb = "would write" if args.dry_run else "wrote     "
            for name in names:
                path = ASSETS / name
                size = f"{path.stat().st_size:,} bytes" if path.exists() else "-"
                log(f"{verb} assets/{name:<22} {size}")
            log("")

        if args.only != "assets":
            sync_text(brand, args.dry_run, log)
            sync_urls(brand, args.dry_run, log)
            flag_manual(brand, log)

        if args.save and not args.dry_run:
            for key in ("name", "logo", "crop", "tagline", "domain", "host"):
                if getattr(args, key, None):
                    brand[key] = getattr(args, key)
            CONFIG.write_text(json.dumps(brand, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")
            log(f"\nsaved      {CONFIG.relative_to(ROOT)}")

        if args.preview and not args.dry_run:
            write_preview(brand, log)

        if args.dry_run:
            log("\ndry run -- nothing was written")
            return 0

        return 2 if verify(brand, log) else 0

    except Fail as e:
        print(f"\nrebrand: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nrebrand: interrupted", file=sys.stderr)
        return 130
    except Exception as e:
        if args.traceback:
            raise
        print(f"\nrebrand: unexpected {type(e).__name__}: {e}"
              f"\n         re-run with --traceback for the full detail", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
