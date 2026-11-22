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

static volatile bool running = false, finished = false;

static void task(void *) {
  if (connect(WIFI_TIMEOUT_MS)) {
    syncClock(6000);
    syncPlaces(nullptr);
  }
  disconnect();
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
