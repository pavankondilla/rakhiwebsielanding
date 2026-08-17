# AiRakhi — first-access landing page

The world's first AI rakhi. Static landing page + a Google Apps Script backend that
writes every signup into a Google Sheet.

**Live:** https://pavankondilla.github.io/rakhiwebsielanding/

The custom domain (`www.airakhi.online`) is **not active**. `CNAME` was removed
from the repo and the DNS records still point away from GitHub. See
`DNS-GODADDY.md` to turn it back on.

---

## What is in here

| Path | What it is |
|---|---|
| `index.html` | The whole site. One file — no build step, no framework, no npm. |
| `404.html` | Styled not-found page for GitHub Pages. |
| `assets/` | Logo mark, favicons and the social card. **Generated — never edit by hand.** |
| `airakhi-logo.png` | The master logo. The only image you actually maintain. |
| `rebrand.ps1`, `tools/` | The rebrand tool. Rebuilds `assets/` and syncs the name across the site. |
| `.github/workflows/deploy.yml` | Publishes the site to GitHub Pages on every push to `main`. |
| `.nojekyll` | Tells GitHub Pages to serve files as-is (no Jekyll processing). |
| `robots.txt`, `sitemap.xml` | Basic SEO. |
| `DNS-GODADDY.md` | Exact GoDaddy records for the custom domain. |
| `google-apps-script/Code.gs` | The waitlist backend. Paste into Apps Script. |
| `google-apps-script/SETUP.md` | Step-by-step deployment of the backend. |

> To serve the custom domain again, restore a `CNAME` file containing
> `www.airakhi.online` **and** point DNS at GitHub (`DNS-GODADDY.md`). Once
> `CNAME` exists the workflow ships it automatically. If it disappears from a
> commit, GitHub drops the domain and the site falls back to the `github.io` URL.

There are no dependencies. The only external request is the Google Fonts
stylesheet (loaded non-blocking) and the form POST to Apps Script.

## How the form reaches the sheet

1. **Primary:** `fetch()` POST with `Content-Type: text/plain;charset=utf-8`.
   That is a *simple* CORS request, so the browser sends no `OPTIONS`
   preflight — which matters because Apps Script web apps cannot answer one.
   `Code.gs` parses the JSON body itself.
2. **Fallback:** if that request is blocked (corporate proxy, strict extension),
   the page retries over JSONP against `doGet(action=submit&callback=…)`,
   which `Code.gs` also supports.

So a signup survives networks where plain CORS would fail.

Alongside name / email / phone / segment / message / feedback, the page sends
page URL, referrer, UTM tags, device, browser, OS, language, timezone and screen
size. Those land in their own columns.

## Changing the logo or the company name

Both are one command. `rebrand.ps1` rebuilds every image in `assets/` from the
master logo **and** rewrites the name and domain everywhere they appear —
`<title>`, the OG/Twitter cards, the two-tone header and footer wordmark, the
canonical URL, `sitemap.xml`, `robots.txt`, the Apps Script backend and this
README. It is idempotent: running it twice in a row changes nothing the second
time, so run it whenever you are unsure.

```powershell
.\rebrand.ps1                     # rebuild from tools\brand.json
.\rebrand.ps1 -DryRun             # show what would change, write nothing
.\rebrand.ps1 -Check              # verify the current state, change nothing
.\rebrand.ps1 -Preview -Open      # render the assets and look at them
```

### A new logo

Drop the file in the repo root, then:

```powershell
.\rebrand.ps1 -Map -Open                          # ruler over the logo
.\rebrand.ps1 -Logo new-logo.png -Crop none -Preview -Open
```

`-Crop` says which part of the file is the emblem, because a master file is
usually a *lockup* — emblem on top, wordmark under it, tagline below that — and
the site header wants the emblem alone:

| `-Crop` | Use it when |
|---|---|
| `none` | The file is just a mark. **Start here for any new logo.** |
| `auto` | The file already has transparency, or a clear gap under the emblem. |
| `top:606` | A lockup. `-Map` writes a ruled copy of the logo — read the y value where the emblem ends. |
| `box:x,y,w,h` | You want an exact rectangle. |

The current logo is a lockup, which is why `brand.json` pins `top:606`.

### A new name

```powershell
.\rebrand.ps1 -Name "AiRakhi" -Domain airakhi.online -WebHost www.airakhi.online -Save
```

`-Save` writes the values back to `tools\brand.json` so later runs keep them.
The name is split at its last lowercase→uppercase seam (`AiRakhi` → `Ai` +
`Rakhi`) and the second half is drawn in the rose accent, in the header, the
footer and the social card.

Two things it will **not** do on its own, both on purpose:

- Phrases in `brand.json`'s `protect` list are frozen, so *Raksha Bandhan* the
  festival never gets renamed along with the company.
- `localStorage` keys like `airakhi_joined` are reported, not rewritten —
  renaming one silently logs every returning visitor out.

### Where the site says it lives

`base_url` in `tools/brand.json` is the URL the site is actually served from,
and the tool points `canonical`, `og:url`, `og:image`, `twitter:image`,
`sitemap.xml`, `robots.txt` and the 404 link at it.

Keep it honest. These tags fail *silently* — the page looks perfect while a
canonical aimed at an unwired domain hands your Google ranking to whatever is
parked there, and an `og:image` that 404s means every WhatsApp and LinkedIn
share goes out with a blank rectangle. `.\rebrand.ps1 -Check` now fails if any
of them drift.

Right now it is the GitHub Pages URL, because `airakhi.online` resolves to a
GoDaddy "launching soon" page. **When DNS actually points at GitHub Pages** and
`CNAME` is restored (`DNS-GODADDY.md`), switch it over:

```powershell
.\rebrand.ps1 -BaseUrl "https://www.airakhi.online/" -Save
```

### Everything is a setting

`tools/brand.json` is the source of truth: name, wordmark split, tagline,
domain, logo path, crop, accent colours, old names to replace, phrases to
protect, files to sync. `python tools/rebrand.py --help` lists every flag; the
PowerShell wrapper only exists to find Python and install Pillow and numpy the
first time.

## Changing the endpoint or the launch date

Both live at the top of the `<script>` block near the bottom of `index.html`:

```js
var ENDPOINT = "https://script.google.com/macros/s/…/exec";
var LAUNCH   = "2026-08-24T06:00:00+05:30";
```

## Deploying

Deployment is automated. `.github/workflows/deploy.yml` publishes to GitHub
Pages on every push to `main` — no manual step, no settings to touch:

```bash
git add -A
git commit -m "Update landing page"
git push
```

Watch it with `gh run watch`, or re-run it by hand from the **Actions** tab
(*Deploy to GitHub Pages* → *Run workflow*).

What the workflow does:

1. Stages the site with `git archive`, so **only tracked files ship**. Anything
   in `.gitignore` (`uploads/`, `*.dc.html`, `support.js`, `image-slot.js`)
   can never leak into the published site.
2. Drops repo plumbing (`.github/`, `.claude/`, `.gitattributes`) and the
   rebrand tooling (`tools/`, `rebrand.ps1`, `airakhi-logo.png`) from the
   artifact, so only the built `assets/` ship.
3. Fails only if `index.html` is missing or empty. A missing `.nojekyll` is
   recreated instead of failing, and a missing `CNAME` is just a notice.
4. Uploads and deploys via the official `actions/*-pages` actions.

It needs no npm, no rsync, and no build step, so there is nothing to break
when the runner image changes.

## Local preview

```bash
python -m http.server 8080
# then open http://localhost:8080/
```

Opening `index.html` straight off the filesystem works too, but a local server
is closer to production.
