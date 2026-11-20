// "à point" for Flipper Zero: crowding forecast of Île-de-France stations, read from the SD card.
// Buttons: Up/Down = previous/next station, Left/Right = today/next dates, OK = list,
// long OK = add/remove favourite, Back = list, then exit.
#include <furi.h>
#include <furi_hal_rtc.h>
#include <datetime/datetime.h>
#include <gui/gui.h>
#include <input/input.h>
#include <storage/storage.h>

#include "app.h"

#define BOOT_MS  1200
#define TOAST_MS 1200

static void input_cb(InputEvent* event, void* ctx) {
    furi_message_queue_put(ctx, event, FuriWaitForever);
}

/* Paris local time is what the Flipper's clock holds (set from the phone or qFlipper). */
static void read_clock(App* app) {
    DateTime dt;
    furi_hal_rtc_get_datetime(&dt);
    uint16_t day = (uint16_t)(datetime_datetime_to_timestamp(&dt) / 86400u);
    app->hour = dt.hour;
    app->today = dt.hour < 4 ? day - 1 : day; /* operating day */
}

static void load_station(App* app) {
    app->n_lines = apt_place_lines(&app->data, app->place, app->lines, APT_MAX_LINES);
    app->scores_ok = apt_place_scores(&app->data, app->place, app->today + app->offset, app->scores);
}

static void load_fav_bands(App* app) {
    for(uint8_t i = 0; i < app->data.n_favs; i++) {
        int s = apt_place_score_at(&app->data, app->data.favs[i], app->today, app->hour);
        app->fav_band[i] = s < 0 ? -1 : (int8_t)apt_band((uint16_t)s, app->data.edges);
    }
}

static void clamp_list(int16_t* sel, int16_t* top, int n) {
    if(n <= 0) {
        *sel = *top = 0;
        return;
    }
    if(*sel < 0) *sel = n - 1; /* wrap */
    if(*sel >= n) *sel = 0;
    if(*sel < *top) *top = *sel;
    if(*sel >= *top + LIST_ROWS) *top = *sel - LIST_ROWS + 1;
}

static char initial(const char* s) {
    uint8_t a = (uint8_t)s[0], b = (uint8_t)s[1];
    if(a == 0xC3) { /* Latin-1 letters with accents, upper and lower case */
        b &= ~0x20;
        if(b >= 0x80 && b <= 0x85) return 'A';
        if(b == 0x87) return 'C';
        if(b >= 0x88 && b <= 0x8B) return 'E';
        if(b >= 0x8C && b <= 0x8F) return 'I';
        if(b >= 0x92 && b <= 0x96) return 'O';
        if(b >= 0x99 && b <= 0x9C) return 'U';
        return '?';
    }
    return (a >= 'a' && a <= 'z') ? (char)(a - 32) : (char)a;
}

/* Next (dir = 1) or previous (dir = -1) first letter in the alphabetical list. */
static int16_t jump_letter(const App* app, int16_t from, int dir) {
    int n = app->data.n_places;
    char cur = initial(apt_place_name(&app->data, from));
    int i = from;
    if(dir > 0) {
        while(i < n && initial(apt_place_name(&app->data, i)) == cur)
            i++;
        return i < n ? i : 0;
    }
    /* back: to the start of this letter, or of the previous one if already there */
    if(i > 0 && initial(apt_place_name(&app->data, i - 1)) != cur) {
        i--;
        cur = initial(apt_place_name(&app->data, i));
    } else if(i == 0) {
        i = n - 1;
        cur = initial(apt_place_name(&app->data, i));
    }
    while(i > 0 && initial(apt_place_name(&app->data, i - 1)) == cur)
        i--;
    return i;
}

static void toast(App* app, const char* msg) {
    app->toast = msg;
    app->toast_until = furi_get_tick() + furi_ms_to_ticks(TOAST_MS);
}

static void toggle_fav(App* app, uint16_t place) {
    int before = app->data.n_favs;
    bool now = apt_fav_toggle(&app->data, place);
    if(!now && app->data.n_favs == before)
        toast(app, "16 favoris au plus.");
    else
        toast(app, now ? "Ajoutée aux favoris." : "Retirée des favoris.");
    load_fav_bands(app);
}

static void open_station(App* app, uint16_t place, bool from_favs) {
    app->place = place;
    app->from_favs = from_favs;
    app->offset = 0;
    app->screen = ScreenStation;
    load_station(app);
}

static int max_offset(const App* app) {
    int last = (int)app->data.first_day + app->data.n_days - 1 - (int)app->today;
    return last > 0 ? last : 0;
}

