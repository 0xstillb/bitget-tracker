/* Bitget Tracker CYD Viewer — live 320x240 dark dashboard for the Pi Viewer. */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <lvgl.h>
#include <TFT_eSPI.h>
#include <XPT2046_Touchscreen.h>
#include <SPI.h>

static const uint16_t SCREEN_WIDTH = 320;
static const uint16_t SCREEN_HEIGHT = 240;
static const uint32_t FETCH_INTERVAL_MS = 30000;
static const uint32_t WIFI_RETRY_INTERVAL_MS = 10000;
static const uint32_t TOUCH_DEBOUNCE_MS = 600;
static const uint32_t USB_PROVISIONING_WINDOW_MS = 120000;
static const size_t SERIAL_LINE_MAX = 512;
static const char *DEFAULT_VIEWER_URL = "http://192.168.1.121:8080";

// Compact version of the Pi mockup palette. Values are RGB565 for ILI9341.
static const uint16_t COLOR_BACKGROUND = 0x0841;
static const uint16_t COLOR_PANEL = 0x10A3;
static const uint16_t COLOR_BORDER = 0x2A85;
static const uint16_t COLOR_ACCENT = 0x45FF;
static const uint16_t COLOR_MUTED = 0x9D5B;
static const uint16_t COLOR_POSITIVE = 0x55EA;
static const uint16_t COLOR_NEGATIVE = 0xF8C6;
static const uint16_t COLOR_WARNING = 0xF6A0;

#define XPT2046_IRQ 36
#define XPT2046_MOSI 32
#define XPT2046_MISO 39
#define XPT2046_CLK 25
#define XPT2046_CS 33

SPIClass touchSPI(HSPI);
XPT2046_Touchscreen touch(XPT2046_CS, XPT2046_IRQ);
TFT_eSPI tft = TFT_eSPI();
Preferences preferences;

String wifiSsid;
String wifiPass;
String viewerUrl;
double lastEquity = 0.0;
double lastTodayPnl = 0.0;
double lastOpenPnl = 0.0;
double lastAllPnl = 0.0;
String lastPositions[2] = {"No active positions", ""};
double lastPositionPnl[2] = {0.0, 0.0};
uint8_t lastPositionCount = 0;
uint16_t lastOpenPositionCount = 0;
String lastPortfolioName = "No tracked portfolio";
double lastPortfolioPnl = 0.0;
double lastPortfolioBalance = 0.0;
uint8_t lastTraderCount = 0;
String lastAuthState = "unknown";
String lastUpdated = "--:--";
bool coreFresh = false;
bool online = false;
bool configured = false;
bool screenChromeDrawn = false;
bool touchWasDown = false;
uint32_t lastFetchAt = 0;
uint32_t lastWifiAttemptAt = 0;
uint32_t lastTouchAt = 0;
uint32_t provisioningDeadline = 0;
String serialLine;
bool serialLineOverflow = false;

static bool provisioningWindowOpen() {
  return (int32_t)(provisioningDeadline - millis()) > 0;
}

static void sendProvisioningResult(bool ok, const char *code) {
  JsonDocument response;
  response["ok"] = ok;
  response[ok ? "saved" : "error"] = code;
  serializeJson(response, Serial);
  Serial.println();
}

static void sendProvisioningStatus() {
  JsonDocument response;
  response["ok"] = true;
  response["configured"] = configured;
  response["window_open"] = provisioningWindowOpen();
  response["viewer_url"] = viewerUrl;
  serializeJson(response, Serial);
  Serial.println();
}

static bool validViewerUrl(const String &url) {
  return url.startsWith("http://") || url.startsWith("https://");
}

