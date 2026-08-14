# Bitget CYD landscape viewer

This 320×240 landscape sketch targets the CYD ESP32-2432S028R: ILI9341 TFT
plus XPT2046 touch. It uses a dark navy dashboard with a large equity card,
color-coded PnL cards, compact position rows, and a clear Pi/Core status badge.
On fetch failures it shows the last successfully received values rather than
zeroing the display.

The device calls only the Pi LAN Viewer `GET /api/esp32`; it never contacts
Bitget or the VPS Core. Copy `secrets.example.h` to `secrets.h`, use a Pi LAN
URL, and configure TFT_eSPI with the supplied `User_Setup.h`.

Arduino libraries: ESP32 board package, ArduinoJson 7, TFT_eSPI,
XPT2046_Touchscreen, and LVGL 8.3.x. `lv_init()` is retained for compatibility
with existing CYD deployments; this focused UI uses TFT_eSPI drawing directly.

## Flash for the home Pi

1. Copy `secrets.example.h` to `secrets.h`.
2. Set the home Wi-Fi SSID/password and `PI_VIEWER_URL` to
   `http://192.168.1.121:8080` (or the Pi's current LAN address).
3. Connect the CYD by USB and run `pio run -t upload` from this directory.
4. Open the serial monitor at 115200 baud. The screen should show `LIVE` and
   the latest cached values after the first refresh.

The firmware only calls the Pi's read-only `GET /api/esp32` endpoint. It never
contains Bitget credentials and never contacts the VPS Core directly.
