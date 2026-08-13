import asyncio

import httpx

import main


def _configure_esp32_state(monkeypatch):
    monkeypatch.setattr(main, "_settings", {"balance": 0.0, "investment": 0.0, "traders": {}})
    monkeypatch.setattr(main, "_traders_list", [{"name": "AlphaTrader", "id": "1", "type": "cfd"}])
    monkeypatch.setattr(main, "_traders_cache", {
        "AlphaTrader": {"summary": {
            "name": "AlphaTrader", "balance": 100.0, "daily_pnl": 2.5,
            "all_time_pnl": 12.0, "open_positions_pnl": 1.0,
            "open_position_count": 2, "has_data": True,
        }, "positions_raw": None, "trades": []},
    })
    monkeypatch.setattr(main, "_earn", {"data": {"total": 3.0, "interest_24h": 0.2}})
    monkeypatch.setattr(main, "_elite", {"data": None})
    monkeypatch.setattr(main, "_mt5", {
        "summary": {
            "total_balance": 100.0, "total_investment": 80.0, "daily_pnl": 2.5,
            "open_positions_pnl": 1.0, "open_positions": 4, "all_time_pnl": 12.0,
            "pushed_at": "14:00",
        },
        "positions_raw": [
            {"symbol": "XAUUSD", "side": "long", "size": "0.1", "openPrice": "2300", "profit": "1.2"},
            {"symbol": "BTCUSDT", "side": "short", "size": "0.2", "openPrice": "60000", "profit": "-2.5"},
            {"symbol": "ETHUSDT", "side": "long", "size": "1", "openPrice": "3000", "profit": "0.4"},
            {"symbol": "SOLUSDT", "side": "long", "size": "3", "openPrice": "150", "profit": "0.1"},
        ],
        "trades": [
            {"time": "2026-08-13 12:00", "close_time_ms": 4, "symbol": "XAUUSD", "side": "long", "pnl": 4.5},
            {"time": "2026-08-13 11:00", "close_time_ms": 3, "symbol": "BTCUSDT", "side": "short", "pnl": -2.0},
        ],
    })


def test_esp32_home_keeps_compact_schema_and_includes_only_three_positions(monkeypatch):
    _configure_esp32_state(monkeypatch)

    async def exercise():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/esp32")

    response = asyncio.run(exercise())
    payload = response.json()

    assert response.status_code == 200
    assert {"ok", "stale", "upd", "bal", "inv", "day", "open", "npos", "ntoday", "all", "earn", "eday", "traders", "elite", "positions"} <= payload.keys()
    assert payload["bal"] == 103.0
    assert payload["positions"] == [
        {"s": "XAUUSD", "d": "L", "sz": 0.1, "e": 2300.0, "u": 1.2, "src": "core"},
        {"s": "BTCUSDT", "d": "S", "sz": 0.2, "e": 60000.0, "u": -2.5, "src": "core"},
        {"s": "ETHUSDT", "d": "L", "sz": 1.0, "e": 3000.0, "u": 0.4, "src": "core"},
    ]


def test_esp32_positions_and_history_keep_compact_backward_compatible_rows(monkeypatch):
    _configure_esp32_state(monkeypatch)

    async def exercise():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            positions = await client.get("/api/esp32/positions")
            history = await client.get("/api/esp32/history?n=1")
        return positions, history

    positions, history = asyncio.run(exercise())

    assert positions.json()["positions"][0] == {"s": "XAUUSD", "d": "L", "sz": 0.1, "e": 2300.0, "u": 1.2, "src": "core"}
    assert history.json() == {"trades": [{"t": "08-13 12:00", "s": "XAUUSD", "d": "L", "p": 4.5}]}


def test_esp32_history_caps_request_size_and_never_returns_raw_fields(monkeypatch):
    _configure_esp32_state(monkeypatch)
    monkeypatch.setitem(main._mt5, "trades", [
        {"time": "2026-08-13 12:00", "close_time_ms": index, "symbol": "XAUUSD", "side": "long", "pnl": 1, "cookie": "never"}
        for index in range(101)
    ])

    async def exercise():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/esp32/history?n=999")

    payload = asyncio.run(exercise()).json()

    assert len(payload["trades"]) == 100
    assert set(payload["trades"][0]) == {"t", "s", "d", "p"}
