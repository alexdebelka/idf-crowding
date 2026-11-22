#include "model.h"

#include <string.h>

int32_t dayFromIso(const char *s) {
  if (!s || strlen(s) < 10 || s[4] != '-' || s[7] != '-') return -1;
  int y = 0, m = 0, d = 0;
  for (int i = 0; i < 4; i++) y = y * 10 + (s[i] - '0');
  m = (s[5] - '0') * 10 + (s[6] - '0');
  d = (s[8] - '0') * 10 + (s[9] - '0');
  if (m < 1 || m > 12 || d < 1 || d > 31) return -1;
  // Howard Hinnant's days_from_civil
  y -= m <= 2;
  int era = (y >= 0 ? y : y - 399) / 400;
  int yoe = y - era * 400;
  int doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  int doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + doe - 719468;
}

int dayTypeIndex(const char *code) {
  static const char *codes[DT_N] = {"JOHV", "JOVS", "SAHV", "SAVS", "DIJFP"};
  for (int i = 0; i < DT_N; i++)
    if (strcmp(code, codes[i]) == 0) return i;
  return -1;
}

bool scoresFor(const PlaceData &p, int32_t day, uint16_t out[24], bool *forecast) {
  for (uint16_t i = 0; i < p.ndates; i++)
    if (p.day[i] == day) {
      memcpy(out, p.scores[i], sizeof(uint16_t) * 24);
      if (forecast) *forecast = true;
      return true;
    }
  if (forecast) *forecast = false;
  // app/src/lib/time.ts defaultDayType: Sunday DIJFP, Saturday SAHV, else JOHV
  int wd = (int)((day + 4) % 7);  // 0 = Sunday
  int wanted = wd == 0 ? DT_DIJFP : (wd == 6 ? DT_SAHV : DT_JOHV);
  const int order[6] = {wanted, DT_JOHV, DT_JOVS, DT_SAHV, DT_SAVS, DT_DIJFP};
  for (int k = 0; k < 6; k++)
    if (p.typicalMask & (1 << order[k])) {
      memcpy(out, p.typical[order[k]], sizeof(uint16_t) * 24);
      return true;
    }
  return false;
}

const LineInfo *lineById(const PlaceData &p, const char *id) {
  for (int i = 0; i < p.nids && i < MAX_LINE_IDS; i++)
    if (!strcmp(p.lineId[i], id) && p.lineIdBadge[i] < p.nlines) return &p.lines[p.lineIdBadge[i]];
  return nullptr;
}
