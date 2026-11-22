// à point — keychain display (LilyGO T-Display-S3, 320 x 170 landscape): setup() and loop().
// Crowding forecast of the favourite stations, from the Place files of the site.
// Controls and setup: README.md.
//
// Controls
//   Button 1 (BOOT): next station.        Button 2 (KEY): today / tomorrow.
//   Hold one button 3 s: closing animation, then off (any press turns it on, with the intro).
//   Hold both buttons 3 s: setup mode (Wi-Fi and favourite stations from the phone).
//   No press for 20 s: sleep. After sleep the keychain is locked: the last screen shows,
//   three presses in a row unlock it.
#include <Arduino.h>
#include <Arduino_GFX_Library.h>
#include <WiFi.h>
#include <driver/gpio.h>
#include <driver/rtc_io.h>
#include <esp_sleep.h>
#include <time.h>

#include "aptqr.h"
#include "config.h"
#include "gfx.h"
#include "intro_play.h"
#include "model.h"
#include "net.h"
#include "portal.h"
#include "screens.h"
#include "store.h"

// ---- Display ----

// The bus each GFX Library version uses for this board in its own example: the LCD peripheral
// on core 3.x (GFX 1.5 and later), the fast GPIO bus on core 2.0.x (GFX 1.4.9).
#if ESP_ARDUINO_VERSION_MAJOR >= 3
static Arduino_DataBus *bus = new Arduino_ESP32LCD8(PIN_LCD_DC, PIN_LCD_CS, PIN_LCD_WR, PIN_LCD_RD, PIN_LCD_D0,
                                                    PIN_LCD_D1, PIN_LCD_D2, PIN_LCD_D3, PIN_LCD_D4, PIN_LCD_D5,
                                                    PIN_LCD_D6, PIN_LCD_D7);
#else
static Arduino_DataBus *bus = new Arduino_ESP32PAR8Q(PIN_LCD_DC, PIN_LCD_CS, PIN_LCD_WR, PIN_LCD_RD, PIN_LCD_D0,
                                                     PIN_LCD_D1, PIN_LCD_D2, PIN_LCD_D3, PIN_LCD_D4, PIN_LCD_D5,
                                                     PIN_LCD_D6, PIN_LCD_D7);
#endif
static Arduino_GFX *panel = new Arduino_ST7789(bus, PIN_LCD_RES, SCREEN_ROTATION, true /* IPS */, 170, 320, 35, 0, 35, 0);
static Canvas canvas;
static uint16_t *band565;   // panel-format copy of one band
static bool topIsNight = false;  // ground of the last screen shown (for the hold bar colour)

// Draws a screen band by band (the whole screen at once when PSRAM holds a full frame) and sends
// each band to the panel. `rowsToSend` limits what is sent (the hold bar only needs the top).
static void show(void (*draw)(), int rowsToSend = SCR_H) {
  for (int top = 0; top < rowsToSend; top += canvas.bandRows) {
    canvas.setBand(top);
    draw();
    if (top == 0) topIsNight = canvas.px[0] < 60 && canvas.px[1] < 60;
    int n = canvas.rows < rowsToSend - top ? canvas.rows : rowsToSend - top;
    canvas.toRgb565(band565);
    panel->draw16bitRGBBitmap(0, top, band565, SCR_W, n);
  }
}

static void backlight(bool on) { digitalWrite(PIN_LCD_BL, on ? HIGH : LOW); }

// ---- State kept across deep sleep ----

RTC_DATA_ATTR static bool rtcClosed = false;  // switched off by the user (not just asleep)
RTC_DATA_ATTR static bool rtcLocked = false;

enum Mode { MODE_STATION, MODE_SETUP };
static Mode mode = MODE_STATION;

static String favIds[MAX_FAVS];
static int favCount = 0;
static uint8_t favIndex = 0;
static bool tomorrow = false;
static bool locked = false;
static uint8_t lockDots = 0;
static uint32_t lastLockPress = 0;
static PlaceData *place = nullptr;  // current favourite, as stored
static bool placeLoaded = false;
static uint32_t lastInput = 0;
static int drawnHour = -1;

