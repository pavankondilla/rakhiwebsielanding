# Backend setup — Google Sheet + Apps Script

The landing page posts every signup to a Google Apps Script web app, which
writes it into a Google Sheet.

Current deployment:

```
https://script.google.com/macros/s/AKfycbyRTPdD8jOUiph-wzGks1jj9IRVkv81Bnimb2uBklHJphpCx_1rgZsHyAlixuM57cgeYQ/exec
```

---

## ⚠️ Do this first: run `setup()` once

Opening the `/exec` URL right now returns:

```json
{"ok":true,"service":"airakhi-first-access","ready":false,"entries":0}
```

`"ready": false` means **the "First Access" tab does not exist yet**. Signups
would still be created on the first write, but run `setup()` once so the tab,
the 24 headers, the column widths, the frozen header row and the Status
dropdown are all created up front:

1. Open the spreadsheet → **Extensions → Apps Script**.
2. In the function dropdown at the top, choose **`setup`**.
3. Click **Run**. Authorise when Google asks (it is your own script — choose
   your account → *Advanced* → *Go to … (unsafe)* → *Allow*).
4. Reload the `/exec` URL. It must now say:

```json
{"ok":true,"ready":true,"sheet":"First Access","entries":0}
```

Also rename the spreadsheet from *Untitled spreadsheet* to something like
**AiRakhi — First Access** so it is findable in Drive.

---

## Full deployment, from scratch

1. Create a Google Sheet.
2. **Extensions → Apps Script.**
3. Delete the placeholder `Code.gs` contents and paste all of
   [`Code.gs`](./Code.gs). Save.
4. Run **`setup`** once and authorise (see above).
5. **Deploy → New deployment → type: Web app**
   - *Description:* `AiRakhi first access`
   - *Execute as:* **Me**
   - *Who has access:* **Anyone**  ← must be *Anyone*, not "Anyone with a
     Google account", or the landing page gets an HTML login page instead of JSON.
6. Copy the `/exec` URL and paste it into `ENDPOINT` in `index.html`.

### After editing `Code.gs`

Apps Script serves the **deployed** version, not the saved one. Use
**Deploy → Manage deployments → ✏️ Edit → Version: New version → Deploy**
to keep the same `/exec` URL. Creating a *new deployment* instead gives you a
new URL and you would have to update `index.html`.

---

## Options in `CONFIG` (top of `Code.gs`)

| Key | Default | What it does |
|---|---|---|
| `SPREADSHEET_ID` | `''` | Leave empty when the script is bound to the sheet. |
| `SHEET_NAME` | `'First Access'` | Tab that holds the leads. |
| `DEDUPE_BY_EMAIL` | `true` | A repeat email updates the row and bumps `Submissions` instead of adding a duplicate. |
| `NOTIFY_EMAIL` | `''` | Set an address to get an email on every new signup. |
| `SHARED_SECRET` | `''` | Leave empty for a public page — a token would be visible in the page source anyway. |
| `ALLOW_GET_SUBMIT` | `true` | **Keep `true`.** The page's JSONP fallback needs it. |
| `TIME_ZONE` | `'Asia/Kolkata'` | Used for entry IDs and the sheet timezone. |

## Health check

Open the `/exec` URL in a browser at any time:

```json
{"ok":true,"service":"airakhi-first-access","version":"1.0.0","ready":true,"entries":42}
```

## Test a submission without the site

```bash
curl -L -X POST "https://script.google.com/macros/s/AKfycbyRTPdD8jOUiph-wzGks1jj9IRVkv81Bnimb2uBklHJphpCx_1rgZsHyAlixuM57cgeYQ/exec" \
  -H "Content-Type: text/plain;charset=utf-8" \
  -d '{"name":"Test User","email":"test@example.com","phone":"+919876543210","segment":"Sibling abroad","message":"hello"}'
```

Expected: `{"ok":true,"status":"created","entryId":"BA-…","row":2,…}`.
Delete that row from the sheet afterwards.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| HTML login page instead of JSON | Deployment access is not *Anyone* | Redeploy with **Who has access: Anyone** |
| `ready: false` | `setup()` never ran | Run `setup()` from the editor |
| Old behaviour after editing `Code.gs` | Deployment not re-versioned | Manage deployments → Edit → New version |
| `{"ok":false,"error":{"code":"BUSY"}}` | Two writes at once | Automatic — the page retries are safe, dedupe prevents doubles |
| Nothing appears, no error | Wrong spreadsheet | Check the **Error Log** tab in the sheet |

Server-side failures are appended to an **Error Log** tab in the same
spreadsheet — timestamp, where, message, stack, payload.
