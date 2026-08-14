# Bitget Session Copier (Local Only)

This unpacked Chrome extension copies the current Bitget cookie header to your
clipboard after you explicitly click its button. It is for the Bitget account
you control and is intended to seed `BITGET_COOKIE` on a private tracker VPS.

It requests only:

- `cookies`, limited to `https://*.bitget.com/*`, so it can include the
  HttpOnly `bt_newsessionid` cookie that page JavaScript cannot read.
- `clipboardWrite`, so it can copy the assembled cookie header.

The extension never sends the cookie anywhere, never stores it, has no
background worker, and makes no network requests. Clipboard contents are
secrets: paste them directly into the private VPS configuration, then clear
your clipboard.

## Install in Chrome

1. Download or clone this repository on the computer where you sign in to
   Bitget.
2. Open `chrome://extensions`.
3. Enable **Developer mode**.
4. Select **Load unpacked** and choose this `chrome-extension` directory.
5. Pin **Bitget Session Copier (Local Only)** from Chrome's Extensions menu.

## Copy the current session

1. Sign in to `https://www.bitget.com` in the same Chrome profile.
2. Click the extension icon and select **Copy session to clipboard**.
3. A successful copy requires `bt_newsessionid`. If it is missing, sign out,
   sign in again, and retry.
4. On the VPS, replace only the value after `BITGET_COOKIE=` in
   `~/.config/bitget-tracker/core.env`. Do not paste the cookie into chat,
   Git, issues, screenshots, or shell history.
5. Delete the prior runtime cookie cache and restart the Core so it uses the
   newly seeded value. The Core deployment guide explains this rotation step.

This extension does not open a listening port. It cannot bypass Bitget login,
CAPTCHA, MFA, device approval, expiry, or any account-security controls.
