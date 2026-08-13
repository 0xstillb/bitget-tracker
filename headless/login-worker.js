'use strict';

const fs = require('fs');
const path = require('path');

const PROTOCOL_VERSION = 1;
const REQUEST_KEYS = new Set(['version', 'action', 'request_id', 'challenge']);
const MAX_INPUT_BYTES = 4096;
const COOKIE_PATH = path.resolve(__dirname, 'data', 'cookies.txt');
const AUTH_COOKIE_NAMES = new Set(['bt_newsessionid', 'bt_sessonid', 'bt_uid']);
const LOGIN_URL = 'https://www.bitget.com/login';

function validIdentifier(value) {
  return typeof value === 'string' && value.length > 0 && value.length <= 128 && !/\s/.test(value);
}

function parseRequest(line) {
  const request = JSON.parse(line);
  if (!request || typeof request !== 'object' || Array.isArray(request)) throw new Error('invalid request');
  if (Object.keys(request).some(key => !REQUEST_KEYS.has(key))) throw new Error('unsupported request field');
  if (request.version !== PROTOCOL_VERSION || request.action !== 'start') throw new Error('unsupported request');
  if (!validIdentifier(request.request_id) || !validIdentifier(request.challenge)) throw new Error('invalid request');
  return request;
}

function emit(request, state, code) {
  const event = {
    version: PROTOCOL_VERSION,
    request_id: request.request_id,
    challenge: request.challenge,
    state,
  };
  if (code) event.code = code;
  process.stdout.write(`${JSON.stringify(event)}\n`);
}

function boundedInteger(value, fallback, minimum, maximum) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(maximum, Math.max(minimum, parsed));
}

function readConfig(env) {
  return {
    enabled: String(env.AUTO_LOGIN_ENABLED || '').trim().toLowerCase() === 'true',
    maxAttempts: boundedInteger(env.AUTO_LOGIN_MAX_ATTEMPTS, 2, 1, 3),
    timeoutMs: boundedInteger(env.AUTO_LOGIN_TIMEOUT_SEC, 180, 30, 300) * 1000,
  };
}

function classifyLoginSnapshot(snapshot) {
  if (snapshot.authenticated === true) return { state: 'success' };

  const text = String(snapshot.text || '').toLowerCase();
  const selectors = Array.isArray(snapshot.selectors)
    ? snapshot.selectors.map(selector => String(selector).toLowerCase())
    : [];
  const selectorText = selectors.join(' ');

  if (
    selectorText.includes('captcha') ||
    selectorText.includes('recaptcha') ||
    selectorText.includes('hcaptcha') ||
    /captcha|verify you are human|slide to complete/.test(text)
  ) {
    return { state: 'captcha_required', code: 'captcha_pending' };
  }
  if (
    selectorText.includes('one-time-code') ||
    selectorText.includes('otp') ||
    /one[- ]time (?:password|code)|verification code|sms code|email code|authenticator code/.test(text)
  ) {
    return { state: 'otp_required', code: 'otp_pending' };
  }
  if (/login (?:rejected|denied|failed)|incorrect password|invalid password|account locked|too many attempts/.test(text)) {
    return { state: 'failed', code: 'rejected' };
  }
  if (
    /approve (?:this |the )?login|check your (?:bitget )?app|waiting for approval|confirm (?:this |the )?login|cross-device verification|scan (?:the )?qr/.test(text)
  ) {
    return { state: 'approval_required', code: 'approval_pending' };
  }
  return null;
}

