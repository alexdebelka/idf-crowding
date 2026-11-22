#include "screens.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "src/fonts_data.h"
#include "logic.h"
#include "src/rabbit_data.h"

// Design tokens (docs/DESIGN_SPEC.md)
static const Rgb NUIT = rgb(0x0E1116), SIGNAL = rgb(0xD9F84A), PAPIER = rgb(0xF6F7F4);
static const Rgb MUTED_ON_NUIT = rgb(0xDADFE6);
static const Rgb LIME_TOP = rgb(0xF1FF8F), LIME_BOTTOM = rgb(0xA9C81F);

// Same thresholds as config.toml / index.json "bands" (40 / 70 / 100).
static const uint8_t EDGES[3] = {40, 70, 100};

enum Ground { G_NUIT, G_SIGNAL, G_PAPIER };

static void ground(Canvas &c, Ground g) {
  switch (g) {
    case G_NUIT:
      c.fill(NUIT);
      c.radial(24, 10, rgb(0x3A4558), 0.6f, 110);
      c.radial(272, 62, SIGNAL, 0.26f, 96);
      break;
    case G_SIGNAL:
      c.fill(SIGNAL);
      c.radial(10, 170, rgb(0xB4D22C), 0.9f, 130);
      c.radial(300, 0, rgb(0xF4FFB0), 0.95f, 120);
      break;
    case G_PAPIER:
      c.fill(PAPIER);
      c.radial(0, 170, rgb(0xC9D3E4), 0.8f, 110);
      c.radial(230, 130, SIGNAL, 0.5f, 120);
      break;
  }
}

// ---- Header: rabbit, station name, and on the right badges, a pill or the lock ----

static const int HEAD_TOP = 6, HEAD_H = 22;
static const float HEAD_MID = HEAD_TOP + HEAD_H / 2.f;

static int midBaseline(const Font &f, float mid) {
  return (int)lroundf(mid + (f.ascent - f.descent) / 2.f);
}

static const float BADGE = 18;  // badge height (and width of a metro disc)

static float badgeWidth(const LineInfo &l) {
  float tw = Canvas::width(FBADGE, l.name);
  if (l.kind == KIND_METRO) return BADGE;
  if (l.kind == KIND_TRAM) return tw + 9 > BADGE ? tw + 9 : BADGE;
  return tw + 7 > BADGE ? tw + 7 : BADGE;
}

static void badge(Canvas &c, float x, const LineInfo &l, Rgb border) {
  float w = badgeWidth(l), y = HEAD_MID - BADGE / 2;
  float r = l.kind == KIND_RER || l.kind == KIND_TRAIN ? 5.f : BADGE / 2;
  c.rrect(x, y, w, BADGE, r, l.color);
  c.rrectStroke(x, y, w, BADGE, r, 1, border);
  float tw = Canvas::width(FBADGE, l.name);
  c.text(FBADGE, x + (w - tw) / 2, midBaseline(FBADGE, HEAD_MID), l.name, l.text);
}

static const float NAME_X = 10 + 20 + 6;

// Width of the badge group with at most `maxb` badges (then "+n").
static float badgesWidth(const PlaceData &p, int maxb) {
  int n = p.nlines < maxb ? p.nlines : maxb;
  float w = 0;
  for (int i = 0; i < n; i++) w += badgeWidth(p.lines[i]) + (i ? 3 : 0);
  if (p.nlines > maxb) {
    char more[6];
    snprintf(more, sizeof more, "+%d", p.nlines - maxb);
    w += 4 + Canvas::width(FSMALLM, more);
  }
  return w;
}

// Draws the badges ending at `right`; returns their left edge. Up to six badges, fewer when the
// station name would otherwise be cut (never fewer than two).
static float badges(Canvas &c, const PlaceData &p, float right, Rgb fg) {
  float nameW = Canvas::width(FNAME, p.name);
  int maxb = 6;
  while (maxb > 2 && right - badgesWidth(p, maxb) - 6 - NAME_X < nameW) maxb--;
  int n = p.nlines < maxb ? p.nlines : maxb;
  char more[6] = "";
  if (p.nlines > maxb) snprintf(more, sizeof more, "+%d", p.nlines - maxb);
  float x = right - badgesWidth(p, maxb);
  float left = x;
  for (int i = 0; i < n; i++) {
    badge(c, x, p.lines[i], fg);
    x += badgeWidth(p.lines[i]) + 3;
  }
  if (more[0]) c.text(FSMALLM, x + 1, midBaseline(FSMALLM, HEAD_MID), more, fg);
  return left;
}