// ---- Clock ----

struct Now {
  bool valid;
  int32_t today;  // operating day: before 04 h it is still the previous day
  int hour;
};

static Now clockNow() {
  Now n{false, 0, 0};
  time_t t = time(nullptr);
  struct tm tm;
  localtime_r(&t, &tm);
  if (tm.tm_year + 1900 < 2025) return n;
  char iso[11];
  strftime(iso, sizeof iso, "%Y-%m-%d", &tm);
  n.valid = true;
  n.hour = tm.tm_hour;
  n.today = dayFromIso(iso) - (tm.tm_hour < 4 ? 1 : 0);
  return n;
}

// Seconds until the next nightly refresh (SYNC_HOUR:SYNC_MINUTE Paris time).
static uint32_t secondsToNightlySync() {
  time_t t = time(nullptr);
  struct tm tm;
  localtime_r(&t, &tm);
  int nowS = tm.tm_hour * 3600 + tm.tm_min * 60 + tm.tm_sec;
  int target = SYNC_HOUR * 3600 + SYNC_MINUTE * 60;
  int d = target - nowS;
  if (d <= 60) d += 24 * 3600;
  return (uint32_t)d;
}

// ---- Drawing ----

static void loadFavourites() {
  favCount = store::favourites(favIds);
  favIndex = store::screenIndex();
  if (favIndex >= favCount) favIndex = 0;
  tomorrow = store::screenTomorrow();
  placeLoaded = false;
}

static void ensurePlace() {
  if (placeLoaded || favCount == 0) return;
  placeLoaded = store::loadPlace(favIds[favIndex], *place);
}

static void paintStation() {
  Now n = clockNow();
  if (favCount == 0) {
    drawMessage(canvas, "\xC3\xA0 point", "Aucune gare", "enregistr\xC3\xA9" "e.", "Maintenez les deux boutons 3 s",
                "pour ouvrir les r\xC3\xA9glages.");
  } else if (!n.valid) {
    drawMessage(canvas, "\xC3\xA0 point", "Heure", "inconnue.",
                store::wifiSsid().length() ? "Connexion au Wi-Fi\xE2\x80\xA6" : "Aucun Wi-Fi enregistr\xC3\xA9.",
                "Maintenez les deux boutons 3 s pour les r\xC3\xA9glages.");
  } else {
    ensurePlace();
    StationView v{placeLoaded ? place : nullptr, favIds[favIndex].c_str(), n.today, n.hour, tomorrow, locked,
                  lockDots};
    drawStation(canvas, v);
  }
  drawnHour = n.valid ? n.hour : -1;
}

static void drawStationScreen() {
  ensurePlace();
  show(paintStation);
}

// ---- Setup screen ----

static uint8_t qr[aptqr_BUFFER_LEN_FOR_VERSION(6)], qrTemp[aptqr_BUFFER_LEN_FOR_VERSION(6)];
static bool qrModule(int x, int y) { return aptqr_getModule(qr, x, y); }

static SetupView setupView;
static String setupSsid, setupPass, setupLine;

static void paintSetup() { drawSetup(canvas, setupView); }

static void drawSetupScreen() {
  setupSsid = portal::ssid();
  setupPass = portal::password();
  String q = portal::qrText();
  bool qrOk = aptqr_encodeText(q.c_str(), qrTemp, qr, aptqr_Ecc_LOW, 1, 6, aptqr_Mask_AUTO, true);
  String w = store::wifiSsid();
  const char *st[] = {"", " (essai\xE2\x80\xA6)", " (ok)", " (\xC3\xA9" "chec)"};
  setupLine = w.length() ? "Wi-Fi : " + w + st[portal::wifiStatus()] : String("Wi-Fi : \xC3\xA0 choisir");
  setupView = SetupView{setupSsid.c_str(), setupPass.c_str(), AP_IP, setupLine.c_str(),
                        portal::favouritesReceived(), qrOk ? aptqr_getSize(qr) : 0, qrModule};
  show(paintSetup);
}

static uint32_t setupStart = 0;

static void enterSetup() {
  mode = MODE_SETUP;
  setupStart = millis();
  portal::begin();
  drawSetupScreen();
}

