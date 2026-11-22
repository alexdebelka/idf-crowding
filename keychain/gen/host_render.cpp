// Renders keychain screens on a computer, to check them against the mockups.
// Build: see gen/host_render.sh. Usage:
//   host_render station <place.json> <YYYY-MM-DD> <hour> <tomorrow 0|1> <locked 0|1> <dots> <out.ppm>
//   host_render close <t seconds> <out.ppm>
//   host_render setup <out.ppm>
//   host_render message <out.ppm>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <fstream>

#include "../apoint/aptqr.h"
#include "../apoint/gfx.h"
#include "../apoint/model.h"
#include "../apoint/parse.h"
#include "../apoint/screens.h"

static void save(const Canvas &c, const char *path) {
  // Through the same RGB565 dither as the panel, expanded back to 8 bits.
  static uint16_t buf[SCR_W * SCR_H];
  c.toRgb565(buf);
  FILE *f = fopen(path, "wb");
  fprintf(f, "P6\n%d %d\n255\n", SCR_W, SCR_H);
  for (int i = 0; i < SCR_W * SCR_H; i++) {
    uint16_t v = buf[i];
    unsigned char p[3] = {(unsigned char)(((v >> 11) & 31) * 255 / 31), (unsigned char)(((v >> 5) & 63) * 255 / 63),
                          (unsigned char)((v & 31) * 255 / 31)};
    fwrite(p, 1, 3, f);
  }
  fclose(f);
}

static uint8_t qr[aptqr_BUFFER_LEN_FOR_VERSION(6)], qrTemp[aptqr_BUFFER_LEN_FOR_VERSION(6)];
static bool qrModule(int x, int y) { return aptqr_getModule(qr, x, y); }

int main(int argc, char **argv) {
  Canvas c;
  c.begin();
  if (argc >= 9 && !strcmp(argv[1], "station")) {
    static PlaceData p;
    std::ifstream in(argv[2]);
    const char *err = parsePlace(in, p);
    if (err[0]) {
      fprintf(stderr, "parse: %s\n", err);
      return 1;
    }
    StationView v{&p, nullptr, dayFromIso(argv[3]), atoi(argv[4]), atoi(argv[5]) != 0, atoi(argv[6]) != 0,
                  (uint8_t)atoi(argv[7])};
    drawStation(c, v);
    save(c, argv[8]);
    fprintf(stderr, "%s: %d lines, %d dates, typical mask %x\n", p.name, p.nlines, p.ndates, p.typicalMask);
  } else if (argc >= 4 && !strcmp(argv[1], "close")) {
    float t = (float)atof(argv[2]);
    if (t < 0) {
      // hold bar over a plain ground
      c.fill(rgb(0xD9F84A));
      drawHoldBar(c, 0.66f, false);
    } else
      drawClose(c, t);
    save(c, argv[3]);
  } else if (argc >= 3 && !strcmp(argv[1], "setup")) {
    // Same QR text as portal::qrText()
    bool ok = aptqr_encodeText("WIFI:T:WPA;S:\xC3\xA0 point-7F3A;P:48213907;;", qrTemp, qr, aptqr_Ecc_LOW, 1, 6,
                               aptqr_Mask_AUTO, true);
    SetupView v{"\xC3\xA0 point-7F3A", "48213907", "192.168.4.1",
                "Wi-Fi : Freebox-2A41 (ok)", 5, ok ? aptqr_getSize(qr) : 0, qrModule};
    drawSetup(c, v);
    save(c, argv[2]);
  } else if (argc >= 3 && !strcmp(argv[1], "message")) {
    drawMessage(c, "\xC3\xA0 point", "Aucune gare", "enregistr\xC3\xA9" "e.", "Maintenez les deux boutons 3 s",
                "pour ouvrir les r\xC3\xA9glages.");
    save(c, argv[2]);
  } else {
    fprintf(stderr, "bad arguments\n");
    return 2;
  }
  return 0;
}
