"""
benchmark.py — YOLO bypass mimarisinin Pi 4 kazanc simulasyonu

Mock VLM ile Pi 4 inference suresini taklit ederek (simulate_latency_ms=30000)
"hepsi VLM" vs "YOLO bypass aktif" iki senaryoyu kosturur ve toplam mission
suresini karsilastirir. Demo sunumunda somut sayi vermek icin.

Kullanim:
    python benchmark.py [--plants N] [--vlm-ms MS] [--high-conf-ratio R]

Ornek (varsayilan):
    python benchmark.py
    -> 50 bitki, Pi 4 simulasyonu (30s VLM), %75'i YOLO yuksek guvenli

Ornek (saha kosulu):
    python benchmark.py --plants 100 --vlm-ms 35000 --high-conf-ratio 0.80

Bu script gercek modeli CAGIRMAZ — sadece zamanlama matematigi yapar
(MockVlmEngine.simulate_latency_ms sleep'i). Hizli kosar (~10-20 sn).

Geliştirici: Bekir Göktepe (220104004018)
Modül: MOD-03 — VLM Plant Analysis (CSE396 — Group 9)
"""

import argparse
import random
import sys
import time
from dataclasses import dataclass
from unittest.mock import patch

import vlm_engine
from mock_vlm import MockVlmEngine
from vlm_types import (
    YOLO_CLASS_DISEASED,
    YOLO_CLASS_HEALTHY,
    YOLO_CLASS_WEED,
    VlmImage,
    VlmStatus,
)


@dataclass
class BenchResult:
    label:              str
    total_plants:       int
    vlm_invocations:    int
    bypassed:           int
    total_seconds:      float
    avg_seconds_plant:  float

    def report(self) -> str:
        return (
            f"{self.label}:\n"
            f"  Toplam bitki         : {self.total_plants}\n"
            f"  VLM cagrilan         : {self.vlm_invocations}\n"
            f"  YOLO bypass          : {self.bypassed}\n"
            f"  Toplam mission suresi: {self.total_seconds:.1f} s "
            f"({self.total_seconds / 60:.1f} dk)\n"
            f"  Bitki basina ort.    : {self.avg_seconds_plant:.2f} s"
        )


def _generate_plants(
    n: int,
    high_conf_ratio: float,
    seed: int = 42,
) -> list[tuple[int, float]]:
    """N tane (yolo_class_id, yolo_confidence) cifti uret.

    high_conf_ratio kadari [0.75, 0.99], geri kalani [0.30, 0.74].
    """
    rng = random.Random(seed)
    classes = [YOLO_CLASS_HEALTHY, YOLO_CLASS_DISEASED, YOLO_CLASS_WEED]
    plants: list[tuple[int, float]] = []
    n_high = int(n * high_conf_ratio)
    for _ in range(n_high):
        plants.append((rng.choice(classes), rng.uniform(0.75, 0.99)))
    for _ in range(n - n_high):
        plants.append((rng.choice(classes), rng.uniform(0.30, 0.74)))
    rng.shuffle(plants)
    return plants


def _make_image(yolo_class: int, yolo_conf: float) -> VlmImage:
    return VlmImage(
        data            = b"\x00" * (378 * 378 * 3),
        width           = 378,
        height          = 378,
        stride          = 378 * 3,
        timestamp_ms    = 0,
        yolo_class_id   = yolo_class,
        yolo_confidence = yolo_conf,
    )


def _run_scenario(
    label:           str,
    plants:          list[tuple[int, float]],
    vlm_latency_ms:  int,
    bypass_enabled:  bool,
) -> BenchResult:
    """
    Tek bir senaryo kostur.

    bypass_enabled=False ise YOLO confidence kucultulerek gate her zaman
    devre disi kalir (her bitki VLM'e gider).
    """
    engine = MockVlmEngine(scenario="valid_healthy", simulate_latency_ms=vlm_latency_ms)

    # vlm_engine.run_moondream_inference yerine mock'umuzu koy
    def fake_inference(pil_image, prompt):
        return engine.run_inference(None, prompt)

    # init kontrolunu atla
    with patch.object(vlm_engine, "_is_initialized", True), \
         patch.object(vlm_engine, "_model", object()), \
         patch.object(vlm_engine, "run_moondream_inference", fake_inference):

        t0 = time.time()
        for yolo_class, yolo_conf in plants:
            if not bypass_enabled:
                # Gate'i etkisizlestir — confidence'i 0'a cek
                img = _make_image(yolo_class, 0.0)
            else:
                img = _make_image(yolo_class, yolo_conf)
            vlm_analyze_or_fail(img)
        total_s = time.time() - t0

    return BenchResult(
        label             = label,
        total_plants      = len(plants),
        vlm_invocations   = engine.call_count,
        bypassed          = len(plants) - engine.call_count,
        total_seconds     = total_s,
        avg_seconds_plant = total_s / len(plants) if plants else 0.0,
    )


