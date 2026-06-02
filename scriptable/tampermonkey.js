// ==UserScript==
// @name         Bitget CFD → Tracker
// @namespace    bitget-tracker
// @version      1.0
// @description  Relays Bitget CFD copy trading data to your self-hosted tracker
// @author       you
// @match        https://www.bitget.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      localhost
// @connect      *
// @run-at       document-start
// ==/UserScript==

(function () {
  'use strict';

  // ── CONFIG ─────────────────────────────────────────────────────────────────
  // On first run, you'll be prompted to enter your tracker URL.
  // Local testing: http://localhost:8000
  // After deploying to Render: https://bitget-tracker.onrender.com
  let TRACKER_URL = GM_getValue('tracker_url', '');
  if (!TRACKER_URL) {
    TRACKER_URL = prompt(
      'Bitget Tracker Setup\n\nEnter your tracker URL:\n(local: http://localhost:8000)\n(Render: https://your-app.onrender.com)',
      'http://localhost:8000'
    );
    if (TRACKER_URL) {
      TRACKER_URL = TRACKER_URL.replace(/\/$/, '');
      GM_setValue('tracker_url', TRACKER_URL);
      alert('Saved! URL set to: ' + TRACKER_URL);
    } else {
      console.warn('[Bitget Tracker] No URL set — script disabled.');
      return;
    }
  }

  const MT5_ENDPOINTS = [
    '/v1/trace/mt5/data/tracePosition',
    '/v1/trace/mt5/trace/positionHistory',
  ];

  // ── Push to tracker ────────────────────────────────────────────────────────
  function pushToTracker(kind, data) {
    GM_xmlhttpRequest({
      method: 'POST',
      url: TRACKER_URL + '/api/push/mt5',
      headers: { 'Content-Type': 'application/json' },
      data: JSON.stringify({ kind, data }),
      onerror: (e) => console.warn('[Bitget Tracker] push failed', e),
    });
  }

  // ── Intercept fetch ────────────────────────────────────────────────────────
  const _origFetch = window.fetch;
  window.fetch = function (...args) {
    const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
    const promise = _origFetch.apply(this, args);

    if (url.includes('/v1/trace/mt5/data/tracePosition')) {
      promise.then(r => r.clone().json()).then(data => {
        console.log('[Bitget Tracker] captured positions');
        pushToTracker('positions', data);
      }).catch(() => {});
    } else if (url.includes('/v1/trace/mt5/trace/positionHistory')) {
      promise.then(r => r.clone().json()).then(data => {
        console.log('[Bitget Tracker] captured history');
        pushToTracker('history', data);
      }).catch(() => {});
    } else if (url.includes('/v1/trace/mt5/data/traceBalance')) {
      promise.then(r => r.clone().json()).then(data => {
        console.log('[Bitget Tracker] captured balance');
        pushToTracker('balance', data);
      }).catch(() => {});
    }

    return promise;
  };

  // ── Intercept XMLHttpRequest (fallback) ───────────────────────────────────
  const _origOpen = XMLHttpRequest.prototype.open;
  const _origSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this._trackerUrl = url;
    return _origOpen.call(this, method, url, ...rest);
  };

  XMLHttpRequest.prototype.send = function (...args) {
    const url = this._trackerUrl || '';
    if (MT5_ENDPOINTS.some(ep => url.includes(ep))) {
      this.addEventListener('load', () => {
        try {
          const data = JSON.parse(this.responseText);
          const kind = url.includes('tracePosition') ? 'positions' : 'history';
          console.log('[Bitget Tracker] XHR captured', kind);
          pushToTracker(kind, data);
        } catch (_) {}
      });
    }
    return _origSend.apply(this, args);
  };

  // ── Extract portfolioId from the current page URL ─────────────────────────
  function getPortfolioId() {
    // Matches /my-portfolio/1443199880395776000 or ?portfolioId=...
    const pathMatch = location.pathname.match(/\/(\d{15,})/);
    if (pathMatch) return pathMatch[1];
    const urlParams = new URLSearchParams(location.search);
    return urlParams.get('portfolioId') || GM_getValue('portfolio_id', '');
  }

  // ── Active poll fallback (calls endpoints directly every 60s) ─────────────
  async function activePoll() {
    const portfolioId = getPortfolioId();
    if (portfolioId) GM_setValue('portfolio_id', portfolioId);
    console.log('[Bitget Tracker] polling, portfolioId=', portfolioId);

    // tracePosition — POST
    try {
      const r = await fetch('/v1/trace/mt5/data/tracePosition', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ portfolioId }),
      });
      if (r.ok) { pushToTracker('positions', await r.json()); console.log('[Bitget Tracker] positions ok'); }
    } catch (e) { console.warn('[Bitget Tracker] positions error:', e); }

    // positionHistory — POST with portfolioId
    try {
      const r = await fetch('/v1/trace/mt5/trace/positionHistory', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ portfolioId, pageNo: 1, pageSize: 50 }),
      });
      if (r.ok) { pushToTracker('history', await r.json()); console.log('[Bitget Tracker] history ok'); }
    } catch (e) { console.warn('[Bitget Tracker] history error:', e); }

    // Balance — try several candidate endpoints
    const balancePaths = [
      { method: 'GET',  url: `/v1/trace/mt5/data/traceAccount` },
      { method: 'POST', url: `/v1/trace/mt5/data/traceAccount`, body: { portfolioId } },
      { method: 'GET',  url: `/v1/trace/mt5/account/balance` },
      { method: 'POST', url: `/v1/trace/mt5/trace/portfolioDetail`, body: { portfolioId } },
      { method: 'GET',  url: `/v1/trace/mt5/data/portfolioDetail?portfolioId=${portfolioId}` },
    ];
    for (const { method, url, body } of balancePaths) {
      try {
        const opts = { method, credentials: 'include', headers: { 'Content-Type': 'application/json' } };
        if (body) opts.body = JSON.stringify(body);
        const r = await fetch(url, opts);
        if (r.ok) {
          const data = await r.json();
          if (data.code === '200' || data.status !== 404) {
            pushToTracker('balance', data);
            console.log('[Bitget Tracker] balance ok from', url, data);
            break;
          }
        }
      } catch (_) {}
    }
  }

  // Start polling after page load
  window.addEventListener('load', () => {
    activePoll();
    setInterval(activePoll, 60_000);
  });

  console.log('[Bitget Tracker] userscript loaded — pushing to', TRACKER_URL);
})();
