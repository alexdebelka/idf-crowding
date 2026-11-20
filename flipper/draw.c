// Screens, as drawn on the design canvas (keychain canvas, "Flipper" row).
#include <stdio.h>
#include <string.h>

#include "app.h"
#include "fonts.h"

static const uint8_t rabbit_small_bits[] =
    {0xc6, 0x00, 0xcc, 0x00, 0xfc, 0x00, 0xfe, 0x01, 0xff, 0x03, 0xcf, 0x03, 0xcf, 0x03, 0xff, 0x03, 0xfe, 0x01};
static const uint8_t rabbit_big_bits[] = {
    0xc0, 0x03, 0x0e, 0x00, 0xe0, 0x03, 0x1f, 0x00, 0xf0, 0x87, 0x3f, 0x00, 0xf0, 0xc7, 0x3f, 0x00, 0xf0, 0xcf,
    0x3f, 0x00, 0xf0, 0xcf, 0x3f, 0x00, 0xf0, 0xef, 0x3f, 0x00, 0xf0, 0xef, 0x3f, 0x00, 0xf0, 0xef, 0x1f, 0x00,
    0xf0, 0xff, 0x1f, 0x00, 0xf0, 0xff, 0x1f, 0x00, 0xe0, 0xff, 0x1f, 0x00, 0xe0, 0xff, 0x0f, 0x00, 0xe0, 0xff,
    0x0f, 0x00, 0xe0, 0xff, 0x0f, 0x00, 0xe0, 0xff, 0x0f, 0x00, 0xf0, 0xff, 0x1f, 0x00, 0xf0, 0xff, 0x1f, 0x00,
    0xf8, 0xff, 0x3f, 0x00, 0xf8, 0xff, 0x3f, 0x00, 0xfc, 0xff, 0x7f, 0x00, 0xfc, 0xff, 0x7f, 0x00, 0xfe, 0xff,
    0xff, 0x00, 0xfe, 0xff, 0xff, 0x00, 0xff, 0xff, 0xff, 0x01, 0xff, 0xff, 0xff, 0x01, 0xff, 0xff, 0xff, 0x01,
    0xff, 0x83, 0xff, 0x01, 0xff, 0x83, 0xff, 0x01, 0xff, 0x01, 0xff, 0x01, 0xff, 0x01, 0xff, 0x01, 0xff, 0x83,
    0xff, 0x01, 0xff, 0x83, 0xff, 0x00, 0xfe, 0xff, 0xff, 0x00, 0xfc, 0xff, 0x7f, 0x00, 0xf8, 0xff, 0x3f, 0x00,
    0xf0, 0xff, 0x1f, 0x00, 0xc0, 0xff, 0x07, 0x00};
static const uint8_t star_bits[] = {0x04, 0x1f, 0x0e, 0x0a, 0x11};

static const char* const HEADLINE[] = {"Calme.", "Assez calme.", "Chargé.", "Très chargé."};
static const char* const BAND[] = {"Calme", "Assez calme", "Chargé", "Très chargé"};
static const char* const WDAY[] = {"dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."};
static const char* const MONTH[] =
    {"janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."};

/* chart geometry: 20 bars, 5 px wide, 6 px apart */
#define X0    4
#define PITCH 6
#define BW    5

typedef enum {
    BarDither,
    BarSolid,
    BarHollow,
} BarStyle;

static void text(Canvas* c, const uint8_t* font, int x, int base, const char* s) {
    canvas_set_custom_u8g2_font(c, font);
    canvas_draw_str(c, x, base, s);
}

static int width(Canvas* c, const uint8_t* font, const char* s) {
    canvas_set_custom_u8g2_font(c, font);
    return canvas_string_width(c, s);
}

/* Copies s into buf, cut with "..." so that it fits in maxw pixels. UTF-8 safe. */
static const char* fit(Canvas* c, const uint8_t* font, const char* s, int maxw, char* buf, size_t n) {
    strncpy(buf, s, n - 1);
    buf[n - 1] = '\0';
    if(width(c, font, buf) <= maxw) return buf;
    size_t len = strlen(buf);
    while(len > 0) {
        do {
            len--;
        } while(len > 0 && ((uint8_t)buf[len] & 0xC0) == 0x80);
        while(len > 0 && buf[len - 1] == ' ')
            len--;
        if(len + 4 > n) continue;
        memcpy(buf + len, "...", 4);
        if(width(c, font, buf) <= maxw) return buf;
    }
    return buf;
}

