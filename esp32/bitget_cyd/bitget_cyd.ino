/* Bitget Tracker CYD Viewer — simplified 320x240 landscape status screen. */

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
String lastUpdated = "--:--";
bool coreFresh = false;
bool online = false;
uint32_t lastFetchAt = 0;

static uint16_t pnlColor(double value) {
  if (value > 0.004) return TFT_GREEN;
  if (value < -0.004) return TFT_RED;
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
  JsonArray positions = payload["positions"].as<JsonArray>();
  for (int index = 0; index < 3; ++index) {
    if (index >= positions.size()) break;
    JsonObject position = positions[index];
    const char *symbol = position["s"] | "?";
    const char *direction = position["d"] | "L";
    double pnl = position["u"] | 0.0;
    char line[64];
    snprintf(line, sizeof(line), "%s %s  %+.2f", symbol, direction, pnl);
    nextPositions[index] = line;
  }

  lastEquity = nextEquity;
  lastTodayPnl = nextTodayPnl;
  lastOpenPnl = nextOpenPnl;
  lastAllPnl = nextAllPnl;
  lastUpdated = nextUpdated;
  for (int index = 0; index < 3; ++index) lastPositions[index] = nextPositions[index];
  coreFresh = !(payload["stale"] | true);
  return true;
}

static void drawCard(int x, int y, int width, int height, const char *label, double value) {
  char amount[24];
  formatUsd(amount, sizeof(amount), value);
  tft.fillRoundRect(x, y, width, height, 5, TFT_DARKGREY);
  tft.setTextColor(TFT_LIGHTGREY, TFT_DARKGREY);
  tft.setTextSize(1);
  tft.drawString(label, x + 5, y + 5);
  tft.setTextColor(pnlColor(value), TFT_DARKGREY);
  tft.setTextSize(2);
  tft.drawString(amount, x + 5, y + 20);
}

static void drawDashboard() {
  tft.fillScreen(TFT_BLACK);
  tft.setTextSize(1);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.drawString("BITGET PI VIEWER", 6, 5);
  tft.setTextColor(online ? (coreFresh ? TFT_GREEN : TFT_YELLOW) : TFT_RED, TFT_BLACK);
  tft.drawRightString(online ? (coreFresh ? "ONLINE" : "STALE") : "OFFLINE", 314, 5, 1);

  char equity[28];
  formatUsd(equity, sizeof(equity), lastEquity);
  tft.fillRoundRect(5, 20, 310, 38, 5, TFT_NAVY);
  tft.setTextColor(TFT_LIGHTGREY, TFT_NAVY);
  tft.setTextSize(1);
  tft.drawString("EQUITY", 12, 26);
  tft.setTextColor(TFT_WHITE, TFT_NAVY);
  tft.setTextSize(2);
  tft.drawRightString(equity, 306, 34, 2);

  drawCard(5, 64, 100, 48, "TODAY P&L", lastTodayPnl);
  drawCard(110, 64, 100, 48, "OPEN P&L", lastOpenPnl);
  drawCard(215, 64, 100, 48, "ALL TIME", lastAllPnl);

  tft.setTextSize(1);
  tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  tft.drawString("POSITIONS (latest 3)", 6, 119);
  for (int index = 0; index < 3; ++index) {
    int y = 134 + index * 24;
    tft.drawRoundRect(5, y, 310, 20, 3, TFT_DARKGREY);
    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.drawString(lastPositions[index], 11, y + 6);
  }
  tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  tft.drawString(String("Updated: ") + lastUpdated, 6, 218);
  tft.drawRightString(WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : "Wi-Fi reconnecting", 314, 218, 1);
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
