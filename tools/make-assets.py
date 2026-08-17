"""Build web assets from airakhi-logo.png.

The source is a 1024x1024 RGB lockup on a solid white field: emblem on top,
"Airakhi" wordmark below it, tagline at the bottom. We need the emblem alone,
knocked out of its background, to sit in a dark header.

Two flood fills do the work:
  1. From the border, through white -> that is the background, so alpha 0.
     (A global white->transparent threshold would punch holes in the light
     areas *inside* the emblem: VR headsets, glows.)
  2. From the emblem's centre, through what is left -> that is the emblem.
     Cropping to its bounding box is exact, so no wordmark letter-tops leak
     into the mark and no part of the emblem gets sliced off.
"""
import os

import numpy as np
from PIL import Image

SRC = "airakhi-logo.png"
OUT = "assets"
INK = (36, 10, 16)  # --ink, the site background


def flood(mask, seed):
    """Grow `seed` through `mask` until stable. Run-based, so it converges in
    a handful of sweeps instead of one per pixel of path length."""
    cur = seed & mask
    h = mask.shape[0]
    for _ in range(64):
        before = cur.sum()
        for ys in (range(h), range(h - 1, -1, -1)):
            for y in ys:
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


im = Image.open(SRC).convert("RGB")
a = np.array(im).astype(np.int16)

# 1. Knock out the background.
#
# The artwork does not sit on the white field with a clean edge -- it carries a
# soft grey glow that fades out over ~20px. A hard threshold leaves that glow
# behind as a bright halo, which is glaring on a dark header. So the fill uses
# a *loose* definition of background (anything pale and near-neutral), and
# alpha is then graded by how far from white each of those pixels is. Pixels
# the fill never reaches -- the light areas enclosed by the artwork, such as
# the VR headsets -- stay fully opaque.
mn = a.min(axis=2)
sat = a.max(axis=2) - mn
pale = (mn >= 200) & (sat <= 28)

edge = np.zeros_like(pale)
edge[0, :] = edge[-1, :] = True
edge[:, 0] = edge[:, -1] = True
background = flood(pale, edge)

CLEAR, OPAQUE = 252, 175  # min-channel values that map to alpha 0 and 255
grad = np.clip((CLEAR - mn) * (255.0 / (CLEAR - OPAQUE)), 0, 255)
alpha = np.where(background, grad, 255).astype(np.uint8)

full = Image.fromarray(np.dstack([np.array(im), alpha]), "RGBA")

# 2. Isolate the emblem from the centre of the swoosh. The swoosh's bottom
# vertex touches the wordmark's ascenders, so connectivity alone runs straight
# into the lettering -- CUT is the baseline of the swoosh, below which nothing
# belongs to the mark.
CUT = 606
opaque = alpha > 16
opaque[CUT:, :] = False
seed = np.zeros_like(opaque)
seed[300:360, 480:560] = True
emblem_mask = flood(opaque, seed)

# Keep the emblem plus the few pixels of feathered rim hugging it. Without the
# proximity limit, stray graded pixels from the wordmark below survive inside
# the crop box and show up as specks under the mark.
def dilate(mask, n):
    out = mask.copy()
    for _ in range(n):
        grown = out.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            grown |= np.roll(out, (dy, dx), (0, 1))
        out = grown
    return out


keep = emblem_mask | (dilate(emblem_mask, 4) & background)
ys, xs = np.where(keep & (alpha > 8))
box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
print("emblem bbox:", box)

emblem = Image.fromarray(
    np.dstack([np.array(im), np.where(keep, alpha, 0).astype(np.uint8)]), "RGBA"
).crop(box)


def trim(img):
    return img.crop(img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox())


def square(img, pad=0.06):
    img = trim(img)
    w, h = img.size
    side = int(max(w, h) * (1 + pad * 2))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - w) // 2, (side - h) // 2), img)
    return canvas


def fit(img, width):
    w, h = img.size
    return img.resize((width, max(1, round(width * h / w))), Image.LANCZOS)


# The header/footer mark keeps its natural wide aspect, so it renders as large
# as the header allows instead of being padded into a square.
fit(emblem, 320).save(f"{OUT}/logo-mark.png", optimize=True)

# Icons are square, and composited onto ink because iOS/Android flatten
# transparency onto white.
sq = square(emblem)
for size, name in ((180, "apple-touch-icon.png"), (64, "favicon.png"), (32, "favicon-32.png")):
    icon = Image.new("RGBA", (size, size), INK + (255,))
    icon.alpha_composite(sq.resize((size, size), Image.LANCZOS))
    icon.convert("RGB").save(f"{OUT}/{name}", optimize=True)

# Social card, 1200x630. The source lockup's wordmark and tagline are dark
# navy -- drawn for a white page, invisible on ink -- so the card uses the
# emblem plus the site's own typography and colours instead.
from PIL import ImageDraw, ImageFont

CREAM, ROSE, GOLD = (247, 234, 230), (240, 101, 122), (223, 176, 90)
card = Image.new("RGBA", (1200, 630), INK + (255,))
mark = fit(emblem, 430)
card.alpha_composite(mark, ((1200 - mark.size[0]) // 2, 74))

d = ImageDraw.Draw(card)
serif = ImageFont.truetype("C:/Windows/Fonts/georgiab.ttf", 84)
sans = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 30)

# "Ai" cream + "Rakhi" rose, centred as one word.
w_ai = d.textlength("Ai", font=serif)
w_rk = d.textlength("Rakhi", font=serif)
x = (1200 - (w_ai + w_rk)) / 2
y = 74 + mark.size[1] + 22
d.text((x, y), "Ai", font=serif, fill=CREAM + (255,))
d.text((x + w_ai, y), "Rakhi", font=serif, fill=ROSE + (255,))

tag = "The world's first AI rakhi"
d.text(((1200 - d.textlength(tag, font=sans)) / 2, y + 104), tag, font=sans, fill=GOLD + (255,))

card.convert("RGB").save(f"{OUT}/og-cover.jpg", quality=88, optimize=True, progressive=True)

for f in sorted(os.listdir(OUT)):
    print(f"  {f:24} {os.path.getsize(os.path.join(OUT, f)):>7,} bytes")