static void dither(Canvas* c, int x, int y, int w, int h) {
    for(int j = y; j < y + h; j++)
        for(int i = x; i < x + w; i++)
            if(((i + j) & 1) == 0) canvas_draw_dot(c, i, j);
}

static void rabbit_corner(Canvas* c) {
    canvas_draw_xbm(c, 117, 0, 10, 9, rabbit_small_bits);
}

/* Line badges, 9 px: metro disc, RER filled square, others outlined. Stops before the rabbit. */
static void badges(Canvas* c, const AptLine* lines, uint8_t n) {
    int x = 0;
    for(uint8_t k = 0; k < n; k++) {
        int tw = width(c, apt_font_4x6, lines[k].name);
        int w = tw + 4 < 9 ? 9 : tw + 4;
        if(x + w > 113) {
            char more[6];
            snprintf(more, sizeof(more), "+%d", n - k);
            text(c, apt_font_4x6, x, 7, more);
            return;
        }
        bool filled = lines[k].kind <= AptLineRer;
        canvas_set_color(c, ColorBlack);
        if(lines[k].kind == AptLineMetro) {
            canvas_draw_disc(c, x + 4, 4, 4);
            if(w > 9) {
                canvas_draw_disc(c, x + w - 5, 4, 4);
                canvas_draw_box(c, x + 4, 0, w - 8, 9);
            }
        } else if(filled) {
            canvas_draw_rbox(c, x, 0, w, 9, 1);
        } else {
            canvas_draw_rframe(c, x, 0, w, 9, 1);
        }
        if(filled) canvas_set_color(c, ColorWhite);
        text(c, apt_font_4x6, x + (w - tw + 1) / 2, 6, lines[k].name);
        canvas_set_color(c, ColorBlack);
        x += w + 2;
    }
}

static void name_row(Canvas* c, const App* app) {
    char buf[64];
    text(c, apt_font_helvB08, 0, 19, fit(c, apt_font_helvB08, apt_place_name(&app->data, app->place), 128, buf, sizeof(buf)));
}

static void chart(
    Canvas* c,
    int top,
    int base,
    const uint16_t scores[24],
    const BarStyle styles[APT_CHART_N],
    int labels_base,
    bool own_peak) {
    uint16_t mx = own_peak ? 1 : 100;
    for(int i = 0; i < APT_CHART_N; i++) {
        uint16_t v = scores[apt_hour_index(apt_chart_hours[i])];
        if(v > mx) mx = v;
    }
    int H = base - top;
    for(int i = 0; i < APT_CHART_N; i++) {
        uint16_t v = scores[apt_hour_index(apt_chart_hours[i])];
        int bh = (int)((v * H + mx / 2) / mx);
        if(bh < 1) bh = 1;
        int x = X0 + i * PITCH;
        switch(styles[i]) {
        case BarSolid:
            canvas_draw_box(c, x, base - bh, BW, bh);
            break;
        case BarHollow:
            if(bh < 3) bh = 3;
            canvas_draw_frame(c, x, base - bh, BW, bh);
            break;
        default:
            dither(c, x, base - bh, BW, bh);
            canvas_draw_line(c, x, base - bh, x + BW - 1, base - bh);
            break;
        }
    }
    canvas_draw_line(c, X0 - 2, base, X0 + APT_CHART_N * PITCH - 1, base);
    canvas_set_custom_u8g2_font(c, apt_font_4x6);
    for(int i = 0; i < APT_CHART_N; i += 3) {
        char h[4];
        snprintf(h, sizeof(h), "%u", apt_chart_hours[i]);
        int w = canvas_string_width(c, h);
        canvas_draw_str(c, X0 + i * PITCH + 2 - w / 2, labels_base, h);
    }
}

static int legend(Canvas* c, const uint8_t* font, int x, int base, BarStyle style, const char* label) {
    if(style == BarSolid)
        canvas_draw_box(c, x, base - 5, 5, 5);
    else
        canvas_draw_frame(c, x, base - 5, 5, 5);
    text(c, font, x + 7, base, label);
    return x + 7 + width(c, font, label) + 6;
}

