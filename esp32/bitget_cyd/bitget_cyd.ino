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

#if __has_include("secrets.h")
#include "secrets.h"
#else
static const char *WIFI_SSID = "YOUR_WIFI_SSID";
static const char *WIFI_PASS = "YOUR_WIFI_PASSWORD";
static const char *PI_VIEWER_URL = "http://192.168.1.10:8080";
#endif

static const uint16_t SCREEN_WIDTH = 320;
static const uint16_t SCREEN_HEIGHT = 240;
static const uint32_t FETCH_INTERVAL_MS = 30000;

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
uint32_t lastFetchAt = 0;

static uint16_t pnlColor(double value) {
  if (value > 0.004) return COLOR_POSITIVE;
  if (value < -0.004) return COLOR_NEGATIVE;
  return TFT_WHITE;
}

static void formatUsd(char *out, size_t length, double value) {
  snprintf(out, length, "%s$%.2f", value > 0.004 ? "+" : (value < -0.004 ? "-" : ""), fabs(value));
}

static void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
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
  const char *status = online ? (coreFresh ? "LIVE" : "STALE") : (WiFi.status() == WL_CONNECTED ? "SYNC" : "OFFLINE");
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
  tft.drawRightString(WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : "Wi-Fi reconnecting", 312, 230, 1);
}

static void loadConfiguration() {
  preferences.begin("bitget-view", true);
  wifiSsid = preferences.getString("ssid", WIFI_SSID);
  wifiPass = preferences.getString("pass", WIFI_PASS);
  viewerUrl = preferences.getString("url", PI_VIEWER_URL);
  preferences.end();
  while (viewerUrl.endsWith("/")) viewerUrl.remove(viewerUrl.length() - 1);
}

void setup() {
  Serial.begin(115200);
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
  if (WiFi.status() != WL_CONNECTED) connectWifi();
  bool tapped = touch.touched();
  if (tapped || now - lastFetchAt >= FETCH_INTERVAL_MS) {
    lastFetchAt = now;
    online = fetchDashboard();  // Failed fetch leaves all last* values intact.
    drawDashboard();
    delay(tapped ? 250 : 0);
  }
  delay(20);
}
