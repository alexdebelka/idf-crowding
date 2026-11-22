// Same rules as the web app (app/src/lib/state.ts, time.ts): bands, "now" facts, day facts.
// Copied from flipper/logic.h (keep the two in step).
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define APT_CHART_N 20 /* chart hours 5 h ... 0 h */

typedef enum {
    AptQuiet,
    AptModerate,
    AptBusy,
    AptVeryBusy,
} AptBand;

extern const uint8_t apt_chart_hours[APT_CHART_N];

/* Position of clock hour h in a 24-value operating-day array (04 h first). */
static inline uint8_t apt_hour_index(uint8_t h) {
    return (uint8_t)((h + 24 - 4) % 24);
}

AptBand apt_band(uint16_t score, const uint8_t edges[3]);

typedef struct {
    uint8_t hour;
    uint16_t score;
    AptBand band;
    bool nuit; /* busy or very busy */
    int8_t calmer_hour; /* nuit only: first later chart hour under the busy threshold, or -1 */
    bool off_hours; /* 1 h - 4 h: not a chart hour */
} AptNow;

void apt_now_facts(const uint16_t scores[24], uint8_t hour, const uint8_t edges[3], AptNow* out);

typedef struct {
    uint8_t n_busiest;
    uint8_t busiest[4];
    bool has_window;
    uint8_t window_from, window_to; /* [from, to) clock hours */
    uint8_t n_calmest;
    uint8_t calmest[2];
    uint16_t peak;
} AptDay;

void apt_day_facts(const uint16_t scores[24], AptDay* out);

/* Calendar date of a day number (days since 1970-01-01). */
void apt_civil(uint16_t day, int* year, int* month, int* mday, int* weekday /* 0 = Sunday */);
