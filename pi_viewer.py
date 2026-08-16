"""A lightweight, GET-only Pi Viewer for the private Core snapshot API."""

import ipaddress
import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import parse_qs, urlsplit


_SECRET_MARKERS = (
    "api_key", "authorization", "cookie", "credential", "local_storage",
    "passphrase", "password", "secret", "token",
)

# The viewer now serves the real dashboard (static/index.html + journal.html)
# and proxies every other /api/* and /internal/* route to Core.
STATIC_DIR = Path(os.environ.get("PI_VIEWER_STATIC_DIR", "static"))


DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#08111f"><title>Bitget Pi Viewer</title>
<link rel="manifest" href="/manifest.webmanifest"><link rel="icon" href="/assets/app-icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/assets/pi-viewer.css"></head><body>
<header class="topbar"><div><p class="eyebrow">READ-ONLY · PI VIEWER</p><h1>Bitget Tracker</h1></div>
<div class="top-actions"><span id="connection" class="badge" role="status">LOADING</span><button id="install" class="ghost" hidden>Install</button><button id="refresh" class="primary">Refresh</button></div></header>
<main><section class="hero"><div class="hero-heading"><p class="label">TOTAL EQUITY</p><span id="auth-state" class="auth-state">AUTH UNKNOWN</span></div><strong id="equity">—</strong><p id="updated">Waiting for snapshot</p></section>
<section class="metrics" aria-label="Portfolio metrics"><article class="metric"><p>Today P&amp;L</p><strong id="today">—</strong></article><article class="metric"><p>Open P&amp;L</p><strong id="open">—</strong></article><article class="metric"><p>All-time P&amp;L</p><strong id="alltime">—</strong></article><article class="metric"><p>Open positions</p><strong id="position-count">—</strong></article></section>
<section class="panel"><div class="panel-heading"><h2>Open positions</h2><span id="position-status"></span></div><div id="positions" class="rows"><p class="empty">No data yet</p></div></section>
<section class="panel"><div class="panel-heading"><h2>Tracked portfolios</h2><span id="trader-count"></span></div><div id="traders" class="rows"><p class="empty">No data yet</p></div></section></main>
<footer>Local read-only cache · <span id="refresh-note">refreshes every 30 seconds</span></footer><script src="/assets/pi-viewer.js"></script></body></html>"""

DASHBOARD_CSS = """:root{color-scheme:dark;--bg:#08111f;--panel:#111d30;--line:#243552;--text:#f4f7fb;--muted:#9db0cd;--green:#53e0a1;--red:#ff7787;--amber:#ffc658}*{box-sizing:border-box}body{margin:0;min-width:300px;background:radial-gradient(circle at 80% -10%,#1b3d66,transparent 38%),var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.topbar,main,footer{width:min(920px,calc(100% - 32px));margin:auto}.topbar{min-height:88px;display:flex;align-items:center;justify-content:space-between;gap:16px}.eyebrow,.label{margin:0;color:var(--muted);font-size:11px;letter-spacing:.12em;font-weight:700}.topbar h1{margin:2px 0 0;font-size:22px}.top-actions{display:flex;align-items:center;gap:8px}.badge,.auth-state{border:1px solid var(--line);border-radius:999px;padding:6px 9px;color:var(--amber);font-size:11px;font-weight:700}.badge.ok,.auth-state.ok{color:var(--green)}.badge.stale,.auth-state.pending{color:var(--amber)}.badge.offline,.auth-state.failed{color:var(--red)}button{min-height:38px;border-radius:9px;padding:0 13px;border:1px solid transparent;color:var(--text);font:inherit;font-weight:650;cursor:pointer}.primary{background:#2b73da}.ghost{background:transparent;border-color:var(--line)}main{display:grid;gap:14px}.hero,.metric,.panel{border:1px solid var(--line);background:color-mix(in srgb,var(--panel) 92%,transparent);box-shadow:0 10px 28px #0003}.hero{border-radius:16px;padding:22px}.hero-heading{display:flex;align-items:center;justify-content:space-between;gap:10px}.hero strong{display:block;margin:5px 0 1px;font-size:clamp(32px,8vw,52px);letter-spacing:-.045em}.hero p:last-child{margin:0;color:var(--muted)}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.metric{min-height:102px;border-radius:13px;padding:14px}.metric p{margin:0;color:var(--muted);font-size:12px}.metric strong{display:block;margin-top:9px;font-size:20px}.positive{color:var(--green)}.negative{color:var(--red)}.panel{border-radius:14px;overflow:hidden}.panel-heading{display:flex;justify-content:space-between;align-items:center;padding:15px 16px;border-bottom:1px solid var(--line)}.panel h2{margin:0;font-size:15px}.panel-heading span{color:var(--muted);font-size:12px}.rows{display:grid}.row{display:grid;grid-template-columns:1fr auto;gap:12px;padding:13px 16px;border-bottom:1px solid var(--line)}.row:last-child{border:0}.row strong{display:block;font-size:14px}.row small{color:var(--muted)}.row .value{text-align:right}.empty{margin:0;padding:18px 16px;color:var(--muted)}footer{padding:22px 0 calc(22px + env(safe-area-inset-bottom));color:var(--muted);font-size:12px}@media(max-width:620px){.topbar{padding-top:max(12px,env(safe-area-inset-top));min-height:78px}.topbar h1{font-size:19px}.top-actions{gap:6px}.top-actions .ghost{display:none}.badge{padding:5px 7px}.primary{padding:0 10px}.metrics{grid-template-columns:repeat(2,1fr)}.metric{min-height:88px}.metric strong{font-size:18px}.hero{padding:18px}.hero-heading{align-items:flex-start;flex-direction:column}.row{padding:12px}.topbar,main,footer{width:min(100% - 20px,920px)}}"""

DASHBOARD_JS = """const money=new Intl.NumberFormat(undefined,{style:"currency",currency:"USD",maximumFractionDigits:2});
const number=new Intl.NumberFormat(undefined,{maximumFractionDigits:0});
const byId=id=>document.getElementById(id);
const value=(item,key,fallback=0)=>Number((item&&item[key])??fallback)||0;
const setText=(id,text)=>{byId(id).textContent=text};
const signed=value=>`${value>0?"+":""}${money.format(value)}`;
function setPnl(id,amount){const node=byId(id);node.textContent=signed(amount);node.classList.toggle("positive",amount>0);node.classList.toggle("negative",amount<0)}
function row(title,subtitle,amount){const node=document.createElement("div");node.className="row";const left=document.createElement("div");const heading=document.createElement("strong");heading.textContent=title;const detail=document.createElement("small");detail.textContent=subtitle;left.append(heading,detail);const right=document.createElement("strong");right.className="value";right.textContent=signed(amount);right.classList.toggle("positive",amount>0);right.classList.toggle("negative",amount<0);node.append(left,right);return node}
function renderRows(id,items,makeRow){const container=byId(id);container.replaceChildren();if(!items.length){const empty=document.createElement("p");empty.className="empty";empty.textContent="No active data";container.append(empty);return}items.slice(0,8).forEach(item=>container.append(makeRow(item)))}
function render(snapshot){const data=snapshot.data||{};const summary=data.summary||{};setText("equity",money.format(value(summary,"total_balance")+value(data.earn,"total")+value(data.elite,"bal")));setPnl("today",value(summary,"daily_pnl"));setPnl("open",value(summary,"open_positions_pnl"));setPnl("alltime",value(summary,"all_time_pnl"));setText("position-count",number.format(value(summary,"open_positions")));setText("updated",`Updated ${summary.pushed_at||snapshot.updated_at||"—"}`);const positions=Array.isArray(data.positions)?data.positions:[];const traders=Array.isArray(data.traders)?data.traders.filter(item=>item&&item.has_data!==false):[];setText("position-status",`${positions.length} active`);setText("trader-count",`${traders.length} tracked`);renderRows("positions",positions,item=>row(`${item.s||"Unknown"} · ${item.d||"—"}`,item.src||"Position",value(item,"u")));renderRows("traders",traders,item=>row(item.name||"Portfolio",`${number.format(value(item,"open_position_count"))} open`,value(item,"daily_pnl")))}
function renderAuth(status){const state=status.login_state||status.session_state||"unknown";const labels={approval_required:"APP APPROVAL REQUIRED",otp_required:"OTP REQUIRED",captcha_required:"CAPTCHA REQUIRED",success:"AUTHENTICATED",failed:"LOGIN FAILED",running:"LOGIN RUNNING",disabled:"AUTO LOGIN OFF",unknown:"AUTH UNKNOWN"};const node=byId("auth-state");node.textContent=labels[state]||state.toUpperCase();node.className=`auth-state ${state.includes("required")||state==="running"?"pending":state==="success"?"ok":state==="failed"?"failed":""}`}
function setConnection(state,label){const node=byId("connection");node.className=`badge ${state}`;node.textContent=label}
async function refresh(){setConnection("stale","REFRESHING");try{const [response,authResponse]=await Promise.all([fetch("/api/v1/summary",{cache:"no-store",headers:{Accept:"application/json"}}),fetch("/api/v1/auth",{cache:"no-store",headers:{Accept:"application/json"}})]);if(!response.ok)throw new Error("snapshot unavailable");render(await response.json());if(authResponse.ok)renderAuth(await authResponse.json());setConnection("ok","LIVE")}catch(_error){setConnection("offline","OFFLINE");setText("updated","Viewer is waiting for a cached snapshot")}}
let deferredInstall;window.addEventListener("beforeinstallprompt",event=>{event.preventDefault();deferredInstall=event;byId("install").hidden=false});byId("install").addEventListener("click",async()=>{if(!deferredInstall)return;deferredInstall.prompt();await deferredInstall.userChoice;deferredInstall=undefined;byId("install").hidden=true});byId("refresh").addEventListener("click",refresh);if("serviceWorker" in navigator)navigator.serviceWorker.register("/service-worker.js").catch(()=>{});refresh();window.setInterval(refresh,30000);"""

PWA_MANIFEST = json.dumps({
    "name": "Bitget Pi Viewer", "short_name": "Bitget", "start_url": "/", "scope": "/",
    "display": "standalone", "background_color": "#08111f", "theme_color": "#08111f",
    "icons": [{"src": "/assets/app-icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}],
}, separators=(",", ":"))

SERVICE_WORKER = """const CACHE="bitget-pi-viewer-v1";const ASSETS=["/","/assets/pi-viewer.css","/assets/pi-viewer.js","/assets/app-icon.svg","/manifest.webmanifest"];self.addEventListener("install",event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS))));self.addEventListener("activate",event=>event.waitUntil(self.clients.claim()));self.addEventListener("fetch",event=>{const url=new URL(event.request.url);if(url.origin!==self.location.origin||!ASSETS.includes(url.pathname))return;event.respondWith(caches.match(event.request).then(cached=>cached||fetch(event.request)));});"""

APP_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="112" fill="#08111f"/><path d="M112 156h288v78H112zm0 122h180v78H112z" fill="#2b73da"/><path d="M326 278h74v78h-74z" fill="#53e0a1"/></svg>"""


class _NoRedirectHandler(HTTPRedirectHandler):
    """Never forward the internal token to a redirected destination."""

    def redirect_request(self, _request, _file_pointer, _code, _message, _headers, _new_url):
        return None


def _validate_core_snapshot_url(url: str) -> str:
    """Allow the internal token only to the canonical private Core endpoint."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError as error:
        raise ValueError("CORE_SNAPSHOT_URL must be the private Core snapshot endpoint") from error
    tailscale = isinstance(address, ipaddress.IPv4Address) and address in ipaddress.ip_network("100.64.0.0/10")
    if (
        parsed.scheme != "http"
        or not (address.is_loopback or tailscale)
        or port != 10000
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/internal/v1/snapshot"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("CORE_SNAPSHOT_URL must be the private Core snapshot endpoint")
    return url


def _safe_error_message(error: BaseException) -> str:
    """Keep diagnostics bounded and redact messages that may contain secrets."""
    message = str(error)
    if any(marker in message.lower() for marker in _SECRET_MARKERS):
        return f"{type(error).__name__}: details redacted"
    return message[:256]


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if not any(marker in str(key).lower() for marker in _SECRET_MARKERS)
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _normalize_snapshot(snapshot: Any) -> dict | None:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("data"), dict):
        return None
    if not isinstance(snapshot.get("version"), int) or not isinstance(snapshot.get("updated_at"), str):
        return None
    return {
        "version": snapshot["version"],
        "updated_at": snapshot["updated_at"],
        "data": _sanitize(snapshot["data"]),
    }


class ViewerCache:
    """Secret-free local cache, updated atomically to preserve last-good data."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict | None:
        try:
            return _normalize_snapshot(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, snapshot: dict) -> bool:
        normalized = _normalize_snapshot(snapshot)
        if normalized is None:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
            ) as temporary:
                temporary.write(json.dumps(normalized, separators=(",", ":"), ensure_ascii=False))
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            os.replace(temporary_name, self.path)
            return True
        finally:
            if temporary_name:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    pass


class CoreSnapshotClient:
    """Fetch only the Core's read-only snapshot using the Pi's internal token."""

    def __init__(self, url: str, token: str, timeout: float = 5.0):
        self.url = _validate_core_snapshot_url(url)
        self.token = token
        self.timeout = timeout

    def fetch(self) -> dict:
        if not self.url or not self.token:
            raise RuntimeError("Core snapshot URL or internal token is not configured")
        request = Request(self.url, headers={"X-Internal-Token": self.token, "Accept": "application/json"})
        with build_opener(_NoRedirectHandler).open(request, timeout=self.timeout) as response:
            snapshot = json.loads(response.read().decode("utf-8"))
        normalized = _normalize_snapshot(snapshot)
        if normalized is None:
            raise ValueError("Core returned an invalid snapshot")
        return normalized

    def fetch_status(self) -> dict:
        if not self.url or not self.token:
            raise RuntimeError("Core status URL or internal token is not configured")
        status_url = self.url.rsplit("/internal/v1/snapshot", 1)[0] + "/internal/v1/status"
        request = Request(status_url, headers={"X-Internal-Token": self.token, "Accept": "application/json"})
        with build_opener(_NoRedirectHandler).open(request, timeout=self.timeout) as response:
            status = json.loads(response.read().decode("utf-8"))
        if not isinstance(status, dict):
            raise ValueError("Core returned an invalid status")
        return _sanitize(status)

    def proxy(self, method: str, path: str, body: bytes = b"",
              content_type: str = "application/json") -> tuple[int, str]:
        """Forward a dashboard API call to Core so the viewer page matches Core's.

        /internal/* gets the Pi's internal token (never exposed to the
        browser); /api/* passes through unchanged so Core's own write-token
        enforcement still applies.
        """
        if not self.url:
            return 503, json.dumps({"detail": "Core URL is not configured"})
        base = self.url.rsplit("/internal/v1/snapshot", 1)[0]
        headers = {"Accept": "application/json"}
        if path.startswith("/internal/"):
            headers["X-Internal-Token"] = self.token
        if body:
            headers["Content-Type"] = content_type
        request = Request(base + path, data=body or None, headers=headers, method=method)
        try:
            with build_opener(_NoRedirectHandler).open(request, timeout=self.timeout) as response:
                return response.status, response.read().decode("utf-8", errors="replace")
        except HTTPError as error:
            return error.code, error.read().decode("utf-8", errors="replace")
        except Exception:
            return 502, json.dumps({"detail": "Core proxy unavailable"})


class PiViewer:
    """Refresh Core data with bounded exponential backoff while serving cache."""

    def __init__(self, client: CoreSnapshotClient, cache: ViewerCache,
                 clock=time.monotonic, refresh_interval: float = 30.0):
        self.client = client
        self.cache = cache
        self.clock = clock
        self.refresh_interval = refresh_interval
        self.snapshot = cache.load()
        self.failures = 0
        self.next_attempt = 0.0
        self.last_error: str | None = None
        self.last_success_at: str | None = None

    def refresh_once(self) -> bool:
        now = self.clock()
        if now < self.next_attempt:
            return False
        try:
            snapshot = self.client.fetch()
            normalized = _normalize_snapshot(snapshot)
            if normalized is None or not self.cache.save(normalized):
                raise ValueError("Core returned an invalid snapshot")
            self.snapshot = normalized
            self.failures = 0
            self.next_attempt = now + self.refresh_interval
            self.last_error = None
            self.last_success_at = datetime.now(timezone.utc).isoformat()
            return True
        except Exception as error:
            self.failures += 1
            backoff = min(300, 2 ** (self.failures - 1))
            self.next_attempt = now + backoff
            self.last_error = _safe_error_message(error)
            return False

    def summary(self) -> dict | None:
        self.refresh_once()
        return self.snapshot

    def health(self) -> dict:
        return {
            "ok": self.snapshot is not None,
            "cached": self.snapshot is not None,
            "stale": self.snapshot is not None and self.last_error is not None,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
            "backoff_seconds": min(300, 2 ** (self.failures - 1)) if self.failures else 0,
        }

    def auth_status(self) -> dict:
        try:
            fetch_status = getattr(self.client, "fetch_status")
            return fetch_status()
        except Exception as error:
            return {"login_state": "unavailable", "error": _safe_error_message(error)}

    def esp32_home(self) -> dict | None:
        """Project cached Core snapshot into the established compact ESP32 schema."""
        snapshot = self.summary()
        if snapshot is None:
            return None
        data = snapshot["data"]
        summary = data.get("summary") or {}
        earn = data.get("earn") or {}
        elite = data.get("elite") or {"on": False, "bal": 0.0}
        positions = list(data.get("positions") or [])[:3]
        traders = []
        for trader in data.get("traders") or []:
            if not isinstance(trader, dict) or not trader.get("has_data", True):
                continue
            traders.append({
                "n": str(trader.get("name") or "")[:16],
                "bal": round(trader.get("balance") or 0.0, 2),
                "day": round(trader.get("daily_pnl") or 0.0, 2),
                "all": round(trader.get("all_time_pnl") or 0.0, 2),
                "open": round(trader.get("open_positions_pnl") or 0.0, 2),
                "pos": int(trader.get("open_position_count") or 0),
            })
        return {
            "ok": True,
            "stale": self.last_error is not None,
            "upd": summary.get("pushed_at") or snapshot["updated_at"],
            "bal": round((summary.get("total_balance") or 0.0) + (earn.get("total") or 0.0) + (elite.get("bal") or 0.0), 2),
            "inv": round(summary.get("total_investment") or 0.0, 2),
            "day": round(summary.get("daily_pnl") or 0.0, 2),
            "open": round(summary.get("open_positions_pnl") or 0.0, 2),
            "npos": int(summary.get("open_positions") or 0),
            "ntoday": int(summary.get("trades_today") or 0),
            "all": round(summary.get("all_time_pnl") or 0.0, 2),
            "earn": round(earn.get("total") or 0.0, 2),
            "eday": round(earn.get("interest_24h") or 0.0, 2),
            "traders": traders,
            "elite": elite,
            "positions": positions,
        }

    def esp32_positions(self) -> list[dict]:
        snapshot = self.summary()
        return list((snapshot or {"data": {}})["data"].get("positions") or [])

    def esp32_history(self, limit: int) -> list[dict]:
        snapshot = self.summary()
        history = list((snapshot or {"data": {}})["data"].get("history") or [])
        return history[:max(1, min(limit, 100))]


class ViewerApplication:
    """Serve the real dashboard and proxy the rest of Core's API surface."""

    SECURITY_HEADERS = {
        "Cache-Control": "no-store, max-age=0",
        "Content-Security-Policy": (
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'none'; object-src 'none'; script-src 'self'; "
            "style-src 'self'; connect-src 'self'"
        ),
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }

    # Routes answered from the viewer's local cache/assets keep the strict
    # headers; the dashboard page itself needs inline scripts and is served
    # exactly as Core serves it.
    VIEWER_LOCAL_ROUTES = frozenset({
        "/api/v1/summary", "/api/v1/health", "/api/v1/auth",
        "/api/esp32", "/api/esp32/positions", "/api/esp32/history",
    })

    def __init__(self, viewer: PiViewer, static_dir: Path | str | None = None):
        self.viewer = viewer
        self.static_dir = Path(static_dir) if static_dir is not None else STATIC_DIR

    def response(self, method: str, path: str, body: bytes = b"") -> tuple[int, dict[str, str], str]:
        status, headers, text = self._route_response(method, path, body)
        route = urlsplit(path).path
        # Only the dashboard pages are exempt: they need inline scripts, so the
        # strict CSP would break them. Everything else keeps the header set.
        if route not in ("/", "/index.html", "/journal.html"):
            headers = {**headers, **self.SECURITY_HEADERS}
        return status, headers, text

    def _dashboard_page(self, name: str) -> tuple[int, dict[str, str], str]:
        page = self.static_dir / name
        try:
            return 200, {
                "Content-Type": "text/html; charset=utf-8",
                "Cache-Control": "no-store, max-age=0",
            }, page.read_text(encoding="utf-8")
        except OSError:
            return 503, {"Content-Type": "application/json"}, json.dumps(
                {"detail": f"static/{name} is not available on this deployment"})

    def _proxy_request(self, method: str, path: str, body: bytes) -> tuple[int, dict[str, str], str]:
        proxy = getattr(self.viewer.client, "proxy", None)
        if proxy is None:
            return 501, {"Content-Type": "application/json"}, json.dumps(
                {"detail": "Core proxy is not configured"})
        status, text = proxy(method, path, body)
        return status, {"Content-Type": "application/json"}, text

    def _route_response(self, method: str, path: str, body: bytes = b"") -> tuple[int, dict[str, str], str]:
        parsed = urlsplit(path)
        route = parsed.path
        if route in ("/", "/index.html"):
            return self._dashboard_page("index.html")
        if route == "/journal.html":
            return self._dashboard_page("journal.html")
        if (route.startswith(("/api/", "/internal/"))
                and route not in self.VIEWER_LOCAL_ROUTES):
            proxy_path = route + (f"?{parsed.query}" if parsed.query else "")
            return self._proxy_request(method, proxy_path, body)
        if method != "GET":
            return 405, {"Allow": "GET", "Content-Type": "application/json"}, json.dumps({"detail": "GET only"})
        if route == "/assets/pi-viewer.css":
            return 200, {"Content-Type": "text/css; charset=utf-8"}, DASHBOARD_CSS
        if route == "/assets/pi-viewer.js":
            return 200, {"Content-Type": "application/javascript; charset=utf-8"}, DASHBOARD_JS
        if route == "/assets/app-icon.svg":
            return 200, {"Content-Type": "image/svg+xml"}, APP_ICON_SVG
        if route == "/manifest.webmanifest":
            return 200, {"Content-Type": "application/manifest+json; charset=utf-8"}, PWA_MANIFEST
        if route == "/service-worker.js":
            return 200, {"Content-Type": "application/javascript; charset=utf-8"}, SERVICE_WORKER
        if route == "/api/v1/summary":
            snapshot = self.viewer.summary()
            if snapshot is None:
                return 503, {"Content-Type": "application/json"}, json.dumps({"detail": "no cached snapshot"})
            return 200, {"Content-Type": "application/json"}, json.dumps(snapshot)
        if route == "/api/v1/health":
            return 200, {"Content-Type": "application/json"}, json.dumps(self.viewer.health())
        if route == "/api/v1/auth":
            return 200, {"Content-Type": "application/json"}, json.dumps(self.viewer.auth_status())
        if route == "/api/esp32":
            payload = self.viewer.esp32_home()
            if payload is None:
                return 503, {"Content-Type": "application/json"}, json.dumps({"detail": "no cached snapshot"})
            return 200, {"Content-Type": "application/json"}, json.dumps(payload)
        if route == "/api/esp32/positions":
            return 200, {"Content-Type": "application/json"}, json.dumps({"positions": self.viewer.esp32_positions()})
        if route == "/api/esp32/history":
            raw_limit = parse_qs(parsed.query).get("n", ["30"])[0]
            try:
                limit = int(raw_limit)
            except ValueError:
                limit = 30
            return 200, {"Content-Type": "application/json"}, json.dumps({"trades": self.viewer.esp32_history(limit)})
        return 404, {"Content-Type": "application/json"}, json.dumps({"detail": "not found"})


def make_handler(application: ViewerApplication):
    class Handler(BaseHTTPRequestHandler):
        def _respond(self, method: str) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            body = self.rfile.read(length) if length else b""
            status, headers, body_text = application.response(method, self.path, body)
            encoded = body_text.encode("utf-8")
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802
            self._respond("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._respond("POST")

        def do_PUT(self) -> None:  # noqa: N802
            self._respond("PUT")

        def do_PATCH(self) -> None:  # noqa: N802
            self._respond("PATCH")

        def do_DELETE(self) -> None:  # noqa: N802
            self._respond("DELETE")

        def log_message(self, _format: str, *_args) -> None:
            return

    return Handler


def run_from_env() -> None:
    client = CoreSnapshotClient(
        os.environ.get("CORE_SNAPSHOT_URL", ""),
        os.environ.get("INTERNAL_API_TOKEN", ""),
        timeout=float(os.environ.get("CORE_SNAPSHOT_TIMEOUT_SEC", "5")),
    )
    viewer = PiViewer(client, ViewerCache(Path(os.environ.get("PI_VIEWER_CACHE_PATH", "viewer-cache.json"))))
    application = ViewerApplication(viewer)

    def refresh_loop() -> None:
        while True:
            viewer.refresh_once()
            time.sleep(1)

    threading.Thread(target=refresh_loop, daemon=True).start()
    ThreadingHTTPServer((os.environ.get("PI_VIEWER_BIND_HOST", "0.0.0.0"),
                         int(os.environ.get("PI_VIEWER_PORT", "8080"))), make_handler(application)).serve_forever()


if __name__ == "__main__":
    run_from_env()
