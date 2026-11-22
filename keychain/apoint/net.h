// Wi-Fi, clock and download of the favourite Place files.
#pragma once
#include <Arduino.h>

namespace net {

// Joins the saved network (station mode). False when none is saved or it does not answer.
bool connect(uint32_t timeoutMs);
void disconnect();

// Sets the clock from NTP (Paris time zone). False when no answer in time.
bool syncClock(uint32_t timeoutMs);
bool clockValid();

// Downloads every favourite Place file and stores it. Returns how many succeeded; `total` gets
// the number of favourites.
int syncPlaces(int *total);

// Runs connect + clock + places on the other core. Poll `syncDone()`.
void startBackgroundSync();
bool syncRunning();
bool syncFinished();  // true once after a background sync ends
}  // namespace net
