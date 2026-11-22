// What the keychain keeps of a Place file (place.v2 from the site): name, lines, the typical
// week and the dated forecast scores. Stored as one binary record per Place in the flash file system (FFat).
#pragma once
#include <stdint.h>

#include "gfx.h"

#define MAX_LINES 12
#define MAX_DATES 100
#define MAX_FAVS 12
#define MAX_LINE_IDS 16
#define PLACE_MAGIC 0x41505432u  // "APT2" (APT1 had no line ids: such files are fetched again)

enum LineKind : uint8_t { KIND_METRO, KIND_RER, KIND_TRAM, KIND_TRAIN };
enum DayType : uint8_t { DT_JOHV, DT_JOVS, DT_SAHV, DT_SAVS, DT_DIJFP, DT_N };

struct LineInfo {
  char name[5];
  uint8_t kind;
  Rgb color, text;
};

struct PlaceData {
  uint32_t magic;
  char id[16];
  char name[80];  // UTF-8
  uint8_t nlines;
  LineInfo lines[MAX_LINES];
  // Line ids of the Place file (e.g. "C01374") and the badge each one is drawn with: the real-time
  // departures name lines by id, and one badge can stand for two ids (RER B, one per operator).
  uint8_t nids;
  char lineId[MAX_LINE_IDS][12];
  uint8_t lineIdBadge[MAX_LINE_IDS];
  uint8_t typicalMask;  // bit per DayType present
  uint16_t typical[DT_N][24];
  uint16_t ndates;
  uint16_t day[MAX_DATES];  // days since 1970-01-01
  uint16_t scores[MAX_DATES][24];
  uint32_t fetched;  // unix time of the download
  char issue[11];    // forecast issue date, YYYY-MM-DD
};

// Day number (days since 1970-01-01) of a YYYY-MM-DD string; -1 when malformed.
int32_t dayFromIso(const char *s);
// Scores of one operating day: its forecast when the Place has one, else the typical week of
// its day type (same fallbacks as the app). Returns false when the Place has neither.
bool scoresFor(const PlaceData &p, int32_t day, uint16_t out[24], bool *forecast = nullptr);
int dayTypeIndex(const char *code);
// Badge of a line id of the Place, or null.
const LineInfo *lineById(const PlaceData &p, const char *id);
