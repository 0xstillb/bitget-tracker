# Bitget CYD landscape viewer

This simplified 320×240 landscape sketch targets the CYD ESP32-2432S028R:
ILI9341 TFT plus XPT2046 touch. It displays equity, Today/Open/All-time PnL,
the latest three positions, and Core/Pi status. On fetch failures it shows the
last successfully received values rather than zeroing the display.

The device calls only the Pi LAN Viewer `GET /api/esp32`; it never contacts
Bitget or the VPS Core. Copy `secrets.example.h` to `secrets.h`, use a Pi LAN
URL, and configure TFT_eSPI with the supplied `User_Setup.h`.

Arduino libraries: ESP32 board package, ArduinoJson 7, TFT_eSPI,
XPT2046_Touchscreen, and LVGL 8.3.x. `lv_init()` is retained for compatibility
with existing CYD deployments; this focused UI uses TFT_eSPI drawing directly.
