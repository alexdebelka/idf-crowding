// Decoder of the intro frames (intro_data.h, gen/intro_enc.py): one frame at a time, band by
// band, into a buffer of `bandRows` screen rows. Portable (tested on a computer).
#pragma once
#include <stdint.h>

#include "gfx.h"
#include "intro_data.h"

// Decodes frame f; calls emit(top, rows) each time the band buffer holds `rows` finished rows.
template <class Emit>
void introDecode(int f, uint16_t *band, int bandRows, Emit emit) {
  const uint16_t *w = intro_words + intro_offs[f], *end = intro_words + intro_offs[f + 1];
  const uint32_t bandPx = (uint32_t)bandRows * SCR_W, total = (uint32_t)SCR_W * SCR_H;
  uint32_t p = 0, k = 0;  // pixel of the frame, pixel inside the band
  int top = 0;
  auto put = [&](uint16_t c) {
    band[k++] = c;
    if (++p, k == bandPx || p == total) {
      int rows = (int)(k / SCR_W);
      emit(top, rows);
      top += rows;
      k = 0;
    }
  };
  while (w < end && p < total) {
    uint16_t h = *w++;
    uint16_t n = h & 0x7FFF;
    if (h & 0x8000) {
      uint16_t c = *w++;
      for (uint16_t i = 0; i < n && p < total; i++) put(c);
    } else {
      for (uint16_t i = 0; i < n && p < total; i++) put(*w++);
    }
  }
}
