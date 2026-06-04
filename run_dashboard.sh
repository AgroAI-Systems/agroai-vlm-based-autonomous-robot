#!/usr/bin/env bash
# =====================================================================
# run_dashboard.sh — AgroAI canli izleme panelini baslatir
#
#   Robot kodunu HIC degistirmez. Sadece su dosyalari okur:
#     /tmp/robot_server.log, src/camera_captures/, src/vlm_crops/,
#     src/vlm_output.json
#
#   Sadece Python standart kutuphanesi kullanir (pip install GEREKMEZ).
#
# Kullanim:
#   ./run_dashboard.sh            # port 8000
#   ./run_dashboard.sh 8080       # ozel port
#
# Ardindan telefon/laptop tarayicidan ac:
#   http://<pi-ip>:<port>     (Pi IP'si:  hostname -I)
#
# Ipucu: robotu ./run_robot.sh ile, paneli bu betikle AYRI terminalde
#        ayni anda calistir.
# =====================================================================
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8000}"
exec python3 "$ROOT/src/dashboard.py" --port "$PORT"