static void leaveSetup() {
  portal::end();
  store::setSkipIntroOnce();
  ESP.restart();  // starts clean in station mode and downloads the stations
}

// ---- Animations ----

// The intro: stand-alone RLE frames (gen/intro_enc.py), each decoded band by band into the same
// buffer as the screens and sent to the panel in full rows.
static void playIntro() {
  uint32_t t0 = millis();
  for (int f = 0; f < INTRO_FRAMES; f++) {
    introDecode(f, band565, canvas.bandRows,
                [](int top, int rows) { panel->draw16bitRGBBitmap(0, top, band565, SCR_W, rows); });
    if (f == 0) backlight(true);
    uint32_t due = t0 + (uint32_t)(f + 1) * 1000 / INTRO_FPS;
    while ((int32_t)(due - millis()) > 0) delay(1);
  }
  delay(350);
}

static void goToSleep(bool closed);

static float closeT = 0;
static bool closeRunning = true;
static void paintClose() { closeRunning = drawClose(canvas, closeT); }
static void paintDark() { canvas.fill(rgb(0x0E1116)); }

static void playClose() {
  uint32_t t0 = millis();
  while (closeRunning) {
    closeT = (millis() - t0) / 1000.f;
    show(paintClose);
  }
  show(paintDark);
  goToSleep(true);
}

// ---- Sleep ----

static void goToSleep(bool closed) {
  rtcClosed = closed;
  rtcLocked = !closed;  // asleep: locked on wake; switched off: plain start with the intro
  store::setScreen(favIndex, tomorrow);
  backlight(false);
  if (band565) panel->displayOff();
  digitalWrite(PIN_POWER_ON, LOW);
  net::disconnect();
  // Keep the backlight and the screen power off while asleep (pads keep their level).
  gpio_hold_en((gpio_num_t)PIN_LCD_BL);
  gpio_hold_en((gpio_num_t)PIN_POWER_ON);
  gpio_deep_sleep_hold_en();

  // Wake on either button (both active low, pulled up by the RTC domain during sleep).
  rtc_gpio_pullup_en((gpio_num_t)PIN_BUTTON_2);
  rtc_gpio_pulldown_dis((gpio_num_t)PIN_BUTTON_2);
  rtc_gpio_pullup_en((gpio_num_t)PIN_BUTTON_1);
  rtc_gpio_pulldown_dis((gpio_num_t)PIN_BUTTON_1);
  esp_sleep_pd_config(ESP_PD_DOMAIN_RTC_PERIPH, ESP_PD_OPTION_ON);
  esp_sleep_enable_ext1_wakeup((1ULL << PIN_BUTTON_1) | (1ULL << PIN_BUTTON_2), ESP_EXT1_WAKEUP_ANY_LOW);
  // Nightly refresh of the forecasts, screen off.
  if (store::wifiSsid().length() && favCount > 0 && clockNow().valid)
    esp_sleep_enable_timer_wakeup((uint64_t)secondsToNightlySync() * 1000000ULL);
  Serial.flush();
  esp_deep_sleep_start();
}

// ---- Buttons ----

struct Btn {
  uint8_t pin;
  bool down;
  bool ignore;  // the press that woke the device, until released
  uint32_t since;
};
static Btn b1{PIN_BUTTON_1, false, false, 0}, b2{PIN_BUTTON_2, false, false, 0};
static bool holdShown = false, bothHeld = false;
static uint32_t pending2 = 0;  // first press of a possible double press on button 2

static void redraw() {
  if (mode == MODE_SETUP)
    drawSetupScreen();
  else
    drawStationScreen();
}

static float holdProgress = 0;
static bool holdNight = false;
static void paintHold() {
  if (mode == MODE_SETUP)
    paintSetup();
  else
    paintStation();
  drawHoldBar(canvas, holdProgress, holdNight);
}

static void lockPress() {
  uint32_t now = millis();
  if (now - lastLockPress > UNLOCK_GAP_MS) lockDots = 0;
  lastLockPress = now;
  lockDots++;
  if (lockDots >= UNLOCK_PRESSES) {
    locked = false;
    rtcLocked = false;
    lockDots = 0;
  }
  redraw();
}