/* Returns false to exit. */
static bool on_input(App* app, const InputEvent* e) {
    bool press = e->type == InputTypeShort || e->type == InputTypeRepeat;
    bool long_ok = e->type == InputTypeLong && e->key == InputKeyOk;
    if(app->screen == ScreenBoot) {
        if(e->type == InputTypeShort) app->boot_until = 0;
        return true;
    }
    if(app->screen == ScreenError) return !(e->type == InputTypeShort && e->key == InputKeyBack);

    if(app->screen == ScreenFavs) {
        int n = app->data.n_favs + 1;
        if(press && e->key == InputKeyUp) app->fav_sel--;
        if(press && e->key == InputKeyDown) app->fav_sel++;
        clamp_list(&app->fav_sel, &app->fav_top, n);
        bool on_fav = app->fav_sel < app->data.n_favs;
        if(e->type == InputTypeShort && e->key == InputKeyOk) {
            if(on_fav)
                open_station(app, app->data.favs[app->fav_sel], true);
            else
                app->screen = ScreenAll;
        }
        if(long_ok && on_fav) {
            toggle_fav(app, app->data.favs[app->fav_sel]);
            clamp_list(&app->fav_sel, &app->fav_top, app->data.n_favs + 1);
        }
        if(e->type == InputTypeShort && e->key == InputKeyBack) return false;
        return true;
    }

    if(app->screen == ScreenAll) {
        int n = app->data.n_places;
        if(press && e->key == InputKeyUp) app->all_sel--;
        if(press && e->key == InputKeyDown) app->all_sel++;
        if(press && e->key == InputKeyRight) app->all_sel = jump_letter(app, app->all_sel, 1);
        if(press && e->key == InputKeyLeft) app->all_sel = jump_letter(app, app->all_sel, -1);
        clamp_list(&app->all_sel, &app->all_top, n);
        if(e->type == InputTypeShort && e->key == InputKeyOk) open_station(app, app->all_sel, false);
        if(long_ok) toggle_fav(app, app->all_sel);
        if(e->type == InputTypeShort && e->key == InputKeyBack) app->screen = ScreenFavs;
        return true;
    }

    /* station */
    if(press && (e->key == InputKeyUp || e->key == InputKeyDown)) {
        int step = e->key == InputKeyDown ? 1 : -1;
        if(app->from_favs && app->data.n_favs > 0) {
            int i = apt_fav_index(&app->data, app->place);
            i = i < 0 ? 0 : (i + step + app->data.n_favs) % app->data.n_favs;
            app->place = app->data.favs[i];
            app->fav_sel = (int16_t)i;
            clamp_list(&app->fav_sel, &app->fav_top, app->data.n_favs + 1);
        } else {
            app->place = (uint16_t)((app->place + step + app->data.n_places) % app->data.n_places);
            app->all_sel = (int16_t)app->place;
            clamp_list(&app->all_sel, &app->all_top, app->data.n_places);
        }
        load_station(app);
    }
    if(press && e->key == InputKeyRight && app->offset < max_offset(app)) {
        app->offset++;
        load_station(app);
    }
    if(press && e->key == InputKeyLeft && app->offset > 0) {
        app->offset--;
        load_station(app);
    }
    if(long_ok) toggle_fav(app, app->place);
    if(e->type == InputTypeShort && (e->key == InputKeyOk || e->key == InputKeyBack)) {
        app->screen = app->from_favs ? ScreenFavs : ScreenAll;
        load_fav_bands(app);
    }
    return true;
}

int32_t a_point_main(void* p) {
    UNUSED(p);
    App* app = malloc(sizeof(App));
    memset(app, 0, sizeof(App));
    app->mutex = furi_mutex_alloc(FuriMutexTypeNormal);
    FuriMessageQueue* queue = furi_message_queue_alloc(8, sizeof(InputEvent));

    Storage* storage = furi_record_open(RECORD_STORAGE);
    app->status = apt_data_open(&app->data, storage);
    read_clock(app);
    if(app->status == AptOk) load_fav_bands(app);
    app->screen = ScreenBoot;
    app->boot_until = furi_get_tick() + furi_ms_to_ticks(BOOT_MS);

    ViewPort* vp = view_port_alloc();
    view_port_draw_callback_set(vp, app_draw, app);
    view_port_input_callback_set(vp, input_cb, queue);
    Gui* gui = furi_record_open(RECORD_GUI);
    gui_add_view_port(gui, vp, GuiLayerFullscreen);

    bool running = true;
    InputEvent e;
    while(running) {
        bool got = furi_message_queue_get(queue, &e, 250) == FuriStatusOk;
        furi_mutex_acquire(app->mutex, FuriWaitForever);
        if(got) running = on_input(app, &e);
        if(app->screen == ScreenBoot && furi_get_tick() >= app->boot_until)
            app->screen = app->status == AptOk ? ScreenFavs : ScreenError;
        /* new hour or new operating day: reload what is on screen */
        uint16_t day = app->today;
        uint8_t hour = app->hour;
        read_clock(app);
        if(app->status == AptOk && (day != app->today || hour != app->hour)) {
            if(day != app->today) app->offset = 0;
            load_fav_bands(app);
            if(app->screen == ScreenStation) load_station(app);
        }
        if(app->toast && furi_get_tick() >= app->toast_until) app->toast = NULL;
        furi_mutex_release(app->mutex);
        view_port_update(vp);
    }

    gui_remove_view_port(gui, vp);
    view_port_free(vp);
    furi_record_close(RECORD_GUI);
    apt_data_close(&app->data);
    furi_record_close(RECORD_STORAGE);
    furi_message_queue_free(queue);
    furi_mutex_free(app->mutex);
    free(app);
    return 0;
}
