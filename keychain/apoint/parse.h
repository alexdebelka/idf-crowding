// Place file (place.v2 JSON, as published under /data/places/<id>.json) -> PlaceData.
// Header-only template so the same code reads an HTTP stream on the device and a file on a
// computer (gen/host_render.cpp).
#pragma once
#include <ArduinoJson.h>
#include <string.h>

#include "model.h"

static inline Rgb parseHex(const char *s, Rgb dflt) {
  if (!s || s[0] != '#' || strlen(s) != 7) return dflt;
  uint32_t v = 0;
  for (int i = 1; i < 7; i++) {
    char ch = s[i];
    v = v * 16 + (ch >= '0' && ch <= '9' ? ch - '0' : ch >= 'a' && ch <= 'f' ? ch - 'a' + 10
                                                  : ch >= 'A' && ch <= 'F' ? ch - 'A' + 10 : 0);
  }
  return rgb(v);
}

static inline uint8_t kindOf(const char *k) {
  if (!k) return KIND_TRAIN;
  if (!strcmp(k, "metro")) return KIND_METRO;
  if (!strcmp(k, "rer")) return KIND_RER;
  if (!strcmp(k, "tram")) return KIND_TRAM;
  return KIND_TRAIN;
}

static inline uint16_t clampScore(float s) {
  if (s < 0) return 0;
  if (s > 65000) return 65000;
  return (uint16_t)(s + 0.5f);
}

// Returns an empty string on success, else a short reason.
template <typename Input>
const char *parsePlace(Input &in, PlaceData &out) {
  JsonDocument filter;
  filter["schema_version"] = true;
  filter["place"]["id"] = true;
  filter["place"]["name"] = true;
  filter["place"]["lines"][0]["id"] = true;
  filter["place"]["lines"][0]["name"] = true;
  filter["place"]["lines"][0]["kind"] = true;
  filter["place"]["lines"][0]["color"] = true;
  filter["place"]["lines"][0]["text_color"] = true;
  JsonObject dt = filter["day_types"].to<JsonObject>();
  const char *codes[DT_N] = {"JOHV", "JOVS", "SAHV", "SAVS", "DIJFP"};
  for (int i = 0; i < DT_N; i++) {
    dt[codes[i]]["hours"][0]["h"] = true;
    dt[codes[i]]["hours"][0]["score"] = true;
  }
  filter["forecast"]["issue_date"] = true;
  filter["forecast"]["dates"][0]["d"] = true;
  filter["forecast"]["dates"][0]["scores"] = true;

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, in, DeserializationOption::Filter(filter));
  if (err) return "json";
  JsonObject place = doc["place"];
  if (place.isNull() || !place["name"].is<const char *>()) return "no place";

  memset(&out, 0, sizeof out);
  out.magic = PLACE_MAGIC;
  strncpy(out.id, place["id"] | "", sizeof out.id - 1);
  strncpy(out.name, place["name"] | "", sizeof out.name - 1);
  for (JsonObject l : place["lines"].as<JsonArray>()) {
    if (out.nlines >= MAX_LINES) break;
    // A line can be listed once per operator (e.g. RER B): keep one badge per name and kind.
    const char *nm = l["name"] | "?";
    uint8_t kind = kindOf(l["kind"]);
    int found = -1;
    for (int i = 0; i < out.nlines; i++)
      if (out.lines[i].kind == kind && !strcmp(out.lines[i].name, nm)) found = i;
    const char *lid = l["id"] | "";
    if (lid[0] && out.nids < MAX_LINE_IDS) {
      strncpy(out.lineId[out.nids], lid, sizeof out.lineId[0] - 1);
      out.lineIdBadge[out.nids++] = (uint8_t)(found >= 0 ? found : out.nlines);
    }
    if (found >= 0) continue;
    LineInfo &li = out.lines[out.nlines++];
    strncpy(li.name, l["name"] | "?", sizeof li.name - 1);
    li.kind = kindOf(l["kind"]);
    li.color = parseHex(l["color"], rgb(0x8E97A6));
    li.text = parseHex(l["text_color"], rgb(0xFFFFFF));
  }
  for (int i = 0; i < DT_N; i++) {
    JsonArray hours = doc["day_types"][codes[i]]["hours"];
    if (hours.isNull() || hours.size() != 24) continue;
    for (JsonObject h : hours) {
      int hh = h["h"] | -1;
      if (hh < 0 || hh > 23) continue;
      out.typical[i][(hh + 20) % 24] = clampScore(h["score"] | 0.f);
    }
    out.typicalMask |= 1 << i;
  }
  strncpy(out.issue, doc["forecast"]["issue_date"] | "", sizeof out.issue - 1);
  for (JsonObject d : doc["forecast"]["dates"].as<JsonArray>()) {
    if (out.ndates >= MAX_DATES) break;
    JsonArray s = d["scores"];
    int32_t day = dayFromIso(d["d"] | "");
    if (day < 0 || s.size() != 24) continue;
    out.day[out.ndates] = (uint16_t)day;
    for (int k = 0; k < 24; k++) out.scores[out.ndates][k] = clampScore(s[k] | 0.f);
    out.ndates++;
  }
  if (!out.typicalMask && !out.ndates) return "no scores";
  return "";
}
