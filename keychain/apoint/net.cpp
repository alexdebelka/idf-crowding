#include "net.h"

#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <time.h>

#include "certs.h"
#include "config.h"
#include "parse.h"
#include "store.h"

namespace net {

bool connect(uint32_t timeoutMs) {
  String ssid = store::wifiSsid();
  if (!ssid.length()) return false;
  if (WiFi.status() == WL_CONNECTED) return true;
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid.c_str(), store::wifiPass().c_str());
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < timeoutMs) delay(100);
  return WiFi.status() == WL_CONNECTED;
}

void disconnect() {
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
}

bool clockValid() {
  time_t now = time(nullptr);
  struct tm tm;
  localtime_r(&now, &tm);
  return tm.tm_year + 1900 >= 2025;
}

bool syncClock(uint32_t timeoutMs) {
  configTzTime(TZ_PARIS, "time.cloudflare.com", "pool.ntp.org");
  uint32_t t0 = millis();
  struct tm tm;
  while (millis() - t0 < timeoutMs) {
    if (getLocalTime(&tm, 200) && tm.tm_year + 1900 >= 2025) return true;
  }
  return false;
}

static bool fetchPlace(const String &id, PlaceData &out) {
  WiFiClientSecure client;
  client.setCACert(ROOT_CAS);
  client.setTimeout(15);
  HTTPClient http;
  http.useHTTP10(true);  // no chunked encoding: the JSON parser reads the body as it comes
  http.setTimeout(15000);
  String path = String(PLACE_PATH) + id + ".json";
  if (!http.begin(client, SITE_HOST, 443, path, true)) return false;
  http.addHeader("Accept", "application/json");
  int code = http.GET();
  if (code != 200) {
    Serial.printf("fetch %s: HTTP %d\n", id.c_str(), code);
    http.end();
    return false;
  }
  const char *err = parsePlace(http.getStream(), out);
  http.end();
  if (err[0]) {
    Serial.printf("fetch %s: %s\n", id.c_str(), err);
    return false;
  }
  out.fetched = (uint32_t)time(nullptr);
  return true;
}

int syncPlaces(int *total) {
  String ids[MAX_FAVS];
  int n = store::favourites(ids);
  if (total) *total = n;
  PlaceData *p = (PlaceData *)ps_malloc(sizeof(PlaceData));
  if (!p) p = (PlaceData *)malloc(sizeof(PlaceData));
  if (!p) return 0;
  int ok = 0;
  for (int i = 0; i < n; i++) {
    if (fetchPlace(ids[i], *p) && store::savePlace(*p)) ok++;
  }
  free(p);
  if (ok == n) store::removeOthers(ids, n);
  Serial.printf("sync: %d / %d Place files\n", ok, n);
  return ok;
}

// ---- Next departures ----

static Departures depShared;  // last answer, read by the main loop through departuresSnapshot()
static portMUX_TYPE depMux = portMUX_INITIALIZER_UNLOCKED;
static volatile bool depRunning = false, depFinished = false, depKeepWifi = false;
static String depId;
static volatile bool running = false, finished = false;

static uint8_t fetchDepartures(const String &id, Departures &out) {
  WiFiClientSecure client;
  client.setCACert(ROOT_CAS);
  client.setTimeout(10);
  HTTPClient http;
  http.useHTTP10(true);
  http.setTimeout(10000);
  String path = String(NEXT_PATH) + id;
  if (!http.begin(client, SITE_HOST, 443, path, true)) return out.status = DEP_ERROR;
  http.addHeader("Accept", "application/json");
  int code = http.GET();
  if (code != 200) {
    Serial.printf("departures %s: HTTP %d\n", id.c_str(), code);
    http.end();
    memset(&out, 0, sizeof out);
    return out.status = DEP_ERROR;
  }
  uint8_t st = parseDepartures(http.getStream(), out);
  http.end();
  Serial.printf("departures %s: status %d, %d rows\n", id.c_str(), st, out.n);
  return st;
}

static void depTask(void *) {
  static Departures d;
  while (running) delay(50);  // let a running sync finish first (they share the Wi-Fi)
  memset(&d, 0, sizeof d);
  if (!connect(WIFI_TIMEOUT_MS)) {
    d.status = DEP_NO_WIFI;
  } else {
    if (!clockValid()) syncClock(4000);
    fetchDepartures(depId, d);
  }
  if (!depKeepWifi) disconnect();
  portENTER_CRITICAL(&depMux);
  memcpy(&depShared, &d, sizeof d);
  portEXIT_CRITICAL(&depMux);
  depRunning = false;
  depFinished = true;
  vTaskDelete(nullptr);
}

void startDepartures(const String &placeId, bool keepWifi) {
  if (depRunning) return;
  depId = placeId;
  depKeepWifi = keepWifi;
  depRunning = true;
  depFinished = false;
  xTaskCreatePinnedToCore(depTask, "next", 12288, nullptr, 1, nullptr, 0);
}

bool departuresRunning() { return depRunning; }

bool departuresFinished() {
  if (!depFinished) return false;
  depFinished = false;
  return true;
}

Departures departuresSnapshot() {
  Departures d;
  portENTER_CRITICAL(&depMux);
  memcpy(&d, &depShared, sizeof d);
  portEXIT_CRITICAL(&depMux);
  return d;
}

void releaseDeparturesWifi() {
  depKeepWifi = false;
  if (!depRunning && !running) disconnect();
}


static void task(void *) {
  if (connect(WIFI_TIMEOUT_MS)) {
    syncClock(6000);
    syncPlaces(nullptr);
  }
  if (!depKeepWifi && !depRunning) disconnect();  // a departures request waiting keeps it
  running = false;
  finished = true;
  vTaskDelete(nullptr);
}

void startBackgroundSync() {
  if (running) return;
  running = true;
  finished = false;
  xTaskCreatePinnedToCore(task, "sync", 12288, nullptr, 1, nullptr, 0);
}

bool syncRunning() { return running; }

bool syncFinished() {
  if (!finished) return false;
  finished = false;
  return true;
}

}  // namespace net
