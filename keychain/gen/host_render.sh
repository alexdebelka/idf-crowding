#!/bin/sh
# Builds gen/host_render (needs a C and a C++17 compiler, and ArduinoJson 7).
# ARDUINOJSON: folder holding ArduinoJson.h (e.g. a clone of bblanchon/ArduinoJson, its src/).
set -e
cd "$(dirname "$0")"
cc -O2 -c ../apoint/aptqr.c -o aptqr.o
c++ -std=c++17 -O2 -Wall -Wextra -Wno-missing-field-initializers -I"${ARDUINOJSON:?set ARDUINOJSON}" \
  -o host_render host_render.cpp ../apoint/gfx.cpp ../apoint/screens.cpp ../apoint/model.cpp \
  ../apoint/logic.cpp aptqr.o
rm -f aptqr.o