static void handleProvisioningCommand(const String &line) {
  JsonDocument request;
  if (deserializeJson(request, line)) {
    sendProvisioningResult(false, "invalid_json");
    return;
  }

  const char *command = request["cmd"] | "";
  if (strcmp(command, "status") == 0) {
    sendProvisioningStatus();
    return;
  }
  if (!provisioningWindowOpen()) {
    sendProvisioningResult(false, "window_closed");
    return;
  }
  if (strcmp(command, "reset") == 0) {
    preferences.begin("bitget-view", false);
    preferences.clear();
    preferences.end();
    sendProvisioningResult(true, "reset");
    delay(100);
    ESP.restart();
    return;
  }
  if (strcmp(command, "set_wifi") != 0) {
    sendProvisioningResult(false, "unknown_command");
    return;
  }

  const char *ssid = request["ssid"] | "";
  const char *password = request["password"] | "";
  String nextViewerUrl = String(request["viewer_url"] | DEFAULT_VIEWER_URL);
  if (strlen(ssid) == 0 || strlen(ssid) > 32 || strlen(password) > 63 ||
      nextViewerUrl.length() > 200 || !validViewerUrl(nextViewerUrl)) {
    sendProvisioningResult(false, "invalid_config");
    return;
  }

  preferences.begin("bitget-view", false);
  bool saved = preferences.putString("ssid", ssid) > 0;
  saved = preferences.putString("pass", password) > 0 && saved;
  saved = preferences.putString("url", nextViewerUrl) > 0 && saved;
  preferences.end();
  if (!saved) {
    sendProvisioningResult(false, "save_failed");
    return;
  }

  sendProvisioningResult(true, "restarting");
  delay(100);
  ESP.restart();
}

static void handleUsbProvisioning() {
  while (Serial.available() > 0) {
    char character = (char)Serial.read();
    if (character == '\r') continue;
    if (character == '\n') {
      if (serialLineOverflow) {
        sendProvisioningResult(false, "line_too_long");
      } else if (serialLine.length() > 0) {
        handleProvisioningCommand(serialLine);
      }
      serialLine = "";
      serialLineOverflow = false;
      continue;
    }
    if (serialLine.length() < SERIAL_LINE_MAX) {
      serialLine += character;
    } else {
      serialLineOverflow = true;
    }
  }
}

static uint16_t pnlColor(double value) {
  if (value > 0.004) return COLOR_POSITIVE;
  if (value < -0.004) return COLOR_NEGATIVE;
  return TFT_WHITE;
}

static void formatUsd(char *out, size_t length, double value) {
  snprintf(out, length, "%s$%.2f", value > 0.004 ? "+" : (value < -0.004 ? "-" : ""), fabs(value));
}

static void formatPercent(char *out, size_t length, double value, double base) {
  if (base <= 0.004) {
    snprintf(out, length, "--");
    return;
  }
  double percent = (value / base) * 100.0;
  snprintf(out, length, "%s%.2f%%", percent > 0.004 ? "+" : (percent < -0.004 ? "-" : ""), fabs(percent));
}

static String compactUpdated(const String &value) {
  int separator = value.indexOf('T');
  if (separator < 0) separator = value.indexOf(' ');
  if (separator >= 0 && value.length() >= separator + 6) return value.substring(separator + 1, separator + 6);
  return value.length() > 8 ? value.substring(value.length() - 8) : value;
}

static void connectWifi() {
  if (!configured || WiFi.status() == WL_CONNECTED) return;
  uint32_t now = millis();
  if (lastWifiAttemptAt != 0 && now - lastWifiAttemptAt < WIFI_RETRY_INTERVAL_MS) return;
  lastWifiAttemptAt = now;
  WiFi.mode(WIFI_STA);
  WiFi.begin(wifiSsid.c_str(), wifiPass.c_str());
}

static bool fetchAuthStatus() {
  if (WiFi.status() != WL_CONNECTED) return false;
  HTTPClient http;
  String endpoint = viewerUrl + "/api/v1/auth";
  http.setTimeout(3000);
  if (!http.begin(endpoint)) return false;
  int status = http.GET();
  if (status != HTTP_CODE_OK) {
    http.end();
    return false;
  }
  String body = http.getString();
  http.end();
  JsonDocument payload;
  if (deserializeJson(payload, body)) return false;
  const char *state = payload["login_state"] | "";
  if (strlen(state) == 0) state = payload["session_state"] | "";
  if (strlen(state) == 0) return false;
  lastAuthState = state;
  return true;
}

