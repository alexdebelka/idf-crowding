#include "data.h"

#include <furi.h>
#include <stdlib.h>
#include <string.h>

#define HEADER_SIZE 26
#define MAX_INDEX   (60u * 1024u)

static uint16_t rd16(const uint8_t* p) {
    return (uint16_t)(p[0] | (p[1] << 8));
}

static uint32_t rd32(const uint8_t* p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static bool read_at(AptData* d, uint32_t off, void* buf, size_t n) {
    if(!storage_file_seek(d->file, off, true)) return false;
    return storage_file_read(d->file, buf, n) == n;
}

static int find_id(const AptData* d, uint32_t id) {
    for(uint16_t i = 0; i < d->n_places; i++)
        if(d->places[i].id == id) return i;
    return -1;
}

static void favs_load(AptData* d) {
    d->n_favs = 0;
    File* f = storage_file_alloc(d->storage);
    if(storage_file_open(f, APT_FAVS_PATH, FSAM_READ, FSOM_OPEN_EXISTING)) {
        char buf[16 * 12 + 1];
        size_t n = storage_file_read(f, buf, sizeof(buf) - 1);
        buf[n] = '\0';
        char* p = buf;
        while(*p && d->n_favs < APT_MAX_FAVS) {
            uint32_t id = (uint32_t)strtoul(p, &p, 10);
            int i = find_id(d, id);
            if(i >= 0 && apt_fav_index(d, i) < 0) d->favs[d->n_favs++] = (uint16_t)i;
            while(*p && (*p < '0' || *p > '9'))
                p++;
        }
    }
    storage_file_close(f);
    storage_file_free(f);
}

static void favs_save(AptData* d) {
    storage_simply_mkdir(d->storage, APT_DIR);
    File* f = storage_file_alloc(d->storage);
    if(storage_file_open(f, APT_FAVS_PATH, FSAM_WRITE, FSOM_CREATE_ALWAYS)) {
        char line[12];
        for(uint8_t i = 0; i < d->n_favs; i++) {
            int n = snprintf(line, sizeof(line), "%lu\n", (unsigned long)d->places[d->favs[i]].id);
            storage_file_write(f, line, n);
        }
    }
    storage_file_close(f);
    storage_file_free(f);
}

AptStatus apt_data_open(AptData* d, Storage* storage) {
    memset(d, 0, sizeof(*d));
    d->storage = storage;
    d->file = storage_file_alloc(storage);
    if(!storage_file_open(d->file, APT_DATA_PATH, FSAM_READ, FSOM_OPEN_EXISTING)) return AptNoFile;

    uint8_t h[HEADER_SIZE];
    if(!read_at(d, 0, h, sizeof(h))) return AptBadFile;
    if(memcmp(h, "APT1", 4) != 0 || h[4] != 1 || h[5] != APT_HOURS || h[6] != APT_FIRST_HOUR)
        return AptBadFile;
    d->divisor = h[7] ? h[7] : 1;
    d->first_day = rd16(h + 8);
    d->n_days = rd16(h + 10);
    d->issue_day = rd16(h + 12);
    d->data_end_day = rd16(h + 14);
    memcpy(d->edges, h + 16, 3);
    d->n_places = rd16(h + 20);
    d->scores_off = rd32(h + 22);

    uint32_t idx_size = d->scores_off - HEADER_SIZE;
    uint64_t need = (uint64_t)d->scores_off + (uint64_t)d->n_places * d->n_days * APT_HOURS;
    if(d->scores_off < HEADER_SIZE || idx_size > MAX_INDEX || d->n_places == 0 ||
       storage_file_size(d->file) < need)
        return AptBadFile;

    d->index = malloc(idx_size);
    d->places = malloc(sizeof(AptPlace) * d->n_places);
    d->names = malloc(idx_size); /* names + NULs never exceed the index itself */
    if(!d->index || !d->places || !d->names) return AptNoMemory;
    if(!read_at(d, HEADER_SIZE, d->index, idx_size)) return AptBadFile;

    uint32_t p = 0, q = 0;
    for(uint16_t i = 0; i < d->n_places; i++) {
        if(p + 6 > idx_size) return AptBadFile;
        d->places[i].id = rd32(d->index + p);
        uint8_t nl = d->index[p + 4];
        p += 5;
        if(p + nl + 1 > idx_size) return AptBadFile;
        d->places[i].name = (uint16_t)q;
        memcpy(d->names + q, d->index + p, nl);
        q += nl;
        d->names[q++] = '\0';
        p += nl;
        d->places[i].lines = (uint16_t)p;
        uint8_t n_lines = d->index[p++];
        for(uint8_t k = 0; k < n_lines; k++) {
            if(p + 2 > idx_size) return AptBadFile;
            p += 2 + d->index[p + 1];
        }
        if(p > idx_size) return AptBadFile;
    }
    favs_load(d);
    return AptOk;
}

void apt_data_close(AptData* d) {
    if(d->file) {
        storage_file_close(d->file);
        storage_file_free(d->file);
    }
    free(d->index);
    free(d->names);
    free(d->places);
    memset(d, 0, sizeof(*d));
}

const char* apt_place_name(const AptData* d, uint16_t place) {
    return d->names + d->places[place].name;
}

uint8_t apt_place_lines(const AptData* d, uint16_t place, AptLine* out, uint8_t max) {
    const uint8_t* p = d->index + d->places[place].lines;
    uint8_t n = *p++, got = 0;
    for(uint8_t k = 0; k < n; k++) {
        uint8_t kind = p[0], len = p[1];
        if(got < max) {
            out[got].kind = kind;
            uint8_t c = len < sizeof(out[got].name) - 1 ? len : sizeof(out[got].name) - 1;
            memcpy(out[got].name, p + 2, c);
            out[got].name[c] = '\0';
            got++;
        }
        p += 2 + len;
    }
    return got;
}

static uint32_t day_offset(const AptData* d, uint16_t place, uint16_t day) {
    return d->scores_off + ((uint32_t)place * d->n_days + (uint32_t)(day - d->first_day)) * APT_HOURS;
}

bool apt_place_scores(AptData* d, uint16_t place, uint16_t day, uint16_t out[APT_HOURS]) {
    if(day < d->first_day || day >= d->first_day + d->n_days) return false;
    uint8_t raw[APT_HOURS];
    if(!read_at(d, day_offset(d, place, day), raw, sizeof(raw))) return false;
    for(int i = 0; i < APT_HOURS; i++)
        out[i] = (uint16_t)raw[i] * d->divisor;
    return true;
}

int apt_place_score_at(AptData* d, uint16_t place, uint16_t day, uint8_t hour) {
    if(day < d->first_day || day >= d->first_day + d->n_days) return -1;
    uint8_t v;
    uint32_t off = day_offset(d, place, day) + (uint32_t)((hour + 24 - APT_FIRST_HOUR) % 24);
    if(!read_at(d, off, &v, 1)) return -1;
    return v * d->divisor;
}

int apt_fav_index(const AptData* d, uint16_t place) {
    for(uint8_t i = 0; i < d->n_favs; i++)
        if(d->favs[i] == place) return i;
    return -1;
}

bool apt_fav_toggle(AptData* d, uint16_t place) {
    int i = apt_fav_index(d, place);
    bool now_fav;
    if(i >= 0) {
        memmove(&d->favs[i], &d->favs[i + 1], (d->n_favs - i - 1) * sizeof(d->favs[0]));
        d->n_favs--;
        now_fav = false;
    } else if(d->n_favs < APT_MAX_FAVS) {
        d->favs[d->n_favs++] = place;
        now_fav = true;
    } else {
        return false;
    }
    favs_save(d);
    return now_fav;
}
