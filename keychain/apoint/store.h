// What the keychain keeps between sleeps and power cuts: Wi-Fi, favourite stations, the last
// screen (NVS), and one PlaceData record per favourite (FAT partition of the board, /p/<id>.bin).
#pragma once
#include <Arduino.h>

#include "model.h"

namespace store {

void begin();

String wifiSsid();
String wifiPass();
void setWifi(const String &ssid, const String &pass);

// Favourite Place ids, in the order of the app. Returns the count.
int favourites(String out[MAX_FAVS]);
// Validates and saves a comma-separated list from the app; returns the count kept (0 = refused).
int setFavourites(const String &csv);

uint8_t screenIndex();
bool screenTomorrow();
void setScreen(uint8_t index, bool tomorrow);

// Password of the setup network, made once per device.
String apPassword();

bool skipIntroOnce();  // true once after setup mode restarts the device
void setSkipIntroOnce();

bool loadPlace(const String &id, PlaceData &out);
bool savePlace(const PlaceData &p);
// Seconds since the oldest favourite file was fetched (or a large value when one is missing).
uint32_t oldestAge(uint32_t nowUnix);
void removeOthers(const String ids[], int n);

}  // namespace store