static bool fetchDashboard() {
  if (WiFi.status() != WL_CONNECTED) return false;
  HTTPClient http;
  String endpoint = viewerUrl + "/api/esp32";
  http.setTimeout(5000);
  if (!http.begin(endpoint)) return false;
  int status = http.GET();
  if (status != HTTP_CODE_OK) {
    http.end();
    return false;
  }
  String body = http.getString();
  http.end();

  JsonDocument payload;
  if (deserializeJson(payload, body)) return false;
  if (!payload["ok"].as<bool>()) return false;

  // Build next state first; failures never zero last-good values.
  double nextEquity = payload["bal"] | lastEquity;
  double nextTodayPnl = payload["day"] | lastTodayPnl;
  double nextOpenPnl = payload["open"] | lastOpenPnl;
  double nextAllPnl = payload["all"] | lastAllPnl;
  String nextUpdated = String((const char *)(payload["upd"] | lastUpdated.c_str()));
  String nextPositions[2] = {"No active positions", ""};
  double nextPositionPnl[2] = {0.0, 0.0};
  JsonArray positions = payload["positions"].as<JsonArray>();
  uint8_t nextPositionCount = min((uint8_t)2, (uint8_t)positions.size());
  uint16_t nextOpenPositionCount = payload["npos"] | nextPositionCount;
  for (int index = 0; index < nextPositionCount; ++index) {
    JsonObject position = positions[index];
    const char *symbol = position["s"] | "?";
    const char *direction = position["d"] | "L";
    nextPositions[index] = String(symbol) + "  " + direction;
    nextPositionPnl[index] = position["u"] | 0.0;
  }

  JsonArray traders = payload["traders"].as<JsonArray>();
  uint8_t nextTraderCount = min((uint8_t)99, (uint8_t)traders.size());
  String nextPortfolioName = "No tracked portfolio";
  double nextPortfolioPnl = 0.0;
  double nextPortfolioBalance = 0.0;
  if (nextTraderCount > 0) {
    JsonObject trader = traders[0];
    nextPortfolioName = String((const char *)(trader["n"] | "Portfolio"));
    nextPortfolioPnl = trader["day"] | 0.0;
    nextPortfolioBalance = trader["bal"] | 0.0;
  }

  lastEquity = nextEquity;
  lastTodayPnl = nextTodayPnl;
  lastOpenPnl = nextOpenPnl;
  lastAllPnl = nextAllPnl;
  lastUpdated = nextUpdated;
  lastPositionCount = nextPositionCount;
  lastOpenPositionCount = nextOpenPositionCount;
  for (int index = 0; index < 2; ++index) {
    lastPositions[index] = nextPositions[index];
    lastPositionPnl[index] = nextPositionPnl[index];
  }
  lastTraderCount = nextTraderCount;
  lastPortfolioName = nextPortfolioName;
  lastPortfolioPnl = nextPortfolioPnl;
  lastPortfolioBalance = nextPortfolioBalance;
  coreFresh = !(payload["stale"] | true);
  return true;
}

static const char *connectionLabel() {
  if (!configured) return "USB SETUP";
  if (online) return coreFresh ? "LIVE" : "STALE";
  return WiFi.status() == WL_CONNECTED ? "SYNC" : "OFFLINE";
}

static uint16_t connectionColor() {
  if (!configured) return COLOR_WARNING;
  if (online && coreFresh) return COLOR_POSITIVE;
  if (online) return COLOR_WARNING;
  return COLOR_NEGATIVE;
}

static const char *authLabel() {
  if (lastAuthState == "success") return "AUTH OK";
  if (lastAuthState == "disabled") return "AUTO OFF";
  if (lastAuthState == "approval_required" || lastAuthState == "otp_required" || lastAuthState == "captcha_required") return "APPROVE";
  if (lastAuthState == "running") return "LOGIN...";
  if (lastAuthState == "failed") return "LOGIN FAIL";
  return "AUTH ?";
}

static uint16_t authColor() {
  if (lastAuthState == "success") return COLOR_POSITIVE;
  if (lastAuthState == "failed" || lastAuthState == "unavailable") return COLOR_NEGATIVE;
  return COLOR_WARNING;
}

