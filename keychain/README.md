# à point — keychain

Firmware for a LilyGO **T-Display-S3** (ESP32-S3, 1.9" 320 × 170 screen, two buttons) that shows the
crowding forecast of your favourite stations, as in the app.

- Screens: now (Signal ground when calm, Nuit when busy), tomorrow (Papier), locked quick view,
  setup, start-up intro, closing animation. Same rules as the app (`app/src/lib/state.ts`, through
  `flipper/logic.c`).
- Data: the public Place files of the site (`/data/places/<id>.json`, `place.v2`), downloaded once a
  night and kept on the device, so the screens work without Wi-Fi.
- Favourites: sent from the app over the keychain's own Wi-Fi network. Nothing goes through a server.
- Not yet: real-time arrivals (double press on button 2), planned as the next step.

## Controls

| Action | Result |
| --- | --- |
| Button 1 (BOOT), one press | Next station |
| Button 2 (KEY), one press | Today / tomorrow |
| Hold one button 3 s | Closing animation, then off. Any press turns it back on (with the intro). |
| Hold both buttons 3 s | Setup mode |
| No press for 20 s | Sleep. Any press wakes it. |
| After sleep | Locked: the last screen shows; three presses in a row unlock it. |

## Setting it up

1. **Flash it** (below). On first start, after the intro, it opens setup mode by itself.
2. **Join its network** from the phone: scan the QR code on the screen with the camera, or pick
   `à point-XXXX` and type the password shown. A page opens (or go to `http://192.168.4.1`).
3. **Wi-Fi**: choose the network the keychain will use each night (home box or phone hotspot,
   2.4 GHz) and save. The result shows on the keychain screen.
4. **Stations**: on the same page, search and add up to 12 stations (the list is built into the
   keychain, so it works without Internet), then **Enregistrer les gares**. The app's link
   **Envoyer au porte-clés** (under *Vos gares*, once the app is deployed with it) sends your starred
   stations the same way.
5. **Terminer** on the page, or any button on the keychain. It restarts, joins the Wi-Fi, sets the
   clock and downloads the stations.

To change Wi-Fi or stations later: hold both buttons 3 s.

## Build and flash

Builds with either (both compiled; board *LilyGo T-Display-S3*, default options: USB CDC on
boot, OPI PSRAM, 16 MB with the FAT partition, where the stations are stored):

| ESP32 core | GFX Library for Arduino | ArduinoJson |
| --- | --- | --- |
| 3.3.12 | 1.6.9 | 7.x |
| 2.0.17 | 1.4.9 | 7.x |

GFX 1.4.x does not build on core 3.x.

Arduino IDE: open `apoint/apoint.ino`, pick the board and port, Upload.

arduino-cli:

```sh
arduino-cli core install esp32:esp32@3.3.12
arduino-cli lib install "GFX Library for Arduino@1.6.9" "ArduinoJson@7.2.1"
arduino-cli compile -b esp32:esp32:lilygo_t_display_s3 apoint
arduino-cli upload  -b esp32:esp32:lilygo_t_display_s3 -p /dev/cu.usbmodem* apoint
```

PlatformIO: `pio run -t upload` (see `platformio.ini`; not tried yet).

If the board does not show up for upload: hold BOOT, press RST, release BOOT.
If the picture is upside down for the way you hold it: `SCREEN_ROTATION` in `apoint/config.h`.

## Files

```
apoint/            the sketch
  app.cpp          setup(), loop(): buttons, lock, sleep, modes
  screens.*        the screens (portable: also built on a computer)
  gfx.*            renderer: RGB888 frame, gradients, anti-aliased shapes and text, dithered RGB565
  model.*, parse.h Place file -> compact record; logic.* = flipper/logic.c rules
  store.*          NVS (Wi-Fi, favourites, last screen) and FFat (/p/<id>.bin)
  net.*            Wi-Fi, NTP, HTTPS download (root CAs in certs.h)
  portal.*         setup mode: access point, captive page, /f?ids=...
  aptqr.*          QR codes (Nayuki, MIT)
  fonts_data.h, rabbit_data.h, intro_data.h   generated (below)
gen/
  make_assets.py   Onest glyphs (4-bit) and rabbit masks
  make_stations.py station list of the setup page (from app/public/data/index.json)
  intro_enc.py     intro cut -> delta-RLE RGB565 frames
  host_render.*    renders screens to PPM on a computer
```

Regenerate the assets:

```sh
python3 gen/make_assets.py ../app/public/fonts/onest-latin-wght-normal.woff2 <brand>/mark.svg apoint
ffmpeg -ss 2.3 -to 5.6 -i <brand>/intro-v2.mp4 -vf "setpts=PTS/1.3,fps=20,scale=320:180,crop=320:170:0:5" /tmp/intro/f_%03d.png
python3 gen/intro_enc.py /tmp/intro apoint/intro_data.h
```

Check the screens on a computer: `ARDUINOJSON=<ArduinoJson>/src gen/host_render.sh`, then
`gen/host_render station <place.json> 2026-11-19 18 0 0 0 busy.ppm` (date, hour, tomorrow, locked,
dots).

## Notes

- Wi-Fi password and favourites are kept in the board's flash (NVS, not encrypted).
- Bands: 40 / 70 / 100 as in `config.toml`; the keychain does not read `index.json`.
- The intro is the app's short cut (scene 2.3 → 5.6 s at 1.3×) with the tagline covered.
- Font: Onest, SIL Open Font License 1.1 (`OFL.txt`).
