import asyncio
import base64
import hashlib
import hmac
import logging
import time

import httpx

logger = logging.getLogger(__name__)
BITGET_API_BASE = "https://api.bitget.com"


def _sign(ts: str, method: str, path_and_query: str, body: str, secret: str) -> str:
    prehash = ts + method.upper() + path_and_query + (body or "")
    return base64.b64encode(
        hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()
    ).decode()


def _auth_headers(method: str, path_and_query: str, body: str,
                  api_key: str, secret: str, passphrase: str) -> dict:
    ts = str(int(time.time() * 1000))
    return {
        "ACCESS-KEY": api_key,
        "ACCESS-SIGN": _sign(ts, method, path_and_query, body, secret),
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
        "locale": "en-US",
    }


async def _get_all_pages(client: httpx.AsyncClient, path: str, base_params: dict,
                         api_key: str, secret: str, passphrase: str,
                         max_pages: int = 20) -> list[dict]:
    rows: list[dict] = []
    cursor: str | None = None
    for _ in range(max_pages):
        params = {**base_params, "limit": "100"}
        if cursor:
            params["idLessThan"] = cursor
        qs = "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        hdrs = _auth_headers("GET", path + qs, "", api_key, secret, passphrase)
        try:
            r = await client.get(BITGET_API_BASE + path + qs, headers=hdrs)
            body = r.json()
        except Exception as exc:
            logger.warning("Bitget API GET %s: %s", path, exc)
            break
        code = str(body.get("code", ""))
        if code not in ("00000", "0", "200"):
            logger.warning("Bitget API %s code=%s msg=%s", path, code, body.get("msg"))
            break
        page: list = []
        d = body.get("data") or {}
        if isinstance(d, dict):
            page = d.get("rows") or d.get("list") or []
        elif isinstance(d, list):
            page = d
        if not page:
            break
        rows.extend(page)
        if len(page) < 100:
            break
        last = page[-1]
        cursor = str(last.get("orderId") or last.get("id") or "")
        if not cursor:
            break
    return rows


_SUCCESS_STATUSES = {
    "success", "successful", "Success", "Successful", "SUCCESS", "SUCCESSFUL",
    "complete", "Complete", "COMPLETE",
}


async def fetch_net_investment(api_key: str, secret: str, passphrase: str,
                                coin: str = "USDT") -> dict:
    """Return net investment = total deposits - total withdrawals for the given coin."""
    async with httpx.AsyncClient(timeout=20) as client:
        deposits, withdrawals = await asyncio.gather(
            _get_all_pages(client, "/api/v2/spot/wallet/deposit-records",
                           {"coin": coin}, api_key, secret, passphrase),
            _get_all_pages(client, "/api/v2/spot/wallet/withdrawal-records",
                           {"coin": coin}, api_key, secret, passphrase),
        )

    dep_total = sum(
        float(r.get("size") or 0) for r in deposits
        if r.get("status") in _SUCCESS_STATUSES
    )
    wdw_total = sum(
        float(r.get("size") or 0) for r in withdrawals
        if r.get("status") in _SUCCESS_STATUSES
    )

    return {
        "deposits": round(dep_total, 2),
        "withdrawals": round(wdw_total, 2),
        "net": round(dep_total - wdw_total, 2),
        "deposit_count": len(deposits),
        "withdrawal_count": len(withdrawals),
        "coin": coin,
    }
