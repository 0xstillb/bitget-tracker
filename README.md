# Bitget Copy Trading Tracker

A self-hosted portfolio tracker for Bitget USDT-Futures copy trading — FastAPI backend, web dashboard, and an iPhone Scriptable home screen widget.

---

## Step 1 — Create Bitget API keys

1. Log in to Bitget → click your avatar → **API Management**
2. Click **Create API**
3. Set permissions to **Read Only**
4. Enable **Futures** read access (USDT-Futures)
5. For IP whitelist, enter `0.0.0.0/0` (any IP) — you can tighten this to your Render IP later
6. Copy the **API Key**, **Secret**, and **Passphrase** — you'll need all three

---

## Step 2 — Deploy to Render

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → **New** → **Web Service** → **Connect GitHub repo**
3. Render will detect `render.yaml` automatically
4. In the Render dashboard, add the three environment variables under **Environment**:
   - `BITGET_API_KEY`
   - `BITGET_API_SECRET`
   - `BITGET_API_PASSPHRASE`
5. Click **Deploy** — wait ~2 minutes for the first build
6. Your URL will be something like `https://bitget-tracker.onrender.com`
7. Visit that URL — you should see the dashboard loading data

---

## Step 3 — Set up iPhone widget

1. Install **Scriptable** from the App Store (free)
2. Open Scriptable → tap **+** → paste the entire contents of `scriptable/widget.js`
3. Name the script (e.g. "Bitget")
4. Tap **Run** — when prompted, enter your Render URL (e.g. `https://bitget-tracker.onrender.com`) and tap **Save**
5. Long-press your home screen → tap **+** → search **Scriptable**
6. Choose the **Medium** widget size → tap **Add Widget**
7. Long-press the widget → **Edit Widget** → set Script to your "Bitget" script
8. Done — widget updates automatically

---

## Troubleshooting

- **Widget shows "⚠ stale"**: The Render free tier spins down after inactivity. Wait 30 seconds for a cold start, then pull to refresh the dashboard — the widget will catch up on its next refresh.
- **PnL shows $0.00**: Confirm your API key has Futures read permission enabled. Copy-trading fills may take a few minutes to appear.
- **CORS error in browser**: Already handled by the server middleware — if you see this, make sure you're hitting your Render URL and not localhost.
- **Widget shows setup screen**: Open Scriptable, run the script manually, and enter your server URL when prompted.
