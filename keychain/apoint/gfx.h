// Software renderer for the 320 x 170 screen: an RGB888 frame in memory, alpha-blended
// primitives (radial and vertical gradients, rounded rectangles, ellipses, masks, text), then
// a dithered RGB565 copy for the panel. No Arduino dependency: also builds on a computer
// (gen/host_render.cpp) to check the screens against the mockups.
#pragma once
#include <stdint.h>
#include <stddef.h>

#define SCR_W 320
#define SCR_H 170

struct Rgb {
  uint8_t r, g, b;
};
static inline Rgb rgb(uint32_t hex) {
  return Rgb{(uint8_t)(hex >> 16), (uint8_t)(hex >> 8), (uint8_t)hex};
}

struct Glyph {
  uint32_t cp;
  uint32_t off;  // into the font's 4-bit bits, two pixels per byte, high nibble first
  uint8_t w, h;
  int8_t dx, dy;   // top-left of the bitmap relative to the pen on the baseline
  uint16_t adv64;  // advance in 1/64 px
};

struct Font {
  const Glyph *glyphs;
  uint16_t n;
  const uint8_t *bits;
  uint8_t ascent, descent;
  float size;
  float track;  // letter-spacing in px, added after each glyph
};

// The canvas holds a horizontal band of the screen (rows top .. top + rows - 1), or the whole
// screen when there is room: a screen is drawn once per band and each band is sent to the panel
// in turn (see app.cpp show()). Drawing outside the band is clipped.
class Canvas {
 public:
  // Allocates the band buffer. bandRows = SCR_H keeps the whole frame (PSRAM on the device).
  bool begin(int bandRows = SCR_H);
  void setBand(int top);  // the rows the next drawing lands in
  uint8_t *px = nullptr;  // bandRows * SCR_W * 3
  int top = 0, rows = SCR_H, bandRows = SCR_H;

  void fill(Rgb c);
  // CSS radial-gradient(circle at cx cy, c0 alpha a0, transparent at radius r), drawn over the frame.
  void radial(int cx, int cy, Rgb c, float a0, float r);
  void rect(int x, int y, int w, int h, Rgb c, float a = 1.f);
  // Rounded rectangle; radii per corner (tl, tr, br, bl). Vertical gradient top -> bottom.
  void rrect(float x, float y, float w, float h, float rtl, float rtr, float rbr, float rbl, Rgb top,
             Rgb bottom, float atop = 1.f, float abottom = 1.f);
  void rrect(float x, float y, float w, float h, float r, Rgb c, float a = 1.f) {
    rrect(x, y, w, h, r, r, r, r, c, c, a, a);
  }
  // Outline of a rounded rectangle, 1 px or more inside its box.
  void rrectStroke(float x, float y, float w, float h, float r, float t, Rgb c, float a = 1.f);
  void ellipse(float cx, float cy, float rx, float ry, Rgb c, float a = 1.f);
  void ring(float cx, float cy, float r, float t, Rgb c, float a = 1.f);
  void line(float x0, float y0, float x1, float y1, float t, Rgb c, float a = 1.f);
  // 8-bit alpha mask (w x h) at x, y in colour c.
  void mask(int x, int y, const uint8_t *m, int w, int h, Rgb c, float a = 1.f);

  // Text: pen at (x, baseline). Returns the advance in px.
  float text(const Font &f, float x, int baseline, const char *utf8, Rgb c, float a = 1.f);
  static float width(const Font &f, const char *utf8);
  // Baseline for CSS-like placement: a line box of `lineHeight` px whose top is at `top`.
  static int baselineFor(const Font &f, int top, float lineHeight);

  // RGB565 copy of the band (rows x SCR_W; native uint16, as the panel driver takes it).
  void toRgb565(uint16_t *out) const;

 private:
  inline void blend(int x, int y, Rgb c, float a);
  // Narrows a row range to the band; false when nothing is left.
  inline bool clipRows(int &y0, int &y1) const {
    if (y0 < top) y0 = top;
    if (y1 > top + rows - 1) y1 = top + rows - 1;
    return y0 <= y1;
  }
};

// UTF-8 decoder used by the text functions and by the ellipsis helper.
uint32_t utf8Next(const char *&s);
// Copies `src` into `dst` (size n), cut with "…" so it fits `maxW` px in font f.
void fitText(const Font &f, const char *src, float maxW, char *dst, size_t n);