static void click(uint8_t which) {
  lastInput = millis();
  if (mode == MODE_SETUP) {
    if (store::wifiSsid().length()) leaveSetup();
    return;
  }
  if (locked) {
    lockPress();
    return;
  }
  if (which == 1) {
    if (favCount > 1) {
      favIndex = (favIndex + 1) % favCount;
      placeLoaded = false;
    }
  } else {
    tomorrow = !tomorrow;
  }
  store::setScreen(favIndex, tomorrow);
  redraw();
}

static void pollButtons() {
  uint32_t now = millis();
  Btn *bs[2] = {&b1, &b2};
  for (int i = 0; i < 2; i++) {
    Btn &b = *bs[i];
    bool d = digitalRead(b.pin) == LOW;
    if (d && !b.down) {
      b.down = true;
      b.since = now;
      lastInput = now;
    } else if (!d && b.down) {
      b.down = false;
      lastInput = now;
      uint32_t held = now - b.since;
      if (b.ignore) {
        b.ignore = false;
      } else if (bothHeld) {
        // released after a two-button hold: nothing more
      } else if (held < 600) {
        if (i == 1 && ARRIVALS_ENABLED && mode == MODE_STATION && !locked) {
          if (pending2 && now - pending2 < DOUBLE_PRESS_MS) {
            pending2 = 0;
            // next arrivals: next step (ADR 0004 route /api/next/<id>)
          } else {
            pending2 = now;
          }
        } else {
          click(i + 1);
        }
      }
      if (holdShown) {
        holdShown = false;
        redraw();
      }
      if (!b1.down && !b2.down) bothHeld = false;
    }
  }
  if (pending2 && now - pending2 >= DOUBLE_PRESS_MS) {
    pending2 = 0;
    click(2);
  }

  // Two-button hold: setup mode.
  if (b1.down && b2.down && !b1.ignore && !b2.ignore) {
    bothHeld = true;
    uint32_t held = now - (b1.since > b2.since ? b1.since : b2.since);
    if (held >= HOLD_SETUP_MS && mode == MODE_STATION) {
      holdShown = false;
      enterSetup();
    }
    return;
  }
  // One-button hold: closing.
  for (int i = 0; i < 2; i++) {
    Btn &b = *bs[i];
    if (!b.down || b.ignore || bothHeld) continue;
    uint32_t held = now - b.since;
    if (held >= HOLD_CLOSE_MS) {
      if (mode == MODE_SETUP) portal::end();
      playClose();  // does not return
    }
    if (held > 250) {
      static uint32_t lastBar = 0;
      if (!holdShown) {
        holdNight = mode == MODE_STATION && topIsNight;
        holdShown = true;
      }
      if (now - lastBar > 40) {
        lastBar = now;
        holdProgress = (float)held / HOLD_CLOSE_MS;
        show(paintHold, 4);  // only the bar's rows change
      }
    }
  }
}

// ---- Nightly refresh (timer wake, screen off) ----

static void nightlySync() {
  digitalWrite(PIN_POWER_ON, LOW);  // screen stays off
  if (net::connect(WIFI_TIMEOUT_MS)) {
    net::syncClock(6000);
    net::syncPlaces(nullptr);
  }
  goToSleep(rtcClosed);
}

// ---- Arduino entry points ----