static float pill(Canvas &c, float right, const char *label, Rgb bg, Rgb fg) {
  float w = Canvas::width(FPILL, label) + 20;
  c.rrect(right - w, HEAD_TOP, w, HEAD_H, HEAD_H / 2.f, bg);
  c.text(FPILL, right - w + 10, midBaseline(FPILL, HEAD_MID), label, fg);
  return right - w;
}

static float lockPill(Canvas &c, float right, uint8_t dots, Rgb bg, Rgb fg) {
  // padlock (14 px box) then three 8 px dots, one filled per press
  const float PAD = 10, LOCK = 14, DOT = 8, GAP = 6;
  float w = PAD + LOCK + 3 * (GAP + DOT) + PAD;
  float x = right - w;
  c.rrect(x, HEAD_TOP, w, HEAD_H, HEAD_H / 2.f, bg);
  float ox = x + PAD, oy = HEAD_MID - LOCK / 2;
  c.rrectStroke(ox + 1.5f, oy + 6, 11, 8, 2, 2, fg);  // body
  c.rect((int)(ox + 6), (int)(oy + 9), 2, 2, fg);     // keyhole
  for (int k = 0; k < 10; k++) {                        // shackle: half circle of radius 3.5
    float a0 = 3.14159f + k * 3.14159f / 10, a1 = 3.14159f + (k + 1) * 3.14159f / 10;
    c.line(ox + 7 + 3.5f * cosf(a0), oy + 5 + 3.5f * sinf(a0), ox + 7 + 3.5f * cosf(a1),
           oy + 5 + 3.5f * sinf(a1), 2, fg);
  }
  c.line(ox + 3.5f, oy + 5, ox + 3.5f, oy + 6.5f, 2, fg);
  c.line(ox + 10.5f, oy + 5, ox + 10.5f, oy + 6.5f, 2, fg);
  for (int i = 0; i < 3; i++) {
    float cx = ox + LOCK + GAP + DOT / 2 + i * (GAP + DOT);
    if (i < dots)
      c.ellipse(cx, HEAD_MID, DOT / 2, DOT / 2, SIGNAL);
    else
      c.ring(cx, HEAD_MID, DOT / 2, 1.5f, fg);
  }
  return x;
}

static void stationName(Canvas &c, const char *name, float right, Rgb fg) {
  char buf[96];
  float x = NAME_X;
  fitText(FNAME, name, right - 6 - x, buf, sizeof buf);
  c.text(FNAME, x, midBaseline(FNAME, HEAD_MID), buf, fg);
}

static void headerRabbit(Canvas &c, Rgb col) { c.mask(10, HEAD_TOP + 1, rabbit20, 20, 20, col); }

// ---- Chart: 20 bars, 5 h ... 0 h ----

enum Mark : uint8_t { M_NONE, M_NOW, M_CALMER, M_BUSIEST, M_CALMEST };

static const int BAR_BASE = 150, BAR_MAX = 52, LABEL_TOP = 153;

static int chartPos(int h) {
  for (int i = 0; i < APT_CHART_N; i++)
    if (apt_chart_hours[i] == h) return i;
  return -1;
}

