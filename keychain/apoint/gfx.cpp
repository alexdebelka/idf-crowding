#include "gfx.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#ifdef ARDUINO
#include <esp_heap_caps.h>
#endif

static inline float clamp01(float v) { return v < 0.f ? 0.f : (v > 1.f ? 1.f : v); }

bool Canvas::begin(int band) {
  if (px) return true;
  bandRows = band < 1 ? 1 : (band > SCR_H ? SCR_H : band);
  size_t n = (size_t)SCR_W * bandRows * 3;
#ifdef ARDUINO
  px = (uint8_t *)heap_caps_malloc(n, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!px) px = (uint8_t *)malloc(n);
#else
  px = (uint8_t *)malloc(n);
#endif
  setBand(0);
  return px != nullptr;
}

void Canvas::setBand(int t) {
  top = t;
  rows = SCR_H - t < bandRows ? SCR_H - t : bandRows;
}

inline void Canvas::blend(int x, int y, Rgb c, float a) {
  y -= top;
  if (x < 0 || y < 0 || x >= SCR_W || y >= rows || a <= 0.f) return;
  uint8_t *p = px + (y * SCR_W + x) * 3;
  if (a >= 1.f) {
    p[0] = c.r; p[1] = c.g; p[2] = c.b;
    return;
  }
  p[0] = (uint8_t)(p[0] + (c.r - p[0]) * a + 0.5f);
  p[1] = (uint8_t)(p[1] + (c.g - p[1]) * a + 0.5f);
  p[2] = (uint8_t)(p[2] + (c.b - p[2]) * a + 0.5f);
}

void Canvas::fill(Rgb c) {
  for (int i = 0; i < SCR_W * rows; i++) {
    px[i * 3] = c.r; px[i * 3 + 1] = c.g; px[i * 3 + 2] = c.b;
  }
}

void Canvas::radial(int cx, int cy, Rgb c, float a0, float r) {
  int x0 = cx - (int)r - 1, x1 = cx + (int)r + 1, y0 = cy - (int)r - 1, y1 = cy + (int)r + 1;
  if (x0 < 0) x0 = 0;
  if (y0 < 0) y0 = 0;
  if (x1 > SCR_W - 1) x1 = SCR_W - 1;
  if (!clipRows(y0, y1)) return;
  for (int y = y0; y <= y1; y++)
    for (int x = x0; x <= x1; x++) {
      float dx = x + 0.5f - cx, dy = y + 0.5f - cy;
      float d = sqrtf(dx * dx + dy * dy);
      if (d >= r) continue;
      blend(x, y, c, a0 * (1.f - d / r));
    }
}

void Canvas::rect(int x, int y, int w, int h, Rgb c, float a) {
  int ya = y, yb = y + h - 1;
  if (!clipRows(ya, yb)) return;
  for (int j = ya; j <= yb; j++)
    for (int i = x; i < x + w; i++) blend(i, j, c, a);
}

// Signed distance from a point to a rounded box (corner radius chosen by quadrant).
static float rboxDist(float px, float py, float x, float y, float w, float h, float rtl, float rtr,
                      float rbr, float rbl) {
  float cx = x + w / 2, cy = y + h / 2;
  float qx = px - cx, qy = py - cy;
  float r = qx < 0 ? (qy < 0 ? rtl : rbl) : (qy < 0 ? rtr : rbr);
  float ax = fabsf(qx) - (w / 2 - r), ay = fabsf(qy) - (h / 2 - r);
  float ox = ax > 0 ? ax : 0, oy = ay > 0 ? ay : 0;
  float outside = sqrtf(ox * ox + oy * oy);
  float inside = ax > ay ? ax : ay;
  return (inside < 0 ? inside : 0) + outside - r;
}

void Canvas::rrect(float x, float y, float w, float h, float rtl, float rtr, float rbr, float rbl,
                   Rgb top, Rgb bottom, float atop, float abottom) {
  if (w <= 0 || h <= 0) return;
  int x0 = (int)floorf(x), x1 = (int)ceilf(x + w), y0 = (int)floorf(y), y1 = (int)ceilf(y + h) - 1;
  if (!clipRows(y0, y1)) return;
  for (int j = y0; j <= y1; j++) {
    float t = h > 1 ? clamp01((j + 0.5f - y) / h) : 0.f;
    Rgb c{(uint8_t)(top.r + (bottom.r - top.r) * t), (uint8_t)(top.g + (bottom.g - top.g) * t),
          (uint8_t)(top.b + (bottom.b - top.b) * t)};
    float a = atop + (abottom - atop) * t;
    for (int i = x0; i < x1; i++) {
      float d = rboxDist(i + 0.5f, j + 0.5f, x, y, w, h, rtl, rtr, rbr, rbl);
      float cov = clamp01(0.5f - d);
      if (cov > 0) blend(i, j, c, a * cov);
    }
  }
}

