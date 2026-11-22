// Keychain settings. Nothing private here: the Wi-Fi network and the favourite stations are
// entered on the device (setup mode) and kept in its flash.
#pragma once

// LilyGO T-Display-S3 (pin_config.h of the LilyGO examples)
#define PIN_POWER_ON 15
#define PIN_LCD_BL 38
#define PIN_LCD_RES 5
#define PIN_LCD_CS 6
#define PIN_LCD_DC 7
#define PIN_LCD_WR 8
#define PIN_LCD_RD 9
#define PIN_LCD_D0 39
#define PIN_LCD_D1 40
#define PIN_LCD_D2 41
#define PIN_LCD_D3 42
#define PIN_LCD_D4 45
#define PIN_LCD_D5 46
#define PIN_LCD_D6 47
#define PIN_LCD_D7 48
#define PIN_BUTTON_1 0   // BOOT: next station
#define PIN_BUTTON_2 14  // KEY: today / tomorrow
#define PIN_BAT_VOLT 4

// Screen rotation for landscape (1 or 3). Change to 3 if the picture is upside down for the
// way the keychain is held.
#define SCREEN_ROTATION 1

// Site serving the Place files (place.v2) and the next departures (/api/next/<id>, ADR 0004).
#define SITE_HOST "quaicalme.com"
#define PLACE_PATH "/data/places/"
#define NEXT_PATH "/api/next/"

// Behaviour (README.md, "Controls")
#define SLEEP_AFTER_MS 20000UL     // no press for this long: deep sleep
#define HOLD_CLOSE_MS 3000UL       // hold one button: closing animation, then off
#define HOLD_SETUP_MS 3000UL       // hold both buttons: setup mode
#define UNLOCK_PRESSES 3           // presses in a row to unlock after sleep
#define UNLOCK_GAP_MS 1500UL       // longest pause between those presses
#define SETUP_TIMEOUT_MS 600000UL  // setup mode closes itself after 10 min
#define DATA_MAX_AGE_S (30UL * 3600UL)  // refresh the Place files when older than this
#define SYNC_HOUR 4                // nightly refresh, Paris time (after the 04 h day change)
#define SYNC_MINUTE 30
#define WIFI_TIMEOUT_MS 12000UL

// Next departures: double press on button 2 (a single press then waits this long for a second
// one). Set ARRIVALS_ENABLED to 0 to make button 2 act at once and drop the screen.
#define ARRIVALS_ENABLED 1
#define DOUBLE_PRESS_MS 300UL
#define ARRIVALS_REFRESH_MS 30000UL  // same as the site's edge cache

// Paris time zone, POSIX form (daylight saving from the last Sunday of March to the last
// Sunday of October).
#define TZ_PARIS "CET-1CEST,M3.5.0,M10.5.0/3"

// Setup mode access point
#define AP_SSID_PREFIX "\xC3\xA0 point-"  // "à point-" + 4 hex digits of the chip id
#define AP_IP "192.168.4.1"