static void drawMetricFrame(int x, const char *label) {
  tft.fillRoundRect(x, 76, 100, 42, 6, COLOR_PANEL);
  tft.drawRoundRect(x, 76, 100, 42, 6, COLOR_BORDER);
  tft.setTextColor(COLOR_MUTED, COLOR_PANEL);
  tft.drawString(label, x + 6, 81, 1);
}

static void drawDashboardChrome() {
  tft.fillScreen(COLOR_BACKGROUND);
  tft.setTextColor(COLOR_MUTED, COLOR_BACKGROUND);
  tft.drawString("READ-ONLY  PI VIEWER", 8, 5, 1);

  // Hero card follows the mockup: label, large equity, and live auth badge.
  tft.fillRoundRect(5, 19, 310, 51, 7, COLOR_PANEL);
  tft.drawRoundRect(5, 19, 310, 51, 7, COLOR_BORDER);
  tft.fillRoundRect(5, 19, 4, 51, 2, COLOR_ACCENT);
  tft.setTextColor(COLOR_MUTED, COLOR_PANEL);
  tft.drawString("TOTAL EQUITY", 14, 25, 1);

  drawMetricFrame(5, "TODAY");
  drawMetricFrame(110, "OPEN");
  drawMetricFrame(215, "ALL-TIME");

  tft.setTextColor(TFT_WHITE, COLOR_BACKGROUND);
  tft.drawString("OPEN POSITIONS", 7, 124, 1);
  for (int index = 0; index < 2; ++index) {
    int y = 136 + index * 19;
    tft.fillRoundRect(5, y, 310, 17, 4, COLOR_PANEL);
    tft.drawRoundRect(5, y, 310, 17, 4, COLOR_BORDER);
  }

  tft.fillRoundRect(5, 176, 310, 34, 6, COLOR_PANEL);
  tft.drawRoundRect(5, 176, 310, 34, 6, COLOR_BORDER);
  tft.setTextColor(TFT_WHITE, COLOR_PANEL);
  tft.drawString("TRACKED PORTFOLIO", 12, 181, 1);
  tft.setTextColor(COLOR_MUTED, COLOR_BACKGROUND);
  tft.drawString("TAP: REFRESH", 8, 217, 1);
  screenChromeDrawn = true;
}

static void drawHeaderStatus() {
  tft.fillRect(220, 3, 94, 12, COLOR_BACKGROUND);
  tft.setTextColor(connectionColor(), COLOR_BACKGROUND);
  tft.drawRightString(connectionLabel(), 312, 4, 1);
  tft.fillRect(205, 24, 102, 10, COLOR_PANEL);
  tft.setTextColor(authColor(), COLOR_PANEL);
  tft.drawRightString(authLabel(), 304, 25, 1);
}

static void drawEquity() {
  char equity[28];
  formatUsd(equity, sizeof(equity), lastEquity);
  tft.fillRect(62, 39, 243, 27, COLOR_PANEL);
  tft.setTextColor(TFT_WHITE, COLOR_PANEL);
  tft.drawRightString(equity, 305, 39, 4);
}

static void drawMetricValue(int x, double value) {
  char amount[20];
  formatUsd(amount, sizeof(amount), value);
  tft.fillRect(x + 5, 96, 90, 19, COLOR_PANEL);
  tft.setTextColor(pnlColor(value), COLOR_PANEL);
  tft.drawCentreString(amount, x + 50, 98, 2);
}

static void drawPositionRow(int index, int y) {
  tft.fillRoundRect(6, y + 1, 308, 15, 4, COLOR_PANEL);
  if (index >= lastPositionCount) {
    tft.setTextColor(COLOR_MUTED, COLOR_PANEL);
    tft.drawString(index == 0 ? "No active data" : "", 12, y + 4, 1);
    return;
  }
  tft.setTextColor(TFT_WHITE, COLOR_PANEL);
  tft.drawString(lastPositions[index], 12, y + 4, 1);
  char amount[18];
  formatUsd(amount, sizeof(amount), lastPositionPnl[index]);
  tft.setTextColor(pnlColor(lastPositionPnl[index]), COLOR_PANEL);
  tft.drawRightString(amount, 306, y + 4, 1);
}