void Canvas::rrectStroke(float x, float y, float w, float h, float r, float t, Rgb c, float a) {
  int x0 = (int)floorf(x), x1 = (int)ceilf(x + w), y0 = (int)floorf(y), y1 = (int)ceilf(y + h) - 1;
  float ri = r - t > 0 ? r - t : 0;
  if (!clipRows(y0, y1)) return;
  for (int j = y0; j <= y1; j++)
    for (int i = x0; i < x1; i++) {
      float d = rboxDist(i + 0.5f, j + 0.5f, x, y, w, h, r, r, r, r);
      float di = rboxDist(i + 0.5f, j + 0.5f, x + t, y + t, w - 2 * t, h - 2 * t, ri, ri, ri, ri);
      float cov = clamp01(0.5f - d) * clamp01(0.5f + di);
      if (cov > 0) blend(i, j, c, a * cov);
    }
}

void Canvas::ellipse(float cx, float cy, float rx, float ry, Rgb c, float a) {
  int x0 = (int)floorf(cx - rx - 1), x1 = (int)ceilf(cx + rx + 1);
  int y0 = (int)floorf(cy - ry - 1), y1 = (int)ceilf(cy + ry + 1);
  if (!clipRows(y0, y1)) return;
  for (int j = y0; j <= y1; j++)
    for (int i = x0; i <= x1; i++) {
      float dx = (i + 0.5f - cx) / rx, dy = (j + 0.5f - cy) / ry;
      float n = sqrtf(dx * dx + dy * dy);
      // distance in px, approximated with the smaller radius
      float d = (n - 1.f) * (rx < ry ? rx : ry);
      float cov = clamp01(0.5f - d);
      if (cov > 0) blend(i, j, c, a * cov);
    }
}

void Canvas::ring(float cx, float cy, float r, float t, Rgb c, float a) {
  int x0 = (int)floorf(cx - r - 1), x1 = (int)ceilf(cx + r + 1);
  int y0 = (int)floorf(cy - r - 1), y1 = (int)ceilf(cy + r + 1);
  if (!clipRows(y0, y1)) return;
  for (int j = y0; j <= y1; j++)
    for (int i = x0; i <= x1; i++) {
      float dx = i + 0.5f - cx, dy = j + 0.5f - cy;
      float d = sqrtf(dx * dx + dy * dy);
      float cov = clamp01(0.5f - (d - r)) * clamp01(0.5f + (d - (r - t)));
      if (cov > 0) blend(i, j, c, a * cov);
    }
}

void Canvas::line(float x0, float y0, float x1, float y1, float t, Rgb c, float a) {
  int bx0 = (int)floorf((x0 < x1 ? x0 : x1) - t), bx1 = (int)ceilf((x0 > x1 ? x0 : x1) + t);
  int by0 = (int)floorf((y0 < y1 ? y0 : y1) - t), by1 = (int)ceilf((y0 > y1 ? y0 : y1) + t);
  float vx = x1 - x0, vy = y1 - y0, len2 = vx * vx + vy * vy;
  if (!clipRows(by0, by1)) return;
  for (int j = by0; j <= by1; j++)
    for (int i = bx0; i <= bx1; i++) {
      float px_ = i + 0.5f - x0, py_ = j + 0.5f - y0;
      float u = len2 > 0 ? clamp01((px_ * vx + py_ * vy) / len2) : 0;
      float dx = px_ - u * vx, dy = py_ - u * vy;
      float d = sqrtf(dx * dx + dy * dy) - t / 2;
      float cov = clamp01(0.5f - d);
      if (cov > 0) blend(i, j, c, a * cov);
    }
}

void Canvas::mask(int x, int y, const uint8_t *m, int w, int h, Rgb c, float a) {
  int ya = y, yb = y + h - 1;
  if (!clipRows(ya, yb)) return;
  for (int j = ya - y; j <= yb - y; j++)
    for (int i = 0; i < w; i++) {
      uint8_t v = m[j * w + i];
      if (v) blend(x + i, y + j, c, a * v / 255.f);
    }
}

