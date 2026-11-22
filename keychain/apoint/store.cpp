#include "store.h"

#include <FFat.h>
#include <Preferences.h>
#include <esp_random.h>

namespace store {

static Preferences prefs;

void begin() {
  prefs.begin("apoint", false);
  if (!FFat.begin(true)) Serial.println("FFat: mount failed");
  FFat.mkdir("/p");
}

String wifiSsid() { return prefs.getString("ssid", ""); }
String wifiPass() { return prefs.getString("pass", ""); }
void setWifi(const String &ssid, const String &pass) {
  prefs.putString("ssid", ssid);
  prefs.putString("pass", pass);
}

static bool validId(const String &id) {
  if (id.length() < 1 || id.length() > 15) return false;
  for (size_t i = 0; i < id.length(); i++) {
    char c = id[i];
    if (!isalnum((unsigned char)c) && c != '_' && c != '-') return false;
  }
  return true;
}

static int split(const String &csv, String out[MAX_FAVS]) {
  int n = 0, start = 0;
  while (start <= (int)csv.length() && n < MAX_FAVS) {
    int comma = csv.indexOf(',', start);
    if (comma < 0) comma = csv.length();
    String id = csv.substring(start, comma);
    id.trim();
    bool seen = false;
    for (int i = 0; i < n; i++) seen |= out[i] == id;
    if (validId(id) && !seen) out[n++] = id;
    start = comma + 1;
  }
  return n;
}

int favourites(String out[MAX_FAVS]) { return split(prefs.getString("favs", ""), out); }

int setFavourites(const String &csv) {
  String ids[MAX_FAVS];
  int n = split(csv, ids);
  if (!n) return 0;
  String joined;
  for (int i = 0; i < n; i++) joined += (i ? "," : "") + ids[i];
  prefs.putString("favs", joined);
  prefs.putUChar("idx", 0);
  return n;
}

uint8_t screenIndex() { return prefs.getUChar("idx", 0); }
bool screenTomorrow() { return prefs.getBool("tmr", false); }
void setScreen(uint8_t index, bool tomorrow) {
  if (prefs.getUChar("idx", 255) != index) prefs.putUChar("idx", index);
  if (prefs.getBool("tmr", !tomorrow) != tomorrow) prefs.putBool("tmr", tomorrow);
}

String apPassword() {
  String p = prefs.getString("appass", "");
  if (p.length() != 8) {
    char buf[9];
    for (int i = 0; i < 8; i++) buf[i] = '0' + esp_random() % 10;
    buf[8] = 0;
    p = buf;
    prefs.putString("appass", p);
  }
  return p;
}

bool skipIntroOnce() {
  bool v = prefs.getBool("skipintro", false);
  if (v) prefs.putBool("skipintro", false);
  return v;
}
void setSkipIntroOnce() { prefs.putBool("skipintro", true); }

static String pathOf(const String &id) { return "/p/" + id + ".bin"; }

bool loadPlace(const String &id, PlaceData &out) {
  File f = FFat.open(pathOf(id), "r");
  if (!f) return false;
  size_t n = f.read((uint8_t *)&out, sizeof out);
  f.close();
  return n == sizeof out && out.magic == PLACE_MAGIC;
}

bool savePlace(const PlaceData &p) {
  String tmp = "/p/" + String(p.id) + ".tmp";
  File f = FFat.open(tmp, "w");
  if (!f) return false;
  size_t n = f.write((const uint8_t *)&p, sizeof p);
  f.close();
  if (n != sizeof p) return false;
  FFat.remove(pathOf(p.id));
  return FFat.rename(tmp, pathOf(p.id));
}

uint32_t oldestAge(uint32_t now) {
  String ids[MAX_FAVS];
  int n = favourites(ids);
  uint32_t oldest = 0;
  static PlaceData p;
  for (int i = 0; i < n; i++) {
    if (!loadPlace(ids[i], p)) return UINT32_MAX;
    uint32_t age = now > p.fetched ? now - p.fetched : 0;
    if (age > oldest) oldest = age;
  }
  return oldest;
}

void removeOthers(const String ids[], int n) {
  File dir = FFat.open("/p");
  if (!dir) return;
  String gone[32];
  int g = 0;
  for (File f = dir.openNextFile(); f && g < 32; f = dir.openNextFile()) {
    String name = f.name();
    int slash = name.lastIndexOf('/');
    if (slash >= 0) name = name.substring(slash + 1);
    bool keep = false;
    for (int i = 0; i < n; i++) keep |= name == ids[i] + ".bin";
    if (!keep) gone[g++] = "/p/" + name;
  }
  dir.close();
  for (int i = 0; i < g; i++) FFat.remove(gone[i]);
}

}  // namespace store
