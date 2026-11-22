// Next departures at a Place, from the site's /api/next/<place id> (app/worker/index.ts,
// docs/adr/0004-next-departures-worker.md): { status, now, rows: [{ line, dest, times, atStop }] },
// rows already ordered by first departure. Header-only so the same code reads the HTTP stream on
// the device and a file on a computer (gen/host_render.cpp).
#pragma once
#include <ArduinoJson.h>
#include <stdint.h>
#include <string.h>

#include "model.h"

#define DEP_KEEP 8  // rows kept from an answer (more than shown, so the list can age)
#define DEP_SHOW 4  // rows on the screen (owner: next 4, all lines)
#define DEP_GRACE_S 30  // a departure this far in the past still shows (as in the app)

enum DepStatus : uint8_t { DEP_LOADING, DEP_OK, DEP_OFF, DEP_ERROR, DEP_NO_WIFI };

struct DepRow {
  char line[12];  // line id, e.g. "C01374"
  char dest[64];  // UTF-8
  int32_t in[2];  // seconds from the answer's `now` to each departure
  uint8_t ntimes;
  bool atStop;
};

struct Departures {
  uint8_t status;
  uint8_t n;
  DepRow rows[DEP_KEEP];
};

// Unix seconds of "YYYY-MM-DDTHH:MM:SS[.sss]Z"; -1 when malformed.
static inline int64_t isoToUnix(const char *s) {
  if (!s || strlen(s) < 19 || s[10] != 'T' || s[13] != ':' || s[16] != ':') return -1;
  int32_t day = dayFromIso(s);
  if (day < 0) return -1;
  int h = (s[11] - '0') * 10 + (s[12] - '0');
  int m = (s[14] - '0') * 10 + (s[15] - '0');
  int sec = (s[17] - '0') * 10 + (s[18] - '0');
  if (h > 23 || m > 59 || sec > 60) return -1;
  return (int64_t)day * 86400 + h * 3600 + m * 60 + sec;
}

// Fills `out` from an answer. Returns out.status.
template <typename Input>
uint8_t parseDepartures(Input &in, Departures &out) {
  memset(&out, 0, sizeof out);
  JsonDocument filter;
  filter["status"] = true;
  filter["now"] = true;
  filter["rows"][0]["line"] = true;
  filter["rows"][0]["dest"] = true;
  filter["rows"][0]["times"] = true;
  filter["rows"][0]["atStop"] = true;
  JsonDocument doc;
  if (deserializeJson(doc, in, DeserializationOption::Filter(filter))) return out.status = DEP_ERROR;
  const char *st = doc["status"] | "";
  if (!strcmp(st, "off") || !strcmp(st, "quota")) return out.status = DEP_OFF;
  int64_t now = isoToUnix(doc["now"] | "");
  if (strcmp(st, "ok") || now < 0) return out.status = DEP_ERROR;
  for (JsonObject r : doc["rows"].as<JsonArray>()) {
    if (out.n >= DEP_KEEP) break;
    DepRow &d = out.rows[out.n];
    memset(&d, 0, sizeof d);
    strncpy(d.line, r["line"] | "", sizeof d.line - 1);
    strncpy(d.dest, r["dest"] | "", sizeof d.dest - 1);
    for (JsonVariant t : r["times"].as<JsonArray>()) {
      if (d.ntimes >= 2) break;
      int64_t u = isoToUnix(t | "");
      if (u >= 0) d.in[d.ntimes++] = (int32_t)(u - now);
    }
    d.atStop = r["atStop"] | false;
    if (d.line[0] && d.dest[0] && d.ntimes) out.n++;
  }
  return out.status = DEP_OK;
}

// The rows still ahead `elapsed` seconds after the answer, at most DEP_SHOW, times shifted to
// "seconds from now". Rows whose line the Place does not list are left out (as in the app).
static inline int depVisible(const Departures &d, int32_t elapsed, const PlaceData *p, DepRow out[DEP_SHOW]) {
  DepRow all[DEP_KEEP];
  int n = 0;
  for (int i = 0; i < d.n && i < DEP_KEEP; i++) {
    const DepRow &r = d.rows[i];
    if (p && !lineById(*p, r.line)) continue;
    DepRow v = r;
    v.ntimes = 0;
    for (int k = 0; k < r.ntimes; k++)
      if (r.in[k] - elapsed >= -DEP_GRACE_S) v.in[v.ntimes++] = r.in[k] - elapsed;
    if (!v.ntimes) continue;
    v.atStop = r.atStop && v.ntimes == r.ntimes;
    all[n++] = v;
  }
  // Soonest first (a row whose first train has gone moves down).
  for (int i = 1; i < n; i++)
    for (int j = i; j > 0 && all[j].in[0] < all[j - 1].in[0]; j--) {
      DepRow t = all[j];
      all[j] = all[j - 1];
      all[j - 1] = t;
    }
  if (n > DEP_SHOW) n = DEP_SHOW;
  for (int i = 0; i < n; i++) out[i] = all[i];
  return n;
}
