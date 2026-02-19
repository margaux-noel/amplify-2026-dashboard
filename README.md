# Amplify 2026 Dashboard

Internal dashboard and partner-facing view for Fora's Amplify 2026 program.

## Pages

- **`index.html`** — Internal dashboard (search, progress tracking, invoices, analytics)
- **`partner.html`** — Partner-facing view, accessed via `?key=PARTNER_KEY`

## Running Locally

You can't just open the HTML files by double-clicking — the browser will block the data files from loading. Instead, run a simple local server:

**Option 1 — Python (easiest, no install needed):**
```bash
cd ~/Desktop/amplify-dashboard
python3 -m http.server 8000
```
Then open your browser and go to:
- `http://localhost:8000` — internal dashboard
- `http://localhost:8000/partner.html?key=PARTNER_KEY` — partner view

Press `Ctrl+C` in the terminal to stop the server.

---

**Option 2 — VS Code:**
Install the [Live Server](https://marketplace.visualstudio.com/items?itemName=ritwickdey.LiveServer) extension, open the folder, and click **Go Live** in the bottom bar.

---

## Updating Data from Streak

Run this whenever you want to pull fresh data:
```bash
cd ~/Desktop/amplify-dashboard
python3 update.py
```

This will regenerate `data.js` and `partners-public.js`, then auto-commit and push to GitHub (which triggers a Vercel redeploy).

Requires the `requests` Python library — if you get an error, run:
```bash
pip3 install requests
```

## Managing Assets (Featured Content Links)

Asset links (Collection, Forum, Newsletter features etc.) are stored in `partner-resources.json`. These are managed via the **Assets tab** in the internal dashboard — avoid editing the file manually.

## Deployment

The dashboard is hosted on **Vercel** and auto-deploys whenever changes are pushed to the `main` branch on GitHub. Live URL is set up via Vercel project settings.