def vlm_analyze_or_fail(image: VlmImage):
    """vlm_engine.vlm_analyze_plant'i cagir, hata varsa anla."""
    from vlm_engine import vlm_analyze_plant
    return vlm_analyze_plant(image)


def main() -> int:
    ap = argparse.ArgumentParser(description="YOLO bypass kazanc simulasyonu")
    ap.add_argument("--plants", type=int, default=50,
                    help="Simule edilecek bitki sayisi (default: 50)")
    ap.add_argument("--vlm-ms", type=int, default=30_000,
                    help="Tek VLM cagrisi suresi (ms) — Pi 4 icin ~30000")
    ap.add_argument("--high-conf-ratio", type=float, default=0.75,
                    help="YOLO'nun yuksek guven verdigi bitki orani [0.0-1.0]")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if not (0.0 <= args.high_conf_ratio <= 1.0):
        print("--high-conf-ratio 0 ile 1 arasinda olmali")
        return 2

    print("YOLO Bypass Benchmark — Pi 4 Simulasyonu")
    print("=" * 60)
    print(f"Bitki sayisi          : {args.plants}")
    print(f"VLM cagri suresi      : {args.vlm_ms} ms ({args.vlm_ms / 1000:.0f} s)")
    print(f"Yuksek guven orani    : {args.high_conf_ratio:.0%}")
    print()

    plants = _generate_plants(args.plants, args.high_conf_ratio, args.seed)

    # Uyari: --vlm-ms 30000 + 50 bitki = 1500 sn beklenir. Latency 0'a indir
    # (gercek timing zaten beklenen toplam = call_count * vlm_ms).
    # Burada hizli simulasyon icin latency_ms = 0 kullaniyoruz ve sonucu
    # call_count * vlm_ms olarak HESAPLIYORUZ.

    print("Simulasyon kosuluyor (beklemeden, matematik)...")
    print()

    r_no_bypass = _run_scenario(
        label          = "[A] Bypass YOK (her bitki VLM'e gider)",
        plants         = plants,
        vlm_latency_ms = 0,   # gercek beklemeden, sadece sayim
        bypass_enabled = False,
    )
    # Gercek Pi 4 suresini hesapla
    r_no_bypass.total_seconds = r_no_bypass.vlm_invocations * (args.vlm_ms / 1000)
    r_no_bypass.avg_seconds_plant = r_no_bypass.total_seconds / args.plants

    r_with_bypass = _run_scenario(
        label          = "[B] Bypass AKTIF (YOLO conf >= 0.75 atlar)",
        plants         = plants,
        vlm_latency_ms = 0,
        bypass_enabled = True,
    )
    r_with_bypass.total_seconds = r_with_bypass.vlm_invocations * (args.vlm_ms / 1000)
    r_with_bypass.avg_seconds_plant = r_with_bypass.total_seconds / args.plants

    print(r_no_bypass.report())
    print()
    print(r_with_bypass.report())
    print()
    print("=" * 60)

    if r_no_bypass.total_seconds > 0:
        saved_s = r_no_bypass.total_seconds - r_with_bypass.total_seconds
        speedup = r_no_bypass.total_seconds / max(r_with_bypass.total_seconds, 0.001)
        saved_pct = saved_s / r_no_bypass.total_seconds * 100
        print(f"KAZANIM   : {saved_s:.0f} s ({saved_s / 60:.1f} dk) - %{saved_pct:.0f} azalma")
        print(f"SPEEDUP   : {speedup:.1f}x hizli")
        print(f"VLM yuku  : %{r_with_bypass.vlm_invocations / args.plants * 100:.0f}'e dustu")

    return 0


if __name__ == "__main__":
    sys.exit(main())