static void drawPortfolio() {
  tft.fillRect(10, 193, 300, 14, COLOR_PANEL);
  uint16_t ringColor = lastTraderCount > 0 ? COLOR_POSITIVE : COLOR_MUTED;
  tft.fillCircle(20, 199, 7, ringColor);
  tft.fillCircle(20, 199, 4, COLOR_PANEL);
  tft.setTextColor(lastTraderCount > 0 ? TFT_WHITE : COLOR_MUTED, COLOR_PANEL);
  tft.drawString(lastPortfolioName, 32, 194, 1);
  char amount[18];
  formatUsd(amount, sizeof(amount), lastPortfolioPnl);
  tft.setTextColor(pnlColor(lastPortfolioPnl), COLOR_PANEL);
  tft.drawRightString(amount, 304, 194, 1);
}

static void drawFooter() {
  tft.fillRect(132, 214, 182, 21, COLOR_BACKGROUND);
  tft.setTextColor(COLOR_MUTED, COLOR_BACKGROUND);
  tft.drawRightString(String("Updated ") + compactUpdated(lastUpdated), 312, 217, 1);
  String network = !configured ? "USB: setup" : (WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : "Wi-Fi reconnecting");
  tft.drawRightString(network, 312, 229, 1);
}

static void renderDashboard() {
  if (!screenChromeDrawn) drawDashboardChrome();
  drawHeaderStatus();
  drawEquity();
  drawMetricValue(5, lastTodayPnl);
  drawMetricValue(110, lastOpenPnl);
  drawMetricValue(215, lastAllPnl);
  for (int index = 0; index < 2; ++index) drawPositionRow(index, 136 + index * 19);
  tft.fillRect(263, 120, 50, 10, COLOR_BACKGROUND);
  tft.setTextColor(COLOR_MUTED, COLOR_BACKGROUND);
  tft.drawRightString(String(lastOpenPositionCount) + " active", 312, 124, 1);
  tft.fillRect(258, 180, 54, 10, COLOR_PANEL);
  tft.setTextColor(COLOR_MUTED, COLOR_PANEL);
  tft.drawRightString(String(lastTraderCount) + " tracked", 307, 181, 1);
  drawPortfolio();
  drawFooter();
}

static void loadConfiguration() {
  preferences.begin("bitget-view", true);
  wifiSsid = preferences.getString("ssid", "");
  wifiPass = preferences.getString("pass", "");
  viewerUrl = preferences.getString("url", DEFAULT_VIEWER_URL);
  preferences.end();
  while (viewerUrl.endsWith("/")) viewerUrl.remove(viewerUrl.length() - 1);
  configured = wifiSsid.length() > 0 && wifiPass.length() > 0 && validViewerUrl(viewerUrl);
}

void setup() {
  Serial.begin(115200);
  provisioningDeadline = millis() + USB_PROVISIONING_WINDOW_MS;
  Serial.println("{\"ready\":true,\"protocol\":\"usb-provisioning-v1\"}");
  lv_init();  // Retain compatibility with existing CYD LVGL deployments.
  tft.init();
  tft.setRotation(1);
  tft.setSwapBytes(true);
  touchSPI.begin(XPT2046_CLK, XPT2046_MISO, XPT2046_MOSI, XPT2046_CS);
  touch.begin(touchSPI);
  touch.setRotation(1);
  loadConfiguration();
  connectWifi();
  drawDashboardChrome();
  renderDashboard();
}

void loop() {
  uint32_t now = millis();
  handleUsbProvisioning();
  if (configured && WiFi.status() != WL_CONNECTED) connectWifi();

  bool touchDown = touch.touched();
  bool tapped = touchDown && !touchWasDown && (now - lastTouchAt >= TOUCH_DEBOUNCE_MS);
  if (tapped) lastTouchAt = now;
  touchWasDown = touchDown;

  if (configured && (tapped || now - lastFetchAt >= FETCH_INTERVAL_MS)) {
    lastFetchAt = now;
    online = fetchDashboard();
    if (online) fetchAuthStatus();
    renderDashboard();
  }
  delay(20);
}
