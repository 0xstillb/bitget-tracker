// Copy over TFT_eSPI/User_Setup.h for CYD ESP32-2432S028R (ILI9341).
#define USER_SETUP_INFO "Bitget CYD landscape"
#define ILI9341_DRIVER
#define TFT_MISO 12
#define TFT_MOSI 13
#define TFT_SCLK 14
#define TFT_CS   15
#define TFT_DC    2
#define TFT_RST  -1
#define TFT_BL   21
#define TFT_BACKLIGHT_ON HIGH
#define SPI_FREQUENCY 40000000
#define SPI_READ_FREQUENCY 20000000

// Dashboard labels use TFT_eSPI's built-in fonts 1 and 2.
#define LOAD_GLCD
#define LOAD_FONT2
#define LOAD_FONT4
