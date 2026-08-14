# Bitget CYD landscape viewer

This 320×240 landscape sketch targets the CYD ESP32-2432S028R: ILI9341 TFT
plus XPT2046 touch. It uses a dark navy dashboard with a large equity card,
color-coded PnL cards, compact position rows, and a clear Pi/Core status badge.
On fetch failures it shows the last successfully received values rather than
zeroing the display.

The device calls only the Pi LAN Viewer `GET /api/esp32`; it never contacts
Bitget or the VPS Core. Wi-Fi credentials are entered over the physical USB
serial connection and stored in ESP32 NVS. They are not compiled into the
firmware. Never commit Wi-Fi credentials to the repository.

Arduino libraries: ESP32 board package, ArduinoJson 7, TFT_eSPI,
XPT2046_Touchscreen, and LVGL 8.3.x. `lv_init()` is retained for compatibility
with existing CYD deployments; this focused UI uses TFT_eSPI drawing directly.

## Flash and USB provisioning for the home Pi

1. Connect the CYD by USB and run `pio run -t upload` from this directory.
2. Open a serial monitor at 115200 baud within two minutes of boot.
3. Send one JSON line, replacing the local values. The password is accepted
   but never printed back:

   ```json
   {"cmd":"set_wifi","ssid":"Home WiFi","password":"your-password","viewer_url":"http://192.168.1.121:8080"}
   ```

4. The device stores the values in NVS and restarts. It should show `LIVE`
   after the first successful refresh.

The serial protocol also supports `{"cmd":"status"}` (safe, no password
returned) and `{"cmd":"reset"}` during the two-minute USB window. Reset
clears the stored Wi-Fi and returns the device to `USB SETUP` mode. Keep the
USB session local; do not paste credentials into source files or commit them.

The firmware only calls the Pi's read-only `GET /api/esp32` endpoint. It never
contains Bitget credentials and never contacts the VPS Core directly.
