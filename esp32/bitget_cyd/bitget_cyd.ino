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
static const uint16_t COLOR_BACKGROUND = TFT_BLACK;
static const uint16_t COLOR_PANEL = 0x0861;
static const uint16_t COLOR_BORDER = 0x18C4;
static const uint16_t COLOR_ACCENT = 0x4E9F;
static const uint16_t COLOR_MUTED = 0x9CF3;
static const uint16_t COLOR_POSITIVE = 0x34E8;
static const uint16_t COLOR_NEGATIVE = 0xF967;
static const uint16_t COLOR_WARNING = 0xFD20;

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

static void formatBalance(char *out, size_t length, double value) {
  snprintf(out, length, "$%.2f", fabs(value));
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
  if (lastAuthState == "disabled") return "AUTO LOGIN OFF";
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
  tft.fillRoundRect(x, 76, 73, 48, 6, COLOR_PANEL);
  tft.drawRoundRect(x, 76, 73, 48, 6, COLOR_BORDER);
  tft.setTextColor(COLOR_MUTED, COLOR_PANEL);
  tft.drawString(label, x + 5, 82, 1);
}

static void drawDashboardChrome() {
  tft.fillScreen(COLOR_BACKGROUND);
  // Exact 320x240 order from the approved mockup: hero, four cards, then panels.
  tft.fillRoundRect(5, 5, 310, 65, 8, COLOR_PANEL);
  tft.drawRoundRect(5, 5, 310, 65, 8, COLOR_BORDER);
  tft.setTextColor(COLOR_MUTED, COLOR_PANEL);
  tft.drawString("TOTAL EQUITY", 14, 12, 1);

  drawMetricFrame(5, "TODAY P&L");
  drawMetricFrame(83, "OPEN P&L");
  drawMetricFrame(161, "ALL-TIME P&L");
  drawMetricFrame(239, "OPEN POSITIONS");

  tft.fillRoundRect(5, 130, 310, 43, 7, COLOR_PANEL);
  tft.drawRoundRect(5, 130, 310, 43, 7, COLOR_BORDER);
  tft.setTextColor(TFT_WHITE, COLOR_PANEL);
  tft.drawString("OPEN POSITIONS", 13, 136, 1);

  tft.fillRoundRect(5, 178, 310, 43, 7, COLOR_PANEL);
  tft.drawRoundRect(5, 178, 310, 43, 7, COLOR_BORDER);
  tft.setTextColor(TFT_WHITE, COLOR_PANEL);
  tft.drawString("TRACKED PORTFOLIOS", 13, 184, 1);
  screenChromeDrawn = true;
}

static void drawHeroStatus() {
  tft.fillRoundRect(218, 12, 89, 17, 9, COLOR_PANEL);
  tft.drawRoundRect(218, 12, 89, 17, 9, authColor());
  tft.setTextColor(authColor(), COLOR_PANEL);
  tft.drawCentreString(authLabel(), 262, 17, 1);
}

static void drawEquity() {
  char equity[28];
  formatBalance(equity, sizeof(equity), lastEquity);
  tft.fillRect(13, 27, 200, 26, COLOR_PANEL);
  tft.setTextColor(TFT_WHITE, COLOR_PANEL);
  tft.drawString(equity, 14, 27, 4);
  tft.fillRect(13, 55, 200, 11, COLOR_PANEL);
  tft.setTextColor(COLOR_MUTED, COLOR_PANEL);
  tft.drawString(String("Updated ") + compactUpdated(lastUpdated), 14, 56, 1);
}

static void drawMetricValue(int x, double value, double base) {
  char amount[20];
  char percent[16];
  formatUsd(amount, sizeof(amount), value);
  formatPercent(percent, sizeof(percent), value, base);
  tft.fillRect(x + 4, 96, 65, 25, COLOR_PANEL);
  tft.setTextColor(pnlColor(value), COLOR_PANEL);
  tft.drawCentreString(amount, x + 36, 98, 2);
  tft.setTextColor(value == 0.0 ? COLOR_MUTED : pnlColor(value), COLOR_PANEL);
  tft.drawCentreString(percent, x + 36, 113, 1);
}

static void drawPositionMetric() {
  tft.fillRect(243, 96, 65, 25, COLOR_PANEL);
  tft.setTextColor(TFT_WHITE, COLOR_PANEL);
  tft.drawCentreString(String(lastOpenPositionCount), 275, 98, 2);
  tft.setTextColor(COLOR_MUTED, COLOR_PANEL);
  tft.drawCentreString(lastOpenPositionCount == 1 ? "1 active" : String(lastOpenPositionCount) + " active", 275, 113, 1);
}

static void drawPositionPanel() {
  tft.fillRect(13, 149, 295, 20, COLOR_PANEL);
  tft.setTextColor(COLOR_MUTED, COLOR_PANEL);
  tft.drawRightString(String(lastOpenPositionCount) + " active", 306, 136, 1);
  if (lastPositionCount == 0) {
    tft.setTextColor(COLOR_MUTED, COLOR_PANEL);
    tft.drawCentreString("No active data", 160, 153, 1);
    return;
  }
  tft.setTextColor(TFT_WHITE, COLOR_PANEL);
  tft.drawString(lastPositions[0], 14, 153, 1);
  char amount[18];
  formatUsd(amount, sizeof(amount), lastPositionPnl[0]);
  tft.setTextColor(pnlColor(lastPositionPnl[0]), COLOR_PANEL);
  tft.drawRightString(amount, 306, 153, 1);
}

static void drawPortfolio() {
  tft.fillRect(12, 196, 296, 20, COLOR_PANEL);
  tft.setTextColor(COLOR_MUTED, COLOR_PANEL);
  tft.drawRightString(String(lastTraderCount) + " tracked", 306, 184, 1);
  uint16_t ringColor = lastTraderCount > 0 ? COLOR_POSITIVE : COLOR_MUTED;
  tft.drawCircle(23, 205, 8, ringColor);
  tft.drawCircle(23, 205, 7, ringColor);
  if (lastTraderCount == 0) {
    tft.setTextColor(COLOR_MUTED, COLOR_PANEL);
    tft.drawString("No tracked data", 40, 200, 1);
    return;
  }
  tft.setTextColor(TFT_WHITE, COLOR_PANEL);
  tft.drawString(lastPortfolioName, 40, 200, 1);
  char amount[18];
  formatUsd(amount, sizeof(amount), lastPortfolioPnl);
  tft.setTextColor(pnlColor(lastPortfolioPnl), COLOR_PANEL);
  tft.drawRightString(amount, 306, 200, 1);
}

static void drawFooter() {
  tft.fillRect(5, 225, 310, 12, COLOR_BACKGROUND);
  tft.setTextColor(COLOR_MUTED, COLOR_BACKGROUND);
  tft.drawCentreString(String("Updated ") + compactUpdated(lastUpdated) + "  ·  Tap refresh", 160, 228, 1);
}

static void renderDashboard() {
  if (!screenChromeDrawn) drawDashboardChrome();
  drawHeroStatus();
  drawEquity();
  drawMetricValue(5, lastTodayPnl, lastEquity);
  drawMetricValue(83, lastOpenPnl, lastEquity);
  drawMetricValue(161, lastAllPnl, lastEquity);
  drawPositionMetric();
  drawPositionPanel();
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
