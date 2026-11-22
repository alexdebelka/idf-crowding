// a_point.dat reader (format: src/idf_crowding/score/flipper.py) and the favourites file.
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include <storage/storage.h>

#define APT_DIR       EXT_PATH("apps_data/a_point")
#define APT_DATA_PATH APT_DIR "/a_point.dat"
#define APT_FAVS_PATH APT_DIR "/favoris.txt"

#define APT_HOURS      24 /* operating day 04 h ... 03 h */
#define APT_FIRST_HOUR 4
#define APT_MAX_LINES  12
#define APT_MAX_FAVS   16

typedef enum {
    AptLineMetro = 0,
    AptLineRer = 1,
    AptLineTransilien = 2,
    AptLineTram = 3,
    AptLineOther = 4,
} AptLineKind;

typedef struct {
    uint8_t kind;
    char name[9];
} AptLine;

typedef struct {
    uint32_t id;
    uint16_t name; /* offset in AptData.names */
    uint16_t lines; /* offset of the line count in AptData.index */
} AptPlace;

typedef enum {
    AptOk,
    AptNoFile,
    AptBadFile,
    AptNoMemory,
} AptStatus;

typedef struct {
    Storage* storage;
    File* file;
    uint8_t divisor;
    uint16_t first_day; /* days since 1970-01-01 */
    uint16_t n_days;
    uint16_t issue_day;
    uint16_t data_end_day;
    uint8_t edges[3]; /* moderate, busy, very busy from (score units) */
    uint16_t n_places;
    uint32_t scores_off;
    uint8_t* index;
    char* names;
    AptPlace* places;
    uint16_t favs[APT_MAX_FAVS]; /* place indexes */
    uint8_t n_favs;
} AptData;

AptStatus apt_data_open(AptData* d, Storage* storage);
void apt_data_close(AptData* d);

const char* apt_place_name(const AptData* d, uint16_t place);
uint8_t apt_place_lines(const AptData* d, uint16_t place, AptLine* out, uint8_t max);
/* 24 scores (score units) of a date given as a day number; false outside the file. */
bool apt_place_scores(AptData* d, uint16_t place, uint16_t day, uint16_t out[APT_HOURS]);
/* Score at one clock hour; -1 outside the file or on a read error. */
int apt_place_score_at(AptData* d, uint16_t place, uint16_t day, uint8_t hour);

int apt_fav_index(const AptData* d, uint16_t place);
/* Adds or removes, saves the file. Returns true when the place is now a favourite. */
bool apt_fav_toggle(AptData* d, uint16_t place);
