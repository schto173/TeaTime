#!/bin/sh
# Builds the Windows plugin (build/teatime_plugin.dll) with MinGW-w64.
#   Linux / WSL:   sudo apt install gcc-mingw-w64-x86-64 && sh build.sh
#   Windows:       in an MSYS2 "MinGW64" shell: pacman -S mingw-w64-x86_64-gcc && sh build.sh
# Then package it:  python3 package.py   (creates ../dist/TeaTime.mumble_plugin)
set -e
CC="${CC:-x86_64-w64-mingw32-gcc}"
mkdir -p build
"$CC" -std=gnu11 -O2 -Wall -Wextra -shared \
  -DMUMBLE_PLUGIN_API_MAJOR_MACRO=1 -DMUMBLE_PLUGIN_API_MINOR_MACRO=0 -DMUMBLE_PLUGIN_API_PATCH_MACRO=0 \
  teatime_plugin.c -o build/teatime_plugin.dll \
  -static -static-libgcc -lm
echo "built build/teatime_plugin.dll"
