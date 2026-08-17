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
| `assets/` | Logo mark, favicons and the social card, generated from `airakhi-logo.png`. |
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
2. Drops repo plumbing (`.github/`, `.claude/`, `.gitattributes`) from the artifact.
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