static void chart(Canvas &c, Ground g, const uint16_t scores[24], float scale, const Mark marks[APT_CHART_N],
                  int anchorPos) {
  for (int i = 0; i < APT_CHART_N; i++) {
    uint16_t s = scores[apt_hour_index(apt_chart_hours[i])];
    int h = (int)lroundf(s / scale * BAR_MAX);
    if (h > BAR_MAX) h = BAR_MAX;
    if (h < 2) h = 2;
    float x = 12 + 15 * i, y = BAR_BASE - h;
    Mark m = marks[i];
    if (g == G_NUIT) {
      if (m == M_NOW)
        c.rrect(x, y, 11, h, 3, 3, 0, 0, rgb(0xFFFFFF), rgb(0xAEB6C4));
      else if (m == M_CALMER)
        c.rrect(x, y, 11, h, 3, 3, 0, 0, LIME_TOP, LIME_BOTTOM);
      else
        c.rrect(x, y, 11, h, 3, 3, 0, 0, rgb(0x6A7890), rgb(0x262E3B));
    } else if (g == G_SIGNAL) {
      if (m == M_NOW)
        c.rrect(x, y, 11, h, 3, 3, 0, 0, NUIT, rgb(0x3F4A1A));
      else
        c.rrect(x, y, 11, h, 3, 3, 0, 0, NUIT, NUIT, 0.62f, 0.14f);
    } else {
      if (m == M_BUSIEST)
        c.rrect(x, y, 11, h, 3, 3, 0, 0, NUIT, rgb(0x3A4558));
      else if (m == M_CALMEST) {
        c.rrect(x, y, 11, h, 3, 3, 0, 0, NUIT, NUIT);  // 1 px border, no bottom edge
        c.rrect(x + 1, y + 1, 9, h - 1, 2, 2, 0, 0, LIME_TOP, LIME_BOTTOM);
      } else
        c.rrect(x, y, 11, h, 3, 3, 0, 0, rgb(0x8E97A6), rgb(0xC5CBD5));
    }
  }
  // Hour labels: every third hour counted from the anchor (now, else 6 h), plus the marked
  // hours on the "now" screens; a plain label next to a marked one is left out.
  bool highlight[APT_CHART_N] = {false};
  for (int i = 0; i < APT_CHART_N; i++) highlight[i] = (g != G_PAPIER) && (marks[i] == M_NOW || marks[i] == M_CALMER);
  int base = LABEL_TOP;
  int bl = Canvas::baselineFor(FSMALL, base, 14);
  for (int i = 0; i < APT_CHART_N; i++) {
    bool plain = ((i - anchorPos) % 3 + 3) % 3 == 0;
    if (!highlight[i]) {
      if (!plain) continue;
      bool near = (i > 0 && highlight[i - 1]) || (i < APT_CHART_N - 1 && highlight[i + 1]);
      if (near) continue;
    }
    char lab[4];
    snprintf(lab, sizeof lab, "%d", apt_chart_hours[i]);
    const Font &f = highlight[i] ? FSMALLB : FSMALL;
    Rgb col = g == G_NUIT ? (highlight[i] ? (marks[i] == M_CALMER ? SIGNAL : PAPIER) : MUTED_ON_NUIT) : NUIT;
    float cx = 12 + 15 * i + 5.5f;
    c.text(f, cx - Canvas::width(f, lab) / 2, bl, lab, col);
  }
}

// Legend item: 7 px swatch, 4 px gap, label. Returns the width.
static float legendItem(Canvas &c, float x, int top, Rgb s0, Rgb s1, bool border, const char *label, Rgb fg) {
  float y = top + 2.5f;
  if (border) {
    c.rrect(x, y, 9, 9, 2.5f, NUIT);
    c.rrect(x + 1.5f, y + 1.5f, 6, 6, 1.5f, 1.5f, 1.5f, 1.5f, s0, s1);
  } else {
    c.rrect(x, y, 9, 9, 2.5f, 2.5f, 2.5f, 2.5f, s0, s1);
  }
  float w = Canvas::width(FSMALL, label);
  c.text(FSMALL, x + 14, Canvas::baselineFor(FSMALL, top, 14), label, fg);
  return 14 + w;
}

// ---- Station screens ----

static const char *HEADLINES[4] = {"Calme.", "Assez calme.", "Chargé.", "Très chargé."};

static const char *WD[7] = {"dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."};
static const char *MON[12] = {"janv.", "févr.", "mars", "avr.", "mai", "juin",
                              "juil.", "août", "sept.", "oct.", "nov.", "déc."};

static void nowScreen(Canvas &c, const StationView &v, const uint16_t scores[24]) {
  AptNow now;
  apt_now_facts(scores, (uint8_t)v.hour, EDGES, &now);
  Ground g = now.nuit ? G_NUIT : G_SIGNAL;
  ground(c, g);
  Rgb fg = g == G_NUIT ? PAPIER : NUIT;

  if (g == G_SIGNAL) {  // rabbit bottom right of the headline, with its shadow
    c.ellipse(277 + 17, 93 + 3, 17, 3, NUIT, 0.2f);
    c.mask(272, 55, rabbit42, 42, 42, NUIT);
  }
  headerRabbit(c, g == G_NUIT ? SIGNAL : NUIT);
  float right = 310;
  float left = v.locked ? lockPill(c, right, v.lockDots, g == G_NUIT ? rgb(0x262E3B) : NUIT, PAPIER)
                        : badges(c, *v.place, right, fg);
  stationName(c, v.place->name, left, fg);

  const char *head = HEADLINES[now.band];
  int legendTop;
  if (g == G_SIGNAL && Canvas::width(FH52, head) <= 252) {
    c.text(FH52, 10, Canvas::baselineFor(FH52, 30, 52), head, fg);
    legendTop = 84;
  } else {
    c.text(FH40, 10, Canvas::baselineFor(FH40, 32, 42), head, fg);
    legendTop = 78;
  }

  Mark marks[APT_CHART_N] = {M_NONE};
  int nowPos = chartPos(v.hour);
  if (nowPos >= 0) marks[nowPos] = M_NOW;
  int calmPos = now.nuit && now.calmer_hour >= 0 ? chartPos(now.calmer_hour) : -1;
  if (calmPos >= 0) marks[calmPos] = M_CALMER;

  if (nowPos >= 0) {
    float x = 10;
    Rgb lf = g == G_NUIT ? MUTED_ON_NUIT : NUIT;
    if (g == G_NUIT)
      x += legendItem(c, x, legendTop, rgb(0xFFFFFF), rgb(0xAEB6C4), false, "maintenant", lf) + 12;
    else
      x += legendItem(c, x, legendTop, NUIT, rgb(0x3F4A1A), false, "maintenant", lf) + 12;
    if (calmPos >= 0) legendItem(c, x, legendTop, LIME_TOP, LIME_BOTTOM, false, "plus calme", lf);
  }

  AptDay day;
  apt_day_facts(scores, &day);
  float scale = day.peak > 100 ? day.peak : 100;  // app: "now" charts use max(100, peak)
  chart(c, g, scores, scale, marks, nowPos >= 0 ? nowPos : chartPos(6));
}