void setup() {
  Serial.begin(115200);
  delay(300);  // lets the USB serial port come up so the first lines are not lost
  // Release what goToSleep() held, and give the buttons back to the digital pins.
  gpio_deep_sleep_hold_dis();
  gpio_hold_dis((gpio_num_t)PIN_LCD_BL);
  gpio_hold_dis((gpio_num_t)PIN_POWER_ON);
  rtc_gpio_deinit((gpio_num_t)PIN_BUTTON_1);
  rtc_gpio_deinit((gpio_num_t)PIN_BUTTON_2);
  pinMode(PIN_POWER_ON, OUTPUT);
  digitalWrite(PIN_POWER_ON, HIGH);
  pinMode(PIN_LCD_BL, OUTPUT);
  backlight(false);
  pinMode(PIN_BUTTON_1, INPUT_PULLUP);
  pinMode(PIN_BUTTON_2, INPUT_PULLUP);
  setenv("TZ", TZ_PARIS, 1);
  tzset();
  store::begin();

  esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
  place = (PlaceData *)ps_malloc(sizeof(PlaceData));
  if (!place) place = (PlaceData *)malloc(sizeof(PlaceData));
  loadFavourites();

  if (cause == ESP_SLEEP_WAKEUP_TIMER) nightlySync();  // does not return

  panel->begin();
  panel->fillScreen(0x0000);
  Serial.printf("PSRAM: found %d, size %u, free %u; internal heap free %u\n", psramFound(),
                (unsigned)ESP.getPsramSize(), (unsigned)ESP.getFreePsram(), (unsigned)ESP.getFreeHeap());
  // With PSRAM the whole frame is drawn at once; without it, in bands of 34 rows (about 55 KB).
  int band = psramFound() ? SCR_H : 34;
  band565 = (uint16_t *)ps_malloc(SCR_W * band * 2);
  if (!band565) band565 = (uint16_t *)malloc(SCR_W * band * 2);
  if (!canvas.begin(band) || !band565) {
    Serial.println("Not enough memory for the screen buffers");
    panel->setTextColor(0xFFFF);
    panel->setCursor(10, 80);
    panel->printf("Memoire insuffisante (%u o libres)", (unsigned)ESP.getFreeHeap());
    backlight(true);
    for (;;) delay(1000);
  }

  bool fromSleep = cause == ESP_SLEEP_WAKEUP_EXT0 || cause == ESP_SLEEP_WAKEUP_EXT1;
  // The press that woke the device is not a click.
  b1.ignore = digitalRead(PIN_BUTTON_1) == LOW;
  b2.ignore = digitalRead(PIN_BUTTON_2) == LOW;
  b1.down = b1.ignore;
  b2.down = b2.ignore;
  b1.since = b2.since = millis();

  bool skipIntro = store::skipIntroOnce();
  if (fromSleep && !rtcClosed) {
    locked = rtcLocked;  // quick view of the last screen
  } else {
    locked = false;
    rtcLocked = false;
    rtcClosed = false;
    if (!skipIntro) playIntro();
  }

  bool haveWifi = store::wifiSsid().length() > 0;
  if (!haveWifi && favCount == 0 && !fromSleep) {
    backlight(true);
    enterSetup();
    lastInput = millis();
    return;
  }
  drawStationScreen();
  backlight(true);

  // Refresh in the background when the clock is unknown or the stored forecasts are old.
  Now n = clockNow();
  if (haveWifi && favCount > 0 && (!n.valid || store::oldestAge((uint32_t)time(nullptr)) > DATA_MAX_AGE_S))
    net::startBackgroundSync();
  lastInput = millis();
}

void loop() {
  pollButtons();
  uint32_t now = millis();
  if (mode == MODE_SETUP) {
    portal::loop();
    if (portal::changed()) drawSetupScreen();
    if (portal::doneRequested()) {
      delay(1500);  // lets the page reach the phone
      leaveSetup();
    }
    if (now - setupStart > SETUP_TIMEOUT_MS) {
      portal::end();
      goToSleep(false);
    }
    delay(2);
    return;
  }

  if (net::syncFinished()) {
    placeLoaded = false;
    if (!holdShown) redraw();
  }
  // New hour: the "now" bar moves.
  static uint32_t lastTick = 0;
  if (now - lastTick > 5000) {
    lastTick = now;
    Now n = clockNow();
    if (n.valid && n.hour != drawnHour && !holdShown) redraw();
  }
  if (now - lastInput > SLEEP_AFTER_MS && !b1.down && !b2.down && !pending2) {
    if (net::syncRunning()) {
      backlight(false);  // finish the download screen-off, then sleep
      uint32_t t0 = millis();
      while (net::syncRunning() && millis() - t0 < 60000) delay(50);
    }
    goToSleep(false);
  }
  delay(5);
}
