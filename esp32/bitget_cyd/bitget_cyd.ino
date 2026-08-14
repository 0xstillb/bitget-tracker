/* Bitget Tracker CYD Viewer — compact dark dashboard for a 320x240 screen. */

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
static const uint32_t USB_PROVISIONING_WINDOW_MS = 120000;
static const size_t SERIAL_LINE_MAX = 512;
static const char *DEFAULT_VIEWER_URL = "http://192.168.1.121:8080";

// A small, high-contrast palette keeps the dashboard readable on the CYD.
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
String lastPositions[3] = {"No open positions", "", ""};
double lastPositionPnl[3] = {0.0, 0.0, 0.0};
uint8_t lastPositionCount = 0;
String lastUpdated = "--:--";
bool coreFresh = false;
bool online = false;
bool configured = false;
uint32_t lastFetchAt = 0;
uint32_t lastWifiAttemptAt = 0;
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

static void connectWifi() {
  if (!configured) return;
  if (WiFi.status() == WL_CONNECTED) return;
  uint32_t now = millis();
  if (lastWifiAttemptAt != 0 && now - lastWifiAttemptAt < WIFI_RETRY_INTERVAL_MS) return;
  lastWifiAttemptAt = now;
  WiFi.mode(WIFI_STA);
  WiFi.begin(wifiSsid.c_str(), wifiPass.c_str());
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

  // Build next state first; failed requests must not zero last-good values.
  double nextEquity = payload["bal"] | lastEquity;
  double nextTodayPnl = payload["day"] | lastTodayPnl;
  double nextOpenPnl = payload["open"] | lastOpenPnl;
  double nextAllPnl = payload["all"] | lastAllPnl;
  String nextUpdated = String((const char *)(payload["upd"] | lastUpdated.c_str()));
  String nextPositions[3] = {"No open positions", "", ""};
  double nextPositionPnl[3] = {0.0, 0.0, 0.0};
  uint8_t nextPositionCount = min((uint8_t)3, (uint8_t)(payload["npos"] | 0));
  JsonArray positions = payload["positions"].as<JsonArray>();
  for (int index = 0; index < 3; ++index) {
    if (index >= positions.size()) break;
    JsonObject position = positions[index];
    const char *symbol = position["s"] | "?";
    const char *direction = position["d"] | "L";
    double pnl = position["u"] | 0.0;
    char line[32];
    snprintf(line, sizeof(line), "%s  %s", symbol, direction);
    nextPositions[index] = line;
    nextPositionPnl[index] = pnl;
  }

  lastEquity = nextEquity;
  lastTodayPnl = nextTodayPnl;
  lastOpenPnl = nextOpenPnl;
  lastAllPnl = nextAllPnl;
  lastUpdated = nextUpdated;
  lastPositionCount = nextPositionCount;
  for (int index = 0; index < 3; ++index) {
    lastPositions[index] = nextPositions[index];
    lastPositionPnl[index] = nextPositionPnl[index];
  }
  coreFresh = !(payload["stale"] | true);
  return true;
}

static void drawMetricCard(int x, int y, int width, int height, const char *label, double value) {
  char amount[24];
  formatUsd(amount, sizeof(amount), value);
  tft.fillRoundRect(x, y, width, height, 6, COLOR_PANEL);
  tft.drawRoundRect(x, y, width, height, 6, COLOR_BORDER);
  tft.setTextColor(COLOR_MUTED, COLOR_PANEL);
  tft.setTextSize(1);
  tft.drawString(label, x + 7, y + 5, 1);
  tft.setTextColor(pnlColor(value), COLOR_PANEL);
  tft.drawString(amount, x + 7, y + 22, 2);
}

static void drawPositionRow(int index, int y) {
  tft.fillRoundRect(5, y, 310, 18, 5, COLOR_PANEL);
  tft.drawRoundRect(5, y, 310, 18, 5, COLOR_BORDER);
  tft.setTextColor(index < lastPositionCount ? TFT_WHITE : COLOR_MUTED, COLOR_PANEL);
  tft.drawString(lastPositions[index], 12, y + 4, 1);
  if (index < lastPositionCount) {
    char amount[20];
    formatUsd(amount, sizeof(amount), lastPositionPnl[index]);
    tft.setTextColor(pnlColor(lastPositionPnl[index]), COLOR_PANEL);
    tft.drawRightString(amount, 306, y + 4, 1);
  }
}

static void drawDashboard() {
  tft.fillScreen(COLOR_BACKGROUND);
  tft.setTextColor(TFT_WHITE, COLOR_BACKGROUND);
  tft.drawString("BITGET TRACKER", 8, 5, 2);
  tft.setTextColor(COLOR_MUTED, COLOR_BACKGROUND);
  tft.drawString("PI VIEWER", 8, 21, 1);
  const char *status = !configured ? "USB SETUP" : (online ? (coreFresh ? "LIVE" : "STALE") : (WiFi.status() == WL_CONNECTED ? "SYNC" : "OFFLINE"));
  tft.setTextColor(online ? (coreFresh ? COLOR_POSITIVE : COLOR_WARNING) : COLOR_NEGATIVE, COLOR_BACKGROUND);
  tft.drawRightString(status, 312, 10, 2);

  char equity[28];
  formatUsd(equity, sizeof(equity), lastEquity);
  tft.fillRoundRect(5, 37, 310, 42, 7, COLOR_PANEL);
  tft.drawRoundRect(5, 37, 310, 42, 7, COLOR_BORDER);
  tft.fillRoundRect(5, 37, 5, 42, 3, COLOR_ACCENT);
  tft.setTextColor(COLOR_MUTED, COLOR_PANEL);
  tft.drawString("TOTAL EQUITY", 14, 43, 1);
  tft.setTextColor(TFT_WHITE, COLOR_PANEL);
  tft.drawRightString(equity, 306, 52, 4);

  drawMetricCard(5, 85, 100, 40, "TODAY P&L", lastTodayPnl);
  drawMetricCard(110, 85, 100, 40, "OPEN P&L", lastOpenPnl);
  drawMetricCard(215, 85, 100, 40, "ALL-TIME", lastAllPnl);

  tft.setTextColor(TFT_WHITE, COLOR_BACKGROUND);
  tft.drawString("OPEN POSITIONS", 7, 132, 2);
  tft.setTextColor(COLOR_MUTED, COLOR_BACKGROUND);
  tft.drawRightString(String(lastPositionCount) + "/3", 312, 133, 1);
  for (int index = 0; index < 3; ++index) {
    drawPositionRow(index, 146 + index * 19);
  }
  tft.setTextColor(COLOR_MUTED, COLOR_BACKGROUND);
  tft.drawString("TOUCH TO REFRESH", 8, 216, 1);
  tft.drawRightString(String("UPDATED ") + lastUpdated, 312, 216, 1);
  tft.drawRightString(!configured ? "USB: send setup" : (WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : "Wi-Fi reconnecting"), 312, 230, 1);
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
  drawDashboard();
}

void loop() {
  uint32_t now = millis();
  handleUsbProvisioning();
  if (configured && WiFi.status() != WL_CONNECTED) connectWifi();
  bool tapped = touch.touched();
  if (configured && (tapped || now - lastFetchAt >= FETCH_INTERVAL_MS)) {
    lastFetchAt = now;
    online = fetchDashboard();  // Failed fetch leaves all last* values intact.
    drawDashboard();
    delay(tapped ? 250 : 0);
  }
  delay(20);
}
