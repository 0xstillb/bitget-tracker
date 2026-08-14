const REQUIRED_SESSION_COOKIE = "bt_newsessionid";
const copyButton = document.querySelector("#copy-session");
const status = document.querySelector("#status");

function showStatus(message, kind = "") {
  status.textContent = message;
  status.className = kind;
}

function toCookieHeader(cookies) {
  return cookies
    .filter((cookie) => cookie.value)
    .sort((left, right) => left.name.localeCompare(right.name))
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");
}

async function copyBitgetSession() {
  copyButton.disabled = true;
  showStatus("Reading the current Bitget session…");

  try {
    const cookies = await chrome.cookies.getAll({ domain: "bitget.com" });
    if (!cookies.some((cookie) => cookie.name === REQUIRED_SESSION_COOKIE)) {
      showStatus("No bt_newsessionid found. Sign in again at bitget.com, then retry.", "error");
      return;
    }

    await navigator.clipboard.writeText(toCookieHeader(cookies));
    showStatus("Copied. Paste it directly into the private VPS config, then clear your clipboard.", "ok");
  } catch (error) {
    console.error("Could not copy Bitget session", error);
    showStatus("Could not copy the session. Check the Chrome extension permission and try again.", "error");
  } finally {
    copyButton.disabled = false;
  }
}

copyButton.addEventListener("click", copyBitgetSession);
