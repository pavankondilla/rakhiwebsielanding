# Bandhan.ai — first-access landing page

The world's first AI rakhi. Static landing page + a Google Apps Script backend that
writes every signup into a Google Sheet.

**Live:** https://www.airakhi.online
**GitHub Pages URL:** https://pavankondilla.github.io/rakhiwebsielanding/ (redirects to the custom domain once DNS is live)

---

## What is in here

| Path | What it is |
|---|---|
| `index.html` | The whole site. One file — no build step, no framework, no npm. |
| `404.html` | Styled not-found page for GitHub Pages. |
| `CNAME` | The custom domain. GitHub reads this file to serve www.airakhi.online. |
| `.nojekyll` | Tells GitHub Pages to serve files as-is (no Jekyll processing). |
| `robots.txt`, `sitemap.xml` | Basic SEO. |
| `DNS-GODADDY.md` | Exact GoDaddy records for the custom domain. |
| `google-apps-script/Code.gs` | The waitlist backend. Paste into Apps Script. |
| `google-apps-script/SETUP.md` | Step-by-step deployment of the backend. |

> Do not delete `CNAME`. If it disappears from a commit, GitHub drops the
> custom domain and the site falls back to the `github.io` URL.

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

GitHub Pages serves `main` / root. Any push to `main` republishes within a
minute or so:

```bash
git add -A
git commit -m "Update landing page"
git push
```

## Local preview

```bash
python -m http.server 8080
# then open http://localhost:8080/
```

Opening `index.html` straight off the filesystem works too, but a local server
is closer to production.
