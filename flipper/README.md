# à point for Flipper Zero

Crowding forecast of Île-de-France metro and RER stations on a Flipper Zero, from the same
open data and forecasts as the web app. Works offline: the forecasts are read from one file on
the SD card.

## Screens and buttons

- **Vos gares**: your favourite stations with how busy they are right now, then
  *Toutes les gares* (every station, alphabetical).
- **Station, now**: headline (*Calme.*, *Assez calme.*, *Chargé.*, *Très chargé.*), line badges,
  hour-by-hour chart (5 h to 0 h). Solid bar: now. Hollow bar: next calmer hour, when it is busy.
- **Station, another date**: busiest hours (solid) and calmest hours (hollow) of that date.

| Button | List | Station |
| --- | --- | --- |
| Up / Down | move | previous / next station of the list you came from |
| Left / Right | jump to the previous / next letter (*Toutes les gares*) | today / next dates |
| OK | open | back to the list |
| OK, long press | add or remove a favourite | add or remove this station |
| Back | back, then exit | back to the list |

Favourites are kept on the SD card in `apps_data/a_point/favoris.txt`, one station id per
line (up to 16). The file can also be edited by hand.

The app reads the time from the Flipper's clock and takes it as Paris time. qFlipper and the
Flipper mobile app set that clock from the computer or phone.

## Data file

From the repository root, after `make score`:

```sh
make flipper            # 28 dates, about 370 KB
make flipper DAYS=84    # every date of the forecast, about 1.1 MB
```

This writes `data/processed/flipper/a_point.dat`. Copy it to the SD card as
`apps_data/a_point/a_point.dat`, with any of:

- qFlipper: *File manager* tab, drag and drop.
- The Flipper mobile app (iOS, Android), over Bluetooth: *File Manager*, upload.
- The SD card in a card reader.

Update it when a new forecast is published (each file covers the dates it was built for; past
them the app says *Prévision périmée*).

The file layout is documented in `src/idf_crowding/score/flipper.py`. Scores are stored halved
(one byte each); band edges are even numbers, so bands are exactly the web app's.

## Build and install

With [ufbt](https://github.com/flipperdevices/flipperzero-ufbt) (it builds for the firmware
release installed on the Flipper):

```sh
pip install ufbt
cd flipper
ufbt              # -> dist/a_point.fap
ufbt launch       # install and start over USB
```

Or copy `dist/a_point.fap` to the SD card in `apps/Tools/`. The app appears as *a point* in
*Apps > Tools*.

## Licences

Code: MIT (see the repository). Data: derived from Île-de-France Mobilités open data, ODbL;
the start screen credits it. Fonts (`fonts.c`): u8g2 copies of the X11 Adobe Helvetica bitmap
fonts (helvB08/10/12, helvR08) and the public-domain X11 misc-fixed 4x6 and 5x7, Latin-1 subsets;
see the [u8g2 font licence list](https://github.com/olikraus/u8g2/wiki/fntgrp).
