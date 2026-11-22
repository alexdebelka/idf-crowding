// The keychain screens, drawn into a Canvas. Layout and colours follow the approved mockups
// of the à point keychain: Signal / Nuit "now" screens, Papier "tomorrow",
// locked quick view, setup, closing. Portable: also built on a computer by gen/host_render.cpp.
#pragma once
#include <stdint.h>

#include "gfx.h"
#include "model.h"

struct StationView {
  const PlaceData *place;  // null: nothing stored for this station yet
  const char *fallbackName;  // shown when place is null
  int32_t today;           // operating day (before 04 h = the previous calendar day)
  int hour;                // Paris clock hour
  bool tomorrow;
  bool locked;
  uint8_t lockDots;  // presses counted towards the unlock (0-3)
};

void drawStation(Canvas &c, const StationView &v);

// Thin bar across the top while a button is held (0-1).
void drawHoldBar(Canvas &c, float progress, bool onNight);

// Closing animation frame, t in seconds from the end of the hold. Returns false once finished.
bool drawClose(Canvas &c, float t);

struct SetupView {
  const char *ssid;
  const char *pass;
  const char *ip;
  const char *wifiLine;  // e.g. "Wi-Fi : Freebox-2A41 (ok)"
  int favourites;        // ids received
  int qrSize;            // modules per side, 0 = no QR
  bool (*qrModule)(int x, int y);
};
void drawSetup(Canvas &c, const SetupView &v);

// Papier screen with a two-line headline and up to two lines of small text.
void drawMessage(Canvas &c, const char *title, const char *line1, const char *line2,
                 const char *small1, const char *small2);