static void stale(Canvas* c) {
    text(c, apt_font_helvB08, 0, 31, "Prévision périmée.");
    text(c, apt_font_5x7, 0, 44, "Mettez à jour a_point.dat");
    text(c, apt_font_5x7, 0, 53, "(voir le README).");
}

static void draw_now(Canvas* c, const App* app) {
    badges(c, app->lines, app->n_lines);
    rabbit_corner(c);
    name_row(c, app);
    if(!app->scores_ok) {
        stale(c);
        return;
    }
    AptNow f;
    apt_now_facts(app->scores, app->hour, app->data.edges, &f);
    text(c, apt_font_helvB10, 0, 32, HEADLINE[f.band]);
    BarStyle st[APT_CHART_N];
    for(int i = 0; i < APT_CHART_N; i++) {
        uint8_t h = apt_chart_hours[i];
        st[i] = (!f.off_hours && h == f.hour)       ? BarSolid :
                (f.calmer_hour >= 0 && h == f.calmer_hour) ? BarHollow :
                                                        BarDither;
    }
    chart(c, 36, 49, app->scores, st, 55, false);
    int x = 0;
    if(!f.off_hours) x = legend(c, apt_font_5x7, x, 62, BarSolid, "maintenant");
    if(f.calmer_hour >= 0) legend(c, apt_font_5x7, x, 62, BarHollow, "plus calme");
}

static void draw_day(Canvas* c, const App* app) {
    int y, m, d, wd;
    uint16_t day = app->today + app->offset;
    apt_civil(day, &y, &m, &d, &wd);
    char pill[24];
    snprintf(pill, sizeof(pill), "%s %d %s", WDAY[wd], d, MONTH[m - 1]);
    int w = width(c, apt_font_5x7, pill) + 6;
    canvas_draw_rbox(c, 0, 0, w, 9, 1);
    canvas_set_color(c, ColorWhite);
    text(c, apt_font_5x7, 3, 7, pill);
    canvas_set_color(c, ColorBlack);
    rabbit_corner(c);
    name_row(c, app);
    if(!app->scores_ok) {
        stale(c);
        return;
    }
    AptDay f;
    apt_day_facts(app->scores, &f);
    if(!f.has_window) {
        text(c, apt_font_helvB08, 0, 30, "Pas de prévision");
        text(c, apt_font_helvB08, 0, 40, "pour cette date.");
        return;
    }
    char l2[32];
    snprintf(l2, sizeof(l2), "de %u h à %u h.", f.window_from, f.window_to);
    text(c, apt_font_helvB08, 0, 30, "Plus chargé");
    text(c, apt_font_helvB08, 0, 40, l2);
    legend(c, apt_font_4x6, 77, 30, BarSolid, "plus chargé");
    if(f.n_calmest == 2) legend(c, apt_font_4x6, 77, 40, BarHollow, "plus calme");
    BarStyle st[APT_CHART_N];
    for(int i = 0; i < APT_CHART_N; i++) {
        uint8_t h = apt_chart_hours[i];
        st[i] = BarDither;
        for(int k = 0; k < f.n_busiest; k++)
            if(f.busiest[k] == h) st[i] = BarSolid;
        if(f.n_calmest == 2 && (f.calmest[0] == h || f.calmest[1] == h)) st[i] = BarHollow;
    }
    chart(c, 44, 56, app->scores, st, 63, true);
}

static void row(Canvas* c, int i, bool selected, const char* left, const char* right, bool star) {
    int y = 12 + i * 13;
    if(selected) canvas_draw_rbox(c, 0, y, 128, 12, 1);
    canvas_set_color(c, selected ? ColorWhite : ColorBlack);
    int rw = right ? width(c, apt_font_5x7, right) : 0;
    int lx = star ? 10 : 3;
    if(star) canvas_draw_xbm(c, 3, y + 4, 5, 5, star_bits);
    char buf[64];
    text(c, apt_font_helvR08, lx, y + 9, fit(c, apt_font_helvR08, left, 125 - lx - rw - (right ? 4 : 0), buf, sizeof(buf)));
    if(right) text(c, apt_font_5x7, 125 - rw, y + 9, right);
    canvas_set_color(c, ColorBlack);
}