static void dayScreen(Canvas &c, const StationView &v, int32_t day, const uint16_t scores[24]) {
  ground(c, G_PAPIER);
  headerRabbit(c, NUIT);
  int y, m, d, wd;
  apt_civil((uint16_t)day, &y, &m, &d, &wd);
  char label[40];
  snprintf(label, sizeof label, "Demain \xC2\xB7 %s %d %s", WD[wd], d, MON[m - 1]);
  // Short pill when the full date would cut the station name.
  if (310 - (Canvas::width(FPILL, label) + 20) - 6 - NAME_X < Canvas::width(FNAME, v.place->name))
    snprintf(label, sizeof label, "Demain \xC2\xB7 %s %d", WD[wd], d);
  float left = v.locked ? lockPill(c, 310, v.lockDots, NUIT, PAPIER) : pill(c, 310, label, NUIT, PAPIER);
  stationName(c, v.place->name, left, NUIT);

  AptDay f;
  apt_day_facts(scores, &f);
  Mark marks[APT_CHART_N] = {M_NONE};
  if (f.peak == 0 || !f.has_window) {
    c.text(FH28, 10, Canvas::baselineFor(FH28, 31, 27), "Pas de", NUIT);
    c.text(FH28, 10, Canvas::baselineFor(FH28, 58, 27), "pr\xC3\xA9vision.", NUIT);
    return;
  }
  for (int i = 0; i < f.n_busiest; i++) marks[chartPos(f.busiest[i])] = M_BUSIEST;
  for (int i = 0; i < f.n_calmest; i++) marks[chartPos(f.calmest[i])] = M_CALMEST;
  char l2[40];
  snprintf(l2, sizeof l2, "de %d\xC2\xA0h \xC3\xA0 %d\xC2\xA0h.", f.window_from, f.window_to);
  c.text(FH28, 10, Canvas::baselineFor(FH28, 31, 27), "Plus charg\xC3\xA9", NUIT);
  c.text(FH28, 10, Canvas::baselineFor(FH28, 58, 27), l2, NUIT);
  float x = 10;
  x += legendItem(c, x, 88, NUIT, rgb(0x3A4558), false, "plus charg\xC3\xA9", NUIT) + 12;
  if (f.n_calmest) legendItem(c, x, 88, LIME_TOP, LIME_BOTTOM, true, "plus calme", NUIT);
  chart(c, G_PAPIER, scores, (float)f.peak, marks, chartPos(6));
}

void drawStation(Canvas &c, const StationView &v) {
  if (!v.place) {
    drawMessage(c, v.fallbackName ? v.fallbackName : "", "Pas encore", "de donn\xC3\xA9" "es.",
                "Elles arrivent \xC3\xA0 la prochaine connexion Wi-Fi.", nullptr);
    return;
  }
  int32_t day = v.today + (v.tomorrow ? 1 : 0);
  uint16_t scores[24];
  if (!scoresFor(*v.place, day, scores)) {
    drawMessage(c, v.place->name, "Pas de", "pr\xC3\xA9vision.", nullptr, nullptr);
    return;
  }
  if (v.tomorrow)
    dayScreen(c, v, day, scores);
  else
    nowScreen(c, v, scores);
}

void drawHoldBar(Canvas &c, float p, bool onNight) {
  if (p <= 0) return;
  if (p > 1) p = 1;
  c.rect(0, 0, (int)lroundf(SCR_W * p), 4, onNight ? SIGNAL : NUIT);
}

