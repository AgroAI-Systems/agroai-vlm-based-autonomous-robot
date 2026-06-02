"""
demo.py — MOD-03 (VLM) interaktif demo

Mock VLM ile simule edilmis bir tarla missionunu adim adim oynatir.
Her bitki icin YOLO ciktisi + (gerekirse) VLM cagrisi gosterilir.
Demoda izleyiciye gate'in nasil calistigini gostermek icin idealdir.

Kullanim:
    python demo.py                   # 12 bitki, varsayilan
    python demo.py --plants 20       # bitki sayisi
    python demo.py --slow            # ekrandan okumak icin yavasla

Geliştirici: Bekir Göktepe (220104004018)
Modül: MOD-03 — VLM Plant Analysis (CSE396 — Group 9)
"""

import argparse
import random
import sys
import time
from unittest.mock import patch

import vlm_engine
from mock_vlm import SCENARIOS, MockVlmEngine
from vlm_types import (
    YOLO_CLASS_DISEASED,
    YOLO_CLASS_HEALTHY,
    YOLO_CLASS_UNKNOWN,
    YOLO_CLASS_WEED,
    YOLO_VLM_TRIGGER_THRESHOLD,
    VlmImage,
    VlmStatus,
)


_YOLO_LABELS = {
    YOLO_CLASS_HEALTHY:  "HEALTHY",
    YOLO_CLASS_DISEASED: "DISEASED",
    YOLO_CLASS_WEED:     "WEED",
    YOLO_CLASS_UNKNOWN:  "UNKNOWN",
}


def _generate_field(n: int, seed: int = 7) -> list[tuple[int, float, str]]:
    """
    n bitkilik bir tarla uret. Her bitki: (yolo_class, yolo_conf, mock_scenario).

    Karisik bir set:
      - %60 yuksek-guven (YOLO bypass tetiklenecek)
      - %30 dusuk-guven (VLM cagrilacak)
      - %10 YOLO siniflandiramamis (UNKNOWN → her zaman VLM)
    """
    rng = random.Random(seed)
    classes = [YOLO_CLASS_HEALTHY, YOLO_CLASS_DISEASED, YOLO_CLASS_WEED]
    field: list[tuple[int, float, str]] = []
    for i in range(n):
        roll = rng.random()
        if roll < 0.60:
            cls = rng.choice(classes)
            conf = rng.uniform(0.78, 0.97)
            scenario = "valid_healthy"  # bypass'ta kullanilmaz
        elif roll < 0.90:
            cls = rng.choice(classes)
            conf = rng.uniform(0.30, 0.70)
            # Dusuk guvende VLM'in verecegi cevap (model "second opinion")
            scenario = rng.choice([
                "valid_healthy", "valid_diseased", "valid_weed",
                "low_confidence", "hallucinated",
            ])
        else:
            cls = YOLO_CLASS_UNKNOWN
            conf = rng.uniform(0.10, 0.40)
            scenario = rng.choice(["valid_diseased", "wrong_enum", "free_text_only"])
        field.append((cls, conf, scenario))
    return field


def _make_image(yolo_class: int, yolo_conf: float) -> VlmImage:
    return VlmImage(
        data            = b"\x00" * (378 * 378 * 3),
        width           = 378,
        height          = 378,
        stride           = 378 * 3,
        timestamp_ms    = int(time.time() * 1000),
        yolo_class_id   = yolo_class,
        yolo_confidence = yolo_conf,
    )


def _print_header():
    print()
    print("+" + "-" * 78 + "+")
    print("|  MOD-03 VLM — TARLA MISSION DEMOSU (mock VLM ile)" + " " * 28 + "|")
    print("+" + "-" * 78 + "+")
    print()
    print(f"  YOLO bypass esigi: conf >= {YOLO_VLM_TRIGGER_THRESHOLD}")
    print()
    print(f"  {'#':>3}  {'YOLO sinif':<10} {'conf':>5}  {'->':<3} "
          f"{'sonuc':<10} {'action':<6} {'sev':<6} {'ms':>5}  not")
    print("  " + "-" * 76)


def _print_row(idx, yolo_label, yolo_conf, plant_status_name,
               action_name, severity_name, inf_ms, note):
    print(f"  {idx:>3}  {yolo_label:<10} {yolo_conf:>5.2f}  -->  "
          f"{plant_status_name:<10} {action_name:<6} {severity_name:<6} "
          f"{inf_ms:>5d}  {note}")


def main() -> int:
    ap = argparse.ArgumentParser(description="MOD-03 VLM demo")
    ap.add_argument("--plants", type=int, default=12)
    ap.add_argument("--slow", action="store_true",
                    help="Adimlar arasinda 0.5 sn bekle (sunum modu)")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    field = _generate_field(args.plants, args.seed)

    # Engine'i hazir gibi gostermek + her bitki icin mock'u guncellemek
    bypassed = 0
    vlm_called = 0

    _print_header()

    for idx, (yolo_cls, yolo_conf, scenario) in enumerate(field, start=1):
        engine = MockVlmEngine(scenario=scenario, simulate_latency_ms=0)

        def fake_inference(pil, prompt, _engine=engine):
            return _engine.run_inference(None, prompt)

        with patch.object(vlm_engine, "_is_initialized", True), \
             patch.object(vlm_engine, "_model", object()), \
             patch.object(vlm_engine, "run_moondream_inference", fake_inference):

            img = _make_image(yolo_cls, yolo_conf)
            status, result = vlm_engine.vlm_analyze_plant(img)

        if engine.call_count == 0:
            bypassed += 1
            note = "YOLO bypass"
        else:
            vlm_called += 1
            note = f"VLM cagrildi (mock={scenario})"
            if status != VlmStatus.OK:
                note += f" PARSE_FAIL"

        _print_row(
            idx               = idx,
            yolo_label        = _YOLO_LABELS.get(yolo_cls, "??"),
            yolo_conf         = yolo_conf,
            plant_status_name = result.status.name,
            action_name       = result.action.name,
            severity_name     = result.severity.name,
            inf_ms            = result.inference_time_ms,
            note              = note,
        )

        if args.slow:
            time.sleep(0.5)

    print("  " + "-" * 76)
    print()
    print(f"  Ozet: toplam={args.plants}  YOLO_bypass={bypassed}  VLM_cagrildi={vlm_called}")
    if args.plants > 0:
        print(f"        bypass orani = %{bypassed / args.plants * 100:.0f}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
