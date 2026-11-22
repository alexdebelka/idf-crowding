// Copied from flipper/logic.c (keep the two in step).
#include "logic.h"

const uint8_t apt_chart_hours[APT_CHART_N] = {5,  6,  7,  8,  9,  10, 11, 12, 13, 14,
                                              15, 16, 17, 18, 19, 20, 21, 22, 23, 0};

static int chart_pos(uint8_t h) {
    for(int i = 0; i < APT_CHART_N; i++)
        if(apt_chart_hours[i] == h) return i;
    return -1;
}

AptBand apt_band(uint16_t score, const uint8_t edges[3]) {
    if(score < edges[0]) return AptQuiet;
    if(score < edges[1]) return AptModerate;
    if(score < edges[2]) return AptBusy;
    return AptVeryBusy;
}

void apt_now_facts(const uint16_t scores[24], uint8_t hour, const uint8_t edges[3], AptNow* out) {
    out->hour = hour;
    out->score = scores[apt_hour_index(hour)];
    out->band = apt_band(out->score, edges);
    out->nuit = out->band >= AptBusy;
    out->calmer_hour = -1;
    int pos = chart_pos(hour);
    out->off_hours = pos < 0;
    if(!out->nuit || pos < 0) return;
    uint16_t limit = edges[1]; /* lower bound of "busy" */
    for(int i = pos + 1; i < APT_CHART_N; i++) {
        uint8_t h = apt_chart_hours[i];
        if(scores[apt_hour_index(h)] < limit) {
            out->calmer_hour = (int8_t)h;
            break;
        }
    }
}

void apt_day_facts(const uint16_t scores[24], AptDay* out) {
    uint16_t s[APT_CHART_N];
    out->peak = 0;
    for(int i = 0; i < APT_CHART_N; i++) {
        s[i] = scores[apt_hour_index(apt_chart_hours[i])];
        if(s[i] > out->peak) out->peak = s[i];
    }
    out->n_busiest = 0;
    out->n_calmest = 0;
    out->has_window = false;
    if(out->peak == 0) return;

    /* Up to four highest chart hours, ties to the earlier one (stable sort as in the app). */
    bool taken[APT_CHART_N] = {false};
    int first_pos = -1;
    for(int k = 0; k < 4; k++) {
        int best = -1;
        for(int i = 0; i < APT_CHART_N; i++)
            if(!taken[i] && (best < 0 || s[i] > s[best])) best = i;
        if(best < 0 || s[best] == 0) break;
        taken[best] = true;
        if(first_pos < 0) first_pos = best;
        out->busiest[out->n_busiest++] = apt_chart_hours[best];
    }
    int from = first_pos, to = first_pos;
    while(from - 1 >= 0 && taken[from - 1])
        from--;
    while(to + 1 < APT_CHART_N && taken[to + 1])
        to++;
    out->has_window = true;
    out->window_from = apt_chart_hours[from];
    out->window_to = (uint8_t)((apt_chart_hours[to] + 1) % 24);
    /* busiest in chart order */
    uint8_t n = 0;
    for(int i = 0; i < APT_CHART_N; i++)
        if(taken[i]) out->busiest[n++] = apt_chart_hours[i];

    /* Two consecutive daytime hours (7 h - 20 h) with the fewest entries; same loop as the app. */
    int d0 = chart_pos(7); /* day[] = chart hours 7..20 */
    int len = chart_pos(20) - d0 + 1;
    int best = 0;
    for(int i = 1; i < len - 1; i++)
        if(s[d0 + i] + s[d0 + i + 1] < s[d0 + best] + s[d0 + best + 1]) best = i;
    for(int j = 0; j < 2; j++) {
        uint8_t h = apt_chart_hours[d0 + best + j];
        if(!taken[d0 + best + j]) out->calmest[out->n_calmest++] = h;
    }
}

void apt_civil(uint16_t day, int* year, int* month, int* mday, int* weekday) {
    /* Howard Hinnant's civil_from_days */
    long z = (long)day + 719468;
    long era = z / 146097;
    long doe = z - era * 146097;
    long yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    long y = yoe + era * 400;
    long doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    long mp = (5 * doy + 2) / 153;
    long d = doy - (153 * mp + 2) / 5 + 1;
    long m = mp < 10 ? mp + 3 : mp - 9;
    *year = (int)(y + (m <= 2));
    *month = (int)m;
    *mday = (int)d;
    *weekday = (int)((day + 4) % 7); /* 1970-01-01 was a Thursday */
}