static float easeInOut(float t) { return t < 0.5f ? 2 * t * t : 1 - powf(-2 * t + 2, 2) / 2; }

bool drawClose(Canvas &c, float t) {
  const float LOCKUP = 0.7f, SHRINK = 0.45f, DOT = 0.35f, HOLD = 0.25f, FADE = 0.25f;
  if (t < LOCKUP) {  // lime "à point" screen
    c.fill(SIGNAL);
    const char *word = "\xC3\xA0 point";
    float tw = Canvas::width(FH40, word), w = 50 + 10 + tw, x = (SCR_W - w) / 2;
    c.mask((int)lroundf(x), 60, rabbit50, 50, 50, NUIT);
    c.text(FH40, x + 60, Canvas::baselineFor(FH40, 65, 40), word, NUIT);
    return true;
  }
  t -= LOCKUP;
  c.fill(NUIT);
  if (t < SHRINK) {  // the lime screen closes into a disc around the rabbit
    float k = easeInOut(t / SHRINK);
    float r = 185 + (55 - 185) * k;
    c.ellipse(160, 85, r, r, SIGNAL);
    c.mask(129, 47, rabbit62, 62, 62, NUIT, k);
    return true;
  }
  t -= SHRINK;
  if (t < DOT) {  // the disc becomes a dot
    float k = easeInOut(t / DOT);
    float r = 55 + (5 - 55) * k;
    c.ellipse(160, 85, r, r, SIGNAL);
    if (k < 0.6f) c.mask(129, 47, rabbit62, 62, 62, NUIT, 1 - k / 0.6f);
    return true;
  }
  t -= DOT;
  if (t < HOLD) {
    c.ellipse(160, 85, 5, 5, SIGNAL);
    return true;
  }
  t -= HOLD;
  if (t < FADE) {
    c.ellipse(160, 85, 5, 5, SIGNAL, 1 - t / FADE);
    return true;
  }
  return false;
}

void drawMessage(Canvas &c, const char *title, const char *line1, const char *line2, const char *small1,
                 const char *small2) {
  ground(c, G_PAPIER);
  headerRabbit(c, NUIT);
  stationName(c, title, 310, NUIT);
  if (line1) c.text(FH28, 10, Canvas::baselineFor(FH28, 31, 27), line1, NUIT);
  if (line2) c.text(FH28, 10, Canvas::baselineFor(FH28, 58, 27), line2, NUIT);
  if (small1) c.text(FLABEL, 10, Canvas::baselineFor(FLABEL, 120, 16), small1, NUIT);
  if (small2) c.text(FLABEL, 10, Canvas::baselineFor(FLABEL, 138, 16), small2, NUIT);
}

void drawSetup(Canvas &c, const SetupView &v) {
  ground(c, G_PAPIER);
  headerRabbit(c, NUIT);
  stationName(c, "R\xC3\xA9glages", 310, NUIT);
  // QR code to join the keychain's network with the phone camera, as large as the screen allows.
  int qx = 8, qy = 30, side = 0;
  if (v.qrSize > 0) {
    int scale = 134 / (v.qrSize + 2);
    side = scale * (v.qrSize + 2);
    c.rrect(qx, qy, side, side, 6, rgb(0xFFFFFF));
    for (int y = 0; y < v.qrSize; y++)
      for (int x = 0; x < v.qrSize; x++)
        if (v.qrModule(x, y)) c.rect(qx + scale * (x + 1), qy + scale * (y + 1), scale, scale, NUIT);
  }
  float x = qx + side + 12, maxW = 312 - x;
  const Rgb mute = rgb(0x4A5466);
  struct {
    const char *k, *val;
  } rows[3] = {{"R\xC3\xA9seau", v.ssid}, {"Mot de passe", v.pass}, {"Puis ouvrez", v.ip}};
  int top = 30;
  char buf[96];
  for (int i = 0; i < 3; i++) {
    c.text(FLABEL, x, Canvas::baselineFor(FLABEL, top, 14), rows[i].k, mute);
    fitText(FVALUE, rows[i].val, maxW, buf, sizeof buf);
    c.text(FVALUE, x, Canvas::baselineFor(FVALUE, top + 14, 22), buf, NUIT);
    top += 38;
  }
  fitText(FLABEL, v.wifiLine ? v.wifiLine : "", maxW, buf, sizeof buf);
  c.text(FLABEL, x, Canvas::baselineFor(FLABEL, 140, 14), buf, NUIT);
  char st[32];
  snprintf(st, sizeof st, "Gares : %d", v.favourites);
  c.text(FLABEL, x, Canvas::baselineFor(FLABEL, 153, 14), st, NUIT);
}
