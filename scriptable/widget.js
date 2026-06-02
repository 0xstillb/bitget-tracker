// SETUP: In Scriptable, run this script once manually first.
// It will prompt you to enter your server URL (e.g. https://bitget-tracker.onrender.com)
// and save it to Keychain automatically.
// After setup, add a Medium-sized Scriptable widget to your home screen.

const KEYCHAIN_KEY = "bitget_tracker_url";
const GREEN  = new Color("#00c47a");
const RED    = new Color("#ff4d4d");
const AMBER  = new Color("#f59e0b");
const WHITE  = new Color("#ffffff");
const MUTED  = new Color("#888888");
const BG     = new Color("#111111");

// ── First-run setup (only when running inside the app, not as a widget) ──
if (!config.runsInWidget) {
  const stored = Keychain.contains(KEYCHAIN_KEY) ? Keychain.get(KEYCHAIN_KEY) : null;
  const prompt = new Alert();
  prompt.title = "Bitget Tracker Setup";
  prompt.message = "Enter your server URL (e.g. https://bitget-tracker.onrender.com)";
  prompt.addTextField("Server URL", stored || "https://");
  prompt.addAction("Save");
  prompt.addCancelAction("Cancel");
  const idx = await prompt.presentAlert();
  if (idx === 0) {
    const url = prompt.textFieldValue(0).replace(/\/$/, "");
    Keychain.set(KEYCHAIN_KEY, url);
    const done = new Alert();
    done.title = "Saved!";
    done.message = `URL saved: ${url}\n\nNow add a Medium Scriptable widget to your home screen.`;
    done.addAction("OK");
    await done.presentAlert();
    Script.complete();
    return;
  } else {
    Script.complete();
    return;
  }
}

// ── Widget mode ──
const widget = new ListWidget();
widget.backgroundColor = BG;
widget.setPadding(12, 14, 12, 14);
widget.url = Keychain.contains(KEYCHAIN_KEY) ? Keychain.get(KEYCHAIN_KEY) : "";

async function fetchData(baseUrl) {
  const req = new Request(`${baseUrl}/api/widget`);
  req.timeoutInterval = 8;
  try {
    const data = await req.loadJSON();
    return { data, stale: data.stale || false };
  } catch (e) {
    // Try to return cached value from Keychain if available
    const cached = Keychain.contains("bitget_widget_cache")
      ? JSON.parse(Keychain.get("bitget_widget_cache"))
      : null;
    return { data: cached, stale: true };
  }
}

function addRow(widget, justify = "left") {
  const stack = widget.addStack();
  stack.layoutHorizontally();
  stack.centerAlignContent();
  if (justify === "space-between") stack.addSpacer();
  return stack;
}

function txt(stack, content, size, color, bold = false) {
  const t = stack.addText(content);
  t.font = bold ? Font.boldSystemFont(size) : Font.systemFont(size);
  t.textColor = color;
  return t;
}

// ── Build widget ──
if (!Keychain.contains(KEYCHAIN_KEY)) {
  // Not configured
  const row = widget.addStack();
  const t = row.addText("⚙ Open Scriptable & run\nthis script to set up.");
  t.font = Font.systemFont(12);
  t.textColor = MUTED;
  t.centerAlignText();
  Script.setWidget(widget);
  Script.complete();
  return;
}

const baseUrl = Keychain.get(KEYCHAIN_KEY);
const { data, stale } = await fetchData(baseUrl);

if (!data) {
  const row = widget.addStack();
  const t = row.addText("⚠ No data\nCheck server");
  t.font = Font.boldSystemFont(14);
  t.textColor = AMBER;
  t.centerAlignText();
  Script.setWidget(widget);
  Script.complete();
  return;
}

// Cache for offline fallback
Keychain.set("bitget_widget_cache", JSON.stringify(data));

const pnl    = data.daily_pnl    ?? 0;
const pnlPct = data.daily_pnl_pct ?? 0;
const bal    = data.total_balance ?? 0;
const nPos   = data.open_positions ?? 0;
const oPnl   = data.open_positions_pnl ?? 0;
const updAt  = data.updated_at ?? "--:--";

const pnlColor = pnl >= 0 ? GREEN : RED;

// ── Row 1: BITGET label | updated_at | stale ──
const row1 = widget.addStack();
row1.layoutHorizontally();
row1.centerAlignContent();
txt(row1, "BITGET", 10, MUTED, false);
row1.addSpacer();
if (stale) txt(row1, "⚠ stale  ", 10, AMBER, false);
txt(row1, updAt, 10, MUTED, false);

widget.addSpacer(6);

// ── Row 2: Daily P&L (big) ──
const pnlStr = (pnl >= 0 ? "+" : "-") + "$" + Math.abs(pnl).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const row2 = widget.addStack();
txt(row2, pnlStr, 28, pnlColor, true);

widget.addSpacer(2);

// ── Row 3: P&L % ──
const pctStr = (pnlPct >= 0 ? "+" : "") + pnlPct.toFixed(2) + "% today";
const row3 = widget.addStack();
txt(row3, pctStr, 14, pnlColor, false);

widget.addSpacer(8);

// ── Row 4: Balance | Positions ──
const row4 = widget.addStack();
row4.layoutHorizontally();

const balStack = row4.addStack();
balStack.layoutVertically();
txt(balStack, "Balance", 10, MUTED, false);
const balStr = "$" + bal.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
txt(balStack, balStr, 13, WHITE, true);

row4.addSpacer();

const posStack = row4.addStack();
posStack.layoutVertically();
txt(posStack, "Positions", 10, MUTED, false);
txt(posStack, String(nPos), 13, WHITE, true);

widget.addSpacer(6);

// ── Row 5: Open PnL (if any open positions) ──
if (nPos > 0) {
  // Separator
  const sepStack = widget.addStack();
  const sep = sepStack.addText("─────────────────");
  sep.font = Font.systemFont(8);
  sep.textColor = new Color("#333333");

  widget.addSpacer(4);

  const oPnlStr = (oPnl >= 0 ? "+" : "-") + "$" + Math.abs(oPnl).toFixed(2);
  const oPnlColor = oPnl >= 0 ? GREEN : RED;
  const row5 = widget.addStack();
  row5.layoutHorizontally();
  txt(row5, "open PnL: ", 11, MUTED, false);
  txt(row5, oPnlStr, 11, oPnlColor, true);
}

Script.setWidget(widget);
Script.complete();