uint32_t utf8Next(const char *&s) {
  uint8_t c = (uint8_t)*s;
  if (!c) return 0;
  s++;
  if (c < 0x80) return c;
  int n = (c >= 0xF0) ? 3 : (c >= 0xE0) ? 2 : (c >= 0xC0) ? 1 : 0;
  uint32_t cp = c & (0x3F >> n);
  while (n-- > 0 && (*s & 0xC0) == 0x80) cp = (cp << 6) | (*s++ & 0x3F);
  return cp;
}

static const Glyph *findGlyph(const Font &f, uint32_t cp) {
  for (uint16_t i = 0; i < f.n; i++)
    if (f.glyphs[i].cp == cp) return &f.glyphs[i];
  if (cp == 0x00A0 || cp == 0x202F) return findGlyph(f, ' ');
  return findGlyph(f, '?');
}

float Canvas::text(const Font &f, float x, int baseline, const char *s, Rgb c, float a) {
  // Glyphs are placed at fractional pen positions: each bitmap is shifted by the fraction of a
  // pixel (linear interpolation between columns), so small text keeps even spacing.
  float pen = x;
  while (*s) {
    const Glyph *g = findGlyph(f, utf8Next(s));
    if (!g) continue;
    float gxf = pen + g->dx;
    int gx = (int)floorf(gxf);
    float fr = gxf - gx;
    int gy = baseline + g->dy;
    int ja = gy, jb = gy + g->h - 1;
    if (!clipRows(ja, jb)) {
      pen += g->adv64 / 64.f + f.track;
      continue;
    }
    for (int j = ja - gy; j <= jb - gy; j++) {
      uint8_t prev = 0;
      for (int i = 0; i <= g->w; i++) {
        uint8_t v = 0;
        if (i < g->w) {
          uint32_t k = (uint32_t)j * g->w + i;
          uint8_t b = f.bits[g->off + k / 2];
          v = (k & 1) ? (b & 0x0F) : (b >> 4);
        }
        float cov = (v * (1.f - fr) + prev * fr) / 15.f;
        if (cov > 0.004f) blend(gx + i, gy + j, c, a * cov);
        prev = v;
      }
    }
    pen += g->adv64 / 64.f + f.track;
  }
  return pen - x;
}

float Canvas::width(const Font &f, const char *s) {
  float w = 0;
  bool any = false;
  while (*s) {
    const Glyph *g = findGlyph(f, utf8Next(s));
    if (!g) continue;
    w += g->adv64 / 64.f + f.track;
    any = true;
  }
  return any ? w - f.track : 0;
}

int Canvas::baselineFor(const Font &f, int top, float lineHeight) {
  float content = f.ascent + f.descent;
  return (int)lroundf(top + (lineHeight - content) / 2.f + f.ascent);
}

void fitText(const Font &f, const char *src, float maxW, char *dst, size_t n) {
  strncpy(dst, src, n - 1);
  dst[n - 1] = 0;
  if (Canvas::width(f, dst) <= maxW) return;
  const char *ell = "\xE2\x80\xA6";  // …
  size_t len = strlen(dst);
  while (len > 0) {
    // drop one UTF-8 character
    do {
      len--;
    } while (len > 0 && ((uint8_t)dst[len] & 0xC0) == 0x80);
    while (len > 0 && dst[len - 1] == ' ') len--;
    if (len + 4 > n) continue;
    memcpy(dst + len, ell, 4);
    if (Canvas::width(f, dst) <= maxW) return;
  }
  dst[0] = 0;
}

// 4 x 4 ordered dither, so the gradients do not band at 16 bits.
static const uint8_t BAYER[16] = {0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5};

void Canvas::toRgb565(uint16_t *out) const {
  for (int y = 0; y < rows; y++)
    for (int x = 0; x < SCR_W; x++) {
      const uint8_t *p = px + (y * SCR_W + x) * 3;
      int ay = y + top;  // dither on screen rows, so bands join without a seam
      int t = BAYER[(ay & 3) * 4 + (x & 3)];
      int r = p[0] + (t >> 1), g = p[1] + (t >> 2), b = p[2] + (t >> 1);
      if (r > 255) r = 255;
      if (g > 255) g = 255;
      if (b > 255) b = 255;
      out[y * SCR_W + x] = (uint16_t)(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3));
    }
}
