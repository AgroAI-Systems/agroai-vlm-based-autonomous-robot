"""
test_photos.py — Bir klasordeki tum bitki fotograflarini MoondreamV2 + parser
                 zinciri uzerinden gecirip sonuclari raporlar.

Kullanim:
    python test_photos.py [--folder PATH] [--model PATH] [--save-json OUT.json]

Ornek (varsayilan):
    python test_photos.py
    -> C:\\Bekirrr\\ceng\\test_images altindaki tum .jpg/.png/.jpeg dosyalarini test eder

YOLO bypass simulasyonu — dosya adi formati (opsiyonel, elma orneklerl):
    healthy_0.92_saglikli_elma.jpg    -> yolo_class=HEALTHY, yolo_conf=0.92 (bypass)
    diseased_0.55_karaleke.jpg        -> yolo_class=DISEASED, yolo_conf=0.55 (VLM)
    weed_0.85_dandelion.jpg           -> yolo_class=WEED, yolo_conf=0.85 (bypass)
    rastgele_isim.jpg                 -> yolo_class=UNKNOWN, yolo_conf=0.0 (VLM)

Cikti:
    Her foto icin: yolo bilgisi, VLM ham cevabi (kisaltilmis), parse sonucu,
    inference suresi, gate'in tetiklenip tetiklenmedigi.
    Sonda ozet tablo.

Geliştirici: Bekir Göktepe (220104004018)
Modül: MOD-03 — VLM Plant Analysis (CSE396 — Group 9)
"""

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

from PIL import Image

import vlm_engine
from vlm_engine import vlm_analyze_plant, vlm_init, vlm_shutdown
from vlm_types import (
    VLM_MAX_DIAGNOSIS_LEN,
    YOLO_CLASS_DISEASED,
    YOLO_CLASS_HEALTHY,
    YOLO_CLASS_UNKNOWN,
    YOLO_CLASS_WEED,
    VlmImage,
    VlmStatus,
)


_FILENAME_PATTERN = re.compile(
    r"^(?P<cls>healthy|diseased|weed|unknown)_(?P<conf>[01](?:\.\d+)?)_.*",
    re.IGNORECASE,
)

_CLASS_MAP = {
    "healthy":  YOLO_CLASS_HEALTHY,
    "diseased": YOLO_CLASS_DISEASED,
    "weed":     YOLO_CLASS_WEED,
    "unknown":  YOLO_CLASS_UNKNOWN,
}

# vlm_engine.py'deki VLM_CROP_SIZE ile ayni
VLM_CROP_SIZE = 378


def parse_yolo_hint(filename: str) -> tuple[int, float]:
    """
    Dosya adindan YOLO sinif + guven cikartir.
    Eslesme yoksa (UNKNOWN, 0.0) doner.
    """
    m = _FILENAME_PATTERN.match(filename)
    if not m:
        return YOLO_CLASS_UNKNOWN, 0.0
    cls = _CLASS_MAP.get(m.group("cls").lower(), YOLO_CLASS_UNKNOWN)
    conf = float(m.group("conf"))
    return cls, conf


def load_image_as_vlm_image(path: Path, yolo_class: int, yolo_conf: float) -> VlmImage:
    """JPG/PNG dosyasini VLM_CROP_SIZE'a resize edip VlmImage'a cevirir."""
    pil = Image.open(path).convert("RGB").resize((VLM_CROP_SIZE, VLM_CROP_SIZE))
    return VlmImage(
        data            = pil.tobytes(),
        width           = VLM_CROP_SIZE,
        height          = VLM_CROP_SIZE,
        stride          = VLM_CROP_SIZE * 3,
        timestamp_ms    = int(time.time() * 1000),
        yolo_class_id   = yolo_class,
        yolo_confidence = yolo_conf,
    )


def _yolo_label(cls: int) -> str:
    return {
        YOLO_CLASS_HEALTHY:  "HEALTHY",
        YOLO_CLASS_DISEASED: "DISEASED",
        YOLO_CLASS_WEED:     "WEED",
        YOLO_CLASS_UNKNOWN:  "UNKNOWN",
    }.get(cls, "??")


