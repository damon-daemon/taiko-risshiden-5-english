#!/bin/bash
# hnewgame.sh image.iso out.png : headless run from boot to the first event dialogue
# (new game, first scenario/hero, default settings); screenshot of the first line
D=$(cd "$(dirname "$0")" && pwd)
"$D/headless.sh" stop; timeout 2 tail -f /dev/null
"$D/headless.sh" "$1"; timeout 30 tail -f /dev/null
"$D/hpress.sh" /dev/null Return w w w Return w w w
"$D/hpress.sh" /dev/null X w w X w w X w w w X w w w X w w X w w w w
"$D/hpress.sh" /dev/null w w w w w w Down Down Down Down Down Down Down X w w
"$D/hpress.sh" /dev/null Down Down Down Down Down Down Down X
timeout 18 tail -f /dev/null
"$D/hpress.sh" /dev/null X w w w w w
"$D/hshot.sh" "$2"
