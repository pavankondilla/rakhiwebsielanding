# Pointing www.airakhi.online (GoDaddy) at GitHub Pages

The repo contains a `CNAME` file holding `www.airakhi.online`. GitHub reads it
and serves the site on that hostname. The other half is DNS, which lives in
GoDaddy.

The CNAME target is `pavankondilla.github.io` — **the username only, never the
repo name (`rakhiwebsielanding`), no `https://`, no trailing slash.**

---

## 1. Open the DNS editor

GoDaddy → **My Products** → find `airakhi.online` → **DNS** →
**Manage DNS** / *Manage Zones*.

## 2. Delete GoDaddy's parking records first

A fresh GoDaddy domain ships with records that will fight yours. Delete these
if present:

| Type | Name | Value |
|---|---|---|
| A | `@` | `Parked` or an IP like `76.223.105.230` / `13.248.243.5` |
| CNAME | `www` | `@` or `airakhi.online` |

Also check **Domain Settings → Forwarding** and remove any domain or subdomain
forwarding. GoDaddy forwarding silently overrides DNS and is the single most
common reason a Pages custom domain never goes live.

Leave `MX`, `TXT` (SPF/DKIM) and the `_domainconnect` record alone — those are
email and GoDaddy plumbing.

## 3. Add these records

**The www record — this is the one that actually serves the site:**

| Type | Name | Value | TTL |
|---|---|---|---|
| CNAME | `www` | `pavankondilla.github.io` | 600 seconds |

**The apex records — so `airakhi.online` without `www` redirects to `www`:**

| Type | Name | Value | TTL |
|---|---|---|---|
| A | `@` | `185.199.108.153` | 600 |
| A | `@` | `185.199.109.153` | 600 |
| A | `@` | `185.199.110.153` | 600 |
| A | `@` | `185.199.111.153` | 600 |

All four A records are required — they are GitHub's Pages load balancers, and
using fewer than four leaves you with no failover.

**Optional, for IPv6-only mobile networks (Jio, some carriers):**

| Type | Name | Value |
|---|---|---|
| AAAA | `@` | `2606:50c0:8000::153` |
| AAAA | `@` | `2606:50c0:8001::153` |
| AAAA | `@` | `2606:50c0:8002::153` |
| AAAA | `@` | `2606:50c0:8003::153` |

Save.

## 4. Wait, then verify

GoDaddy usually propagates in 10–30 minutes (it can take up to 48 hours, but
rarely does). Check from any terminal:

```bash
nslookup www.airakhi.online
# want: canonical name = pavankondilla.github.io  ->  185.199.10x.153

nslookup airakhi.online
# want: the four 185.199.10x.153 addresses
```

Or use https://dnschecker.org and search `www.airakhi.online` as CNAME.

## 5. Turn on HTTPS

Once DNS resolves, in the repo: **Settings → Pages**. Under *Custom domain* it
should show `www.airakhi.online` with a green **DNS check successful**.

Tick **Enforce HTTPS**. If the box is greyed out, GitHub is still issuing the
Let's Encrypt certificate — that takes up to an hour after DNS goes green.
Come back and tick it; without it visitors get a browser security warning.

## 6. What you end up with

| URL | Behaviour |
|---|---|
| `https://www.airakhi.online` | The site (primary) |
| `http://www.airakhi.online` | 301 → https |
| `https://airakhi.online` | 301 → `https://www.airakhi.online` |
| `https://pavankondilla.github.io/rakhiwebsielanding/` | 301 → the custom domain |

---

## If it does not work

| Symptom | Cause | Fix |
|---|---|---|
| GoDaddy parking page still shows | Old A record or forwarding still set | Redo step 2 |
| `NXDOMAIN` / does not resolve | Records not saved, or still propagating | Recheck the zone, wait 30 min |
| GitHub says *"domain does not resolve to the GitHub Pages server"* | CNAME points at the repo instead of the user | Value must be `pavankondilla.github.io` |
| 404 on the custom domain | `CNAME` file missing from the repo, or Pages source is wrong branch | Confirm `CNAME` is committed at repo root and Pages source is `main` / `/` |
| *Enforce HTTPS* greyed out | Certificate still being issued | Wait up to an hour, then retick |
| Domain reverts to blank in Settings → Pages | A push overwrote the `CNAME` file | The `CNAME` file in the repo is the source of truth — keep it committed |