function sleep(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

function readLocalCookies() {
  if (!fs.existsSync(COOKIE_PATH)) return [];
  const content = fs.readFileSync(COOKIE_PATH, 'utf8').trim();
  if (!content) return [];
  try {
    return JSON.parse(Buffer.from(content, 'base64').toString('utf8'));
  } catch {
    return JSON.parse(content);
  }
}

async function loadRememberedDeviceCookies(page) {
  try {
    const cookies = readLocalCookies();
    const rememberedDeviceCookies = Array.isArray(cookies)
      ? cookies.filter(cookie => !AUTH_COOKIE_NAMES.has(cookie.name))
      : [];
    if (rememberedDeviceCookies.length) await page.setCookie(...rememberedDeviceCookies);
  } catch (error) {
    process.stderr.write(`[login-worker] could not load remembered-device cookies: ${error.message}\n`);
  }
}

async function saveCookies(page) {
  const cookies = await page.cookies();
  const dataDirectory = path.dirname(COOKIE_PATH);
  fs.mkdirSync(dataDirectory, { recursive: true });
  fs.writeFileSync(COOKIE_PATH, Buffer.from(JSON.stringify(cookies)).toString('base64'), { mode: 0o600 });
}

async function visibleSelector(page, selectors) {
  return page.evaluate(candidates => {
    for (const selector of candidates) {
      const element = document.querySelector(selector);
      if (!element) continue;
      const rectangle = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      if (rectangle.width > 0 && rectangle.height > 0 && style.visibility !== 'hidden' && style.display !== 'none') {
        return selector;
      }
    }
    return null;
  }, selectors);
}

async function clickVisibleButton(page, labels) {
  return page.evaluate(expectedLabels => {
    const expected = new Set(expectedLabels.map(label => label.toLowerCase()));
    const button = [...document.querySelectorAll('button')].find(candidate => {
      const rectangle = candidate.getBoundingClientRect();
      const label = (candidate.textContent || '').trim().toLowerCase();
      return expected.has(label) && !candidate.disabled && rectangle.width > 0 && rectangle.height > 0;
    });
    if (!button) return false;
    button.click();
    return true;
  }, labels);
}

async function typeCredential(page, selectors, value) {
  const selector = await visibleSelector(page, selectors);
  if (!selector) throw new Error('credential field not found');
  const input = await page.$(selector);
  await input.click({ clickCount: 3 });
  await input.type(value, { delay: 30 });
}

async function submitCredentials(page, phone, password) {
  await page.waitForSelector('input[name="username"], input[type="email"], input[type="tel"]', { timeout: 15000 });
  await typeCredential(page, ['input[name="username"]', 'input[type="email"]', 'input[type="tel"]'], phone);
  if (!await clickVisibleButton(page, ['next', 'continue'])) throw new Error('username submit button not found');

  await page.waitForSelector('input[type="password"]', { timeout: 15000 });
  await typeCredential(page, ['input[type="password"]'], password);
  if (!await clickVisibleButton(page, ['next', 'log in', 'login', 'continue'])) {
    throw new Error('password submit button not found');
  }
}

async function hasAuthenticatedSession(page) {
  const url = page.url().toLowerCase();
  if (!url.includes('bitget.com') || url.includes('/login') || url.includes('/signin')) return false;
  const cookies = await page.cookies('https://www.bitget.com');
  return cookies.some(cookie => AUTH_COOKIE_NAMES.has(cookie.name) && Boolean(cookie.value));
}

async function captureSnapshot(page) {
  const selectors = [
    'input[autocomplete="one-time-code"]',
    'input[name*="otp" i]',
    'input[name*="code" i]',
    'iframe[src*="captcha" i]',
    'iframe[src*="recaptcha" i]',
    'iframe[src*="hcaptcha" i]',
    '[class*="captcha" i]',
  ];
  const visibleSelectors = await page.evaluate(candidates => candidates.filter(selector => {
    const element = document.querySelector(selector);
    if (!element) return false;
    const rectangle = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return rectangle.width > 0 && rectangle.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  }), selectors);
  const text = await page.evaluate(() => document.body ? document.body.innerText : '');
  return {
    url: page.url(),
    text,
    selectors: visibleSelectors,
    authenticated: await hasAuthenticatedSession(page),
  };
}

function loadPuppeteer() {
  const puppeteer = require('puppeteer-extra');
  const StealthPlugin = require('puppeteer-extra-plugin-stealth');
  puppeteer.use(StealthPlugin());
  return puppeteer;
}

async function attemptLogin(phone, password, timeoutMs, onState) {
  let browser;
  try {
    const puppeteer = loadPuppeteer();
    browser = await puppeteer.launch({
      headless: false,
      defaultViewport: null,
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
    });
    const page = await browser.newPage();
    await loadRememberedDeviceCookies(page);
    await page.goto(LOGIN_URL, { waitUntil: 'networkidle2', timeout: 60000 });
    await submitCredentials(page, phone, password);

    const deadline = Date.now() + timeoutMs;
    let lastState;
    while (Date.now() < deadline) {
      const result = classifyLoginSnapshot(await captureSnapshot(page));
      if (result && result.state === 'success') {
        await saveCookies(page);
        return result;
      }
      if (result && result.state === 'failed') return result;
      if (result && result.state !== lastState) {
        lastState = result.state;
        onState(result);
      }
      await sleep(1000);
    }
    return { state: 'timeout', code: 'attempts_exhausted' };
  } catch (error) {
    process.stderr.write(`[login-worker] login attempt failed: ${error.message}\n`);
    return { state: 'failed', code: 'worker_error' };
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
}

async function runRequest(request, env = process.env, dependencies = {}) {
  const emitEvent = dependencies.emit || emit;
  const performAttempt = dependencies.attemptLogin || attemptLogin;

  emitEvent(request, 'started');
  const config = readConfig(env);
  if (!config.enabled) {
    emitEvent(request, 'failed', 'disabled');
    return;
  }

  const phone = env.BITGET_PHONE;
  const password = env.BITGET_PASSWORD;
  if (!phone || !password) {
    emitEvent(request, 'failed', 'credentials_missing');
    return;
  }

  let finalResult = { state: 'failed', code: 'attempts_exhausted' };
  let lastEventKey;
  for (let attempt = 1; attempt <= config.maxAttempts; attempt += 1) {
    finalResult = await performAttempt(phone, password, config.timeoutMs, result => {
      const key = `${result.state}:${result.code || ''}`;
      if (key !== lastEventKey) {
        emitEvent(request, result.state, result.code);
        lastEventKey = key;
      }
    });
    if (finalResult.state === 'success' || finalResult.code === 'rejected') break;
  }

  if (finalResult.state === 'timeout') emitEvent(request, 'timeout', 'attempts_exhausted');
  else if (finalResult.state === 'success') emitEvent(request, 'success');
  else emitEvent(request, 'failed', finalResult.code === 'rejected' ? 'rejected' : 'attempts_exhausted');
}

function readInput() {
  return new Promise((resolve, reject) => {
    let input = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => {
      input += chunk;
      if (Buffer.byteLength(input, 'utf8') > MAX_INPUT_BYTES) reject(new Error('request too large'));
    });
    process.stdin.on('end', () => resolve(input));
    process.stdin.on('error', reject);
  });
}

async function main() {
  const input = await readInput();
  const line = input.split(/\r?\n/, 1)[0];
  const request = parseRequest(line);
  await runRequest(request);
}

if (require.main === module) {
  main().catch(() => {
    process.exitCode = 2;
  });
}

module.exports = { classifyLoginSnapshot, emit, parseRequest, readConfig, runRequest };