static void draw_favs(Canvas* c, const App* app) {
    text(c, apt_font_helvB08, 0, 9, "Vos gares");
    rabbit_corner(c);
    int n = app->data.n_favs + 1;
    for(int r = 0; r < LIST_ROWS && app->fav_top + r < n; r++) {
        int i = app->fav_top + r;
        bool sel = i == app->fav_sel;
        if(i < app->data.n_favs) {
            int8_t b = app->fav_band[i];
            row(c, r, sel, apt_place_name(&app->data, app->data.favs[i]), b >= 0 ? BAND[b] : "-", false);
        } else {
            row(c, r, sel, "Toutes les gares", ">", false);
        }
    }
    if(app->data.n_favs == 0) {
        text(c, apt_font_5x7, 3, 38, "Pour ajouter un favori :");
        text(c, apt_font_5x7, 3, 47, "appui long sur OK");
        text(c, apt_font_5x7, 3, 56, "sur une gare.");
    }
}

static void draw_all(Canvas* c, const App* app) {
    text(c, apt_font_helvB08, 0, 9, "Toutes les gares");
    char pos[16];
    snprintf(pos, sizeof(pos), "%d/%u", app->all_sel + 1, app->data.n_places);
    text(c, apt_font_4x6, 126 - width(c, apt_font_4x6, pos), 8, pos);
    for(int r = 0; r < LIST_ROWS && app->all_top + r < app->data.n_places; r++) {
        int i = app->all_top + r;
        row(c, r, i == app->all_sel, apt_place_name(&app->data, i), NULL, apt_fav_index(&app->data, i) >= 0);
    }
}

static void draw_boot(Canvas* c, const App* app) {
    canvas_draw_xbm(c, 9, 14, 25, 38, rabbit_big_bits);
    text(c, apt_font_helvB12, 46, 30, "à point");
    if(app->status == AptOk && app->data.issue_day) {
        int y, m, d, wd;
        apt_civil(app->data.issue_day, &y, &m, &d, &wd);
        char s[24];
        snprintf(s, sizeof(s), "du %d %s", d, MONTH[m - 1]);
        text(c, apt_font_5x7, 47, 41, "Prévision");
        text(c, apt_font_5x7, 47, 49, s);
    }
    text(c, apt_font_4x6, 47, 61, "Données : IDFM, ODbL");
}

static void draw_error(Canvas* c, const App* app) {
    const char* title = app->status == AptNoFile   ? "Fichier introuvable" :
                        app->status == AptNoMemory ? "Mémoire insuffisante" :
                                                     "Fichier illisible";
    text(c, apt_font_helvB08, 0, 10, title);
    text(c, apt_font_5x7, 0, 24, "Copiez a_point.dat dans");
    text(c, apt_font_5x7, 0, 33, "SD/apps_data/a_point/");
    text(c, apt_font_5x7, 0, 46, "Fichier : make flipper");
    text(c, apt_font_5x7, 0, 55, "(voir le README).");
}

static void draw_toast(Canvas* c, const char* msg) {
    int w = width(c, apt_font_5x7, msg) + 12;
    int x = (128 - w) / 2;
    canvas_set_color(c, ColorWhite);
    canvas_draw_rbox(c, x - 1, 22, w + 2, 18, 3);
    canvas_set_color(c, ColorBlack);
    canvas_draw_rframe(c, x, 23, w, 16, 3);
    text(c, apt_font_5x7, x + 6, 34, msg);
}

void app_draw(Canvas* canvas, void* ctx) {
    App* app = ctx;
    furi_mutex_acquire(app->mutex, FuriWaitForever);
    canvas_clear(canvas);
    canvas_set_color(canvas, ColorBlack);
    switch(app->screen) {
    case ScreenBoot:
        draw_boot(canvas, app);
        break;
    case ScreenError:
        draw_error(canvas, app);
        break;
    case ScreenFavs:
        draw_favs(canvas, app);
        break;
    case ScreenAll:
        draw_all(canvas, app);
        break;
    case ScreenStation:
        if(app->offset == 0)
            draw_now(canvas, app);
        else
            draw_day(canvas, app);
        break;
    }
    if(app->toast && furi_get_tick() < app->toast_until) draw_toast(canvas, app->toast);
    furi_mutex_release(app->mutex);
}
