#pragma once

#include <furi.h>
#include <gui/gui.h>

#include "data.h"
#include "logic.h"

typedef enum {
    ScreenBoot,
    ScreenError,
    ScreenFavs, /* "Vos gares": favourites, then "Toutes les gares" */
    ScreenAll, /* every Place, alphabetical */
    ScreenStation,
} Screen;

#define LIST_ROWS 4

typedef struct {
    FuriMutex* mutex;
    AptData data;
    AptStatus status;
    Screen screen;

    /* clock (Paris local time from the Flipper's RTC), operating date */
    uint16_t today; /* day number; before 04 h, the previous date */
    uint8_t hour;

    /* lists */
    int16_t fav_sel, fav_top;
    int16_t all_sel, all_top;
    int8_t fav_band[APT_MAX_FAVS]; /* AptBand now, -1 unknown */

    /* station view */
    bool from_favs;
    uint16_t place;
    uint16_t offset; /* 0 = now, 1 = tomorrow ... */
    AptLine lines[APT_MAX_LINES];
    uint8_t n_lines;
    uint16_t scores[APT_HOURS];
    bool scores_ok;

    uint32_t boot_until;
    uint32_t toast_until;
    const char* toast;
} App;

void app_draw(Canvas* canvas, void* ctx);
