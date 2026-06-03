#!/usr/bin/env bash
# =====================================================================
# run_robot.sh — Birlesik sistemi TEK komutla baslatir
#
#   1) robot_server.py (kamera + YOLO + VLM) arka planda baslar
#   2) socket hazir olunca ./pi/main (orkestrator + Arduino serial) on planda calisir
#   3) main cikinca sunucu otomatik kapatilir
#
# main calisirken Arduino'dan "MARKER" bekler (sol sensor siyah bant okuyunca):
#   MARKER -> kamera+YOLO+VLM -> karar -> LASER/PUMP -> RESUME -> sonraki bant
# Arduino bagli degilse main DEMO moduna duser (Enter = istasyon simule).
#
# Kullanim:
#   ./run_robot.sh
#
# Sunucu loglari:  /tmp/robot_server.log  (canli izlemek icin: tail -f)
# =====================================================================
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$ROOT/src"
PI="$ROOT/pi"
SOCK="/tmp/robot_ipc.sock"
LOG="/tmp/robot_server.log"
VENV="$HOME/agroai-env/bin/activate"

# --- venv ---
if [ -f "$VENV" ]; then
    # shellcheck disable=SC1090
    source "$VENV"
else
    echo "[run] UYARI: $VENV bulunamadi, sistem python kullanilacak."
fi

# --- orkestrator binary'sini gerekiyorsa derle ---
if [ ! -x "$PI/main" ] || [ "$PI/main.cpp" -nt "$PI/main" ]; then
    echo "[run] main derleniyor..."
    make -C "$PI" main
fi

# --- vision sunucusunu arka planda baslat ---
echo "[run] vision sunucusu baslatiliyor (loglar: $LOG)..."
python3 "$SRC/robot_server.py" > "$LOG" 2>&1 &
SERVER_PID=$!

cleanup() {
    echo ""
    echo "[run] kapatiliyor..."
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    rm -f "$SOCK"
}
trap cleanup INT TERM EXIT

# --- socket hazir olana kadar bekle (model + kamera yukleme ~15-25s) ---
echo "[run] model + kamera yukleniyor, hazir olmasi bekleniyor..."
for _ in $(seq 1 90); do
    if [ -S "$SOCK" ]; then break; fi
    # sunucu erken oldu mu kontrol et
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "[run] HATA: sunucu baslarken coktu. Son loglar:"
        tail -n 20 "$LOG"
        exit 1
    fi
    sleep 1
done

if [ ! -S "$SOCK" ]; then
    echo "[run] HATA: sunucu zamaninda hazir olmadi. Son loglar:"
    tail -n 20 "$LOG"
    exit 1
fi

echo "[run] sunucu HAZIR. Orkestrator baslatiliyor."
echo "----------------------------------------------------------"
"$PI/main"
# cleanup trap ile sunucu kapatilir
