// Wi-Fi, clock and download of the favourite Place files.
#pragma once
#include <Arduino.h>

#include "departures.h"

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

// Next departures of one Place (/api/next/<id>) on the other core: joins the Wi-Fi when needed
// (after a running sync has finished), asks the site, and keeps the Wi-Fi on while `keepWifi`
// so the next refresh is quick. Poll departuresFinished(), then read departuresSnapshot().
void startDepartures(const String &placeId, bool keepWifi);
bool departuresRunning();
bool departuresFinished();  // true once after a request ends
Departures departuresSnapshot();
// Leaving the departures screen: the Wi-Fi goes off now, or when the running request ends.
void releaseDeparturesWifi();
}  // namespace net