def main() -> int:
    ap = argparse.ArgumentParser(description="Foto klasoru -> VLM pipeline test")
    ap.add_argument("--folder", default=r"C:\Bekirrr\ceng\test_images",
                    help="Foto klasoru (default: C:\\Bekirrr\\ceng\\test_images)")
    ap.add_argument("--model", default="vikhyatk/moondream2",
                    help="HuggingFace repo veya local cache yolu")
    ap.add_argument("--save-json", default=None,
                    help="Tum sonuclari JSON dosyasina kaydet")
    ap.add_argument("--verbose", action="store_true",
                    help="Engine icindeki INFO loglarini goster")
    args = ap.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        print(f"HATA: Klasor yok: {folder}")
        print(f"  Olusturmak icin: mkdir {folder}")
        print(f"  Sonra elma fotolarini buraya at, dosya adi ornegi:")
        print(f"    healthy_0.92_saglikli_elma_yapragi.jpg   (YOLO bypass, VLM atlanir)")
        print(f"    diseased_0.55_karaleke_belirtisi.jpg     (VLM calisir)")
        print(f"    weed_0.85_dandelion.jpg                  (YOLO bypass)")
        print(f"    bilinmeyen_bitki.jpg                     (VLM calisir)")
        return 2

    images = sorted(
        p for p in folder.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )

    if not images:
        print(f"Klasorde foto yok: {folder}")
        print("  Desteklenen: .jpg .jpeg .png")
        return 2

    print(f"Bulunan foto sayisi: {len(images)}")
    print(f"Model dosyasi      : {args.model}")
    print()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    # Model yukle
    print("Moondream yukleniyor...")
    t0 = time.time()
    status = vlm_init(args.model, verbose_logging=args.verbose)
    if status != VlmStatus.OK:
        print(f"HATA: Model yuklenemedi ({status.name})")
        print("Olası sebepler:")
        print("  1. transformers/torch/einops kurulu degil:")
        print("     pip install transformers torch pillow einops")
        print("  2. Ilk indirme icin internet baglantisi gerekli (~3.85 GB)")
        return 1
    print(f"  -> Yuklendi ({time.time() - t0:.1f}s)\n")

    # Her foto icin akis
    results_summary = []
    bypass_count = 0
    vlm_count = 0
    fail_count = 0

    for idx, img_path in enumerate(images, 1):
        yolo_cls, yolo_conf = parse_yolo_hint(img_path.name)

        print(f"[{idx}/{len(images)}] {img_path.name}")
        print(f"    YOLO hint: class={_yolo_label(yolo_cls)} conf={yolo_conf:.2f}")

        try:
            vlm_image = load_image_as_vlm_image(img_path, yolo_cls, yolo_conf)
        except Exception as exc:
            print(f"    HATA goruntu yuklenemedi: {exc}")
            fail_count += 1
            continue

        t0 = time.time()
        parse_status, result = vlm_analyze_plant(vlm_image)
        elapsed_s = time.time() - t0

        used_vlm = result.inference_time_ms > 0
        if used_vlm:
            vlm_count += 1
            tag = "VLM kosturuldu"
        else:
            bypass_count += 1
            tag = "YOLO BYPASS"

        print(f"    -> [{tag}] parse={parse_status.name} "
              f"plant={result.status.name} conf={result.confidence:.2f}")
        print(f"       action={result.action.name} severity={result.severity.name}")
        print(f"       diagnosis: {result.diagnosis[:100]}"
              f"{'...' if len(result.diagnosis) > 100 else ''}")
        print(f"       wall-clock: {elapsed_s:.1f}s "
              f"(inference_time_ms={result.inference_time_ms})")
        print()

        results_summary.append({
            "file":              img_path.name,
            "yolo_class":        _yolo_label(yolo_cls),
            "yolo_confidence":   yolo_conf,
            "bypass_triggered":  not used_vlm,
            "parse_status":      parse_status.name,
            "vlm_result":        result.to_c_compatible_dict(),
            "wall_clock_s":      round(elapsed_s, 2),
        })

    # Ozet
    print("=" * 60)
    print(f"OZET")
    print(f"  Toplam foto    : {len(images)}")
    print(f"  YOLO bypass    : {bypass_count}")
    print(f"  VLM kosturuldu : {vlm_count}")
    print(f"  Hata           : {fail_count}")
    if len(images) > 0:
        print(f"  Bypass orani   : %{bypass_count / len(images) * 100:.0f}")

    if args.save_json:
        out = Path(args.save_json)
        out.write_text(json.dumps(results_summary, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        print(f"\n  JSON kaydedildi: {out}")

    vlm_shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
