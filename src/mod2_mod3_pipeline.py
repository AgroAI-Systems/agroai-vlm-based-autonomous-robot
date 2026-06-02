"""
mod2_mod3_pipeline.py — MOD-02 (YOLO) + MOD-03 (VLM) ortak entegrasyon testi

Akis:
    Goruntu
      │
      ▼
    YOLO (best.pt: SCAB / Weeds / healthy)
      │
      ├─ class_id + confidence ──► MOD-03 YOLO bypass gate
      │                              │
      │             conf >= esik     ├──► direkt VlmResult (VLM atlanir)
      │             (WEED: her conf) │
      │             conf < esik      └──► MoondreamV2 ──► VlmResult
      ▼
    VlmResult (status / action / severity / diagnosis)

YOLO sinif eslemeleri (best.pt'den):
    0 = 'SCAB'    → DISEASED (hastalıklı elma - karaleke)
    1 = 'Weeds'   → WEED     (yabani ot)
    2 = 'healthy' → HEALTHY  (sağlıklı elma)

Kullanim:
    python mod2_mod3_pipeline.py --images C:\\Bekirrr\\ceng\\test_images
    python mod2_mod3_pipeline.py --images C:\\Bekirrr\\ceng\\test_images --save-json results.json

Gelistirici: Bekir Goktepe (220104004018)
Modul: MOD-02 + MOD-03 Entegrasyon Testi — CSE396 Group 9
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# YOLO sinif → MOD-03 sinif ID eslemesi (best.pt ile tutarli)
# ---------------------------------------------------------------------------
# best.pt: {0: 'SCAB', 1: 'Weeds', 2: 'healthy'}
YOLO_NAME_TO_CLASS_ID = {
    "purslane - semizotu": 0,  # Purslane → WEED
    "scab":                1,  # SCAB     → DISEASED
    "healthy":             2,  # healthy  → HEALTHY
}

# best.pt class_id → mod3 YOLO_CLASS_* eslemesi
# best.pt:  0=Purslane(semizotu), 1=SCAB, 2=healthy
# mod3:     HEALTHY=0, DISEASED=1, WEED=2
BESTPT_TO_MOD3_CLASS = {
    0: 2,   # Purslane (semizotu) → YOLO_CLASS_WEED
    1: 1,   # SCAB                → YOLO_CLASS_DISEASED
    2: 0,   # healthy             → YOLO_CLASS_HEALTHY
}

BESTPT_CLASS_NAMES = {0: "Purslane-semizotu", 1: "SCAB", 2: "healthy"}

# Esik degerler (vlm_types.py YOLO_VLM_THRESHOLDS ile ayni)
# WEED (mod3 id=2)    : 0.0  → her conf'ta bypass
# HEALTHY (mod3 id=0) : 0.75
# DISEASED (mod3 id=1): 0.75
BYPASS_THRESHOLDS = {
    0: 0.75,   # mod3 YOLO_CLASS_HEALTHY
    1: 0.75,   # mod3 YOLO_CLASS_DISEASED
    2: 0.0,    # mod3 YOLO_CLASS_WEED — her conf'ta bypass
}

# Tespit edilmesi icin minimum YOLO confidence (cok dusuk tespitleri filtrele)
YOLO_DETECT_MIN_CONF = 0.25


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def resolve_model_path(model_path: str) -> str:
    """
    Model yolunu coz:
    - best.pt varsa → dogrudan kullan
    - best/ klasoru varsa → best.pt'ye donustur, kullan
    - Ikisi de yoksa → hata
    """
    import zipfile

    pt_path    = model_path                             # ornek: src/best.pt
    folder_path = model_path.replace(".pt", "")         # ornek: src/best

    if os.path.isfile(pt_path):
        return pt_path

    if os.path.isdir(folder_path):
        log = logging.getLogger("pipeline.yolo")
        log.info(f"'{folder_path}' klasoru bulundu, best.pt'ye donusturuluyor...")
        with zipfile.ZipFile(pt_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(folder_path):
                for file in files:
                    filepath = os.path.join(root, file)
                    arcname  = os.path.relpath(filepath, os.path.dirname(folder_path))
                    zf.write(filepath, arcname)
        log.info(f"Olusturuldu: {pt_path}")
        return pt_path

    raise FileNotFoundError(
        f"Ne '{pt_path}' ne de '{folder_path}/' bulunamadi.\n"
        f"YOLO modelini su konuma koy: {pt_path}  veya  {folder_path}/"
    )


def load_yolo(model_path: str):
    """best.pt veya best/ klasorunu ultralytics YOLO ile yukle."""
    from ultralytics import YOLO
    log = logging.getLogger("pipeline.yolo")

    resolved = resolve_model_path(model_path)
    log.info(f"YOLO yukleniyor: {resolved}")
    t0 = time.time()
    model = YOLO(resolved)
    log.info(
        f"YOLO hazir ({time.time()-t0:.1f}s) "
        f"siniflar: {model.names}"
    )
    return model


def yolo_detect(yolo_model, image_path: str) -> tuple[int, float, str]:
    """
    Goruntu uzerinde YOLO calistir.

    Returns:
        (mod3_class_id, confidence, yolo_class_name)
        Tespit yoksa: (-1, 0.0, 'no_detection')
    """
    results = yolo_model(image_path, verbose=False, conf=YOLO_DETECT_MIN_CONF)
    boxes = results[0].boxes

    if not len(boxes):
        return -1, 0.0, "no_detection"

    # En yuksek confidence'li tespiti sec
    best_conf = -1.0
    best_cls  = -1
    for box in boxes:
        conf = float(box.conf)
        cls  = int(box.cls)
        if conf > best_conf:
            best_conf = conf
            best_cls  = cls

    yolo_name = BESTPT_CLASS_NAMES.get(best_cls, "unknown")
    mod3_id   = BESTPT_TO_MOD3_CLASS.get(best_cls, -1)
    return mod3_id, best_conf, yolo_name


def load_vlm_engine():
    """MOD-03 VLM engine'i yukle."""
    sys.path.insert(0, str(Path(__file__).parent / "vlm"))
    from vlm_engine import vlm_init, VlmStatus
    log = logging.getLogger("pipeline.vlm")
    log.info("MoondreamV2 yukleniyor...")
    t0 = time.time()
    status = vlm_init()
    if status != VlmStatus.OK:
        raise RuntimeError(f"vlm_init basarisiz: {status.name}")
    log.info(f"MoondreamV2 hazir ({time.time()-t0:.1f}s)")


def run_pipeline_on_image(
    yolo_model,
    image_path: str,
    idx: int,
    total: int,
) -> dict:
    """
    Tek bir goruntu icin tam MOD-02 → MOD-03 pipeline'i calistir.
    """
    sys.path.insert(0, str(Path(__file__).parent / "vlm"))
    from vlm_engine import vlm_analyze_plant
    from vlm_types import VlmImage, VlmStatus

    log = logging.getLogger("pipeline")
    name = Path(image_path).name
    print(f"\n[{idx}/{total}] {name}")

    wall_start = time.time()

    # ── MOD-02: YOLO ────────────────────────────────────────────────────────
    t0 = time.time()
    mod3_class_id, yolo_conf, yolo_name = yolo_detect(yolo_model, image_path)
    yolo_ms = int((time.time() - t0) * 1000)

    if mod3_class_id == -1:
        print(f"    YOLO: tespit yok ({yolo_ms}ms)")
    else:
        bypass_threshold = BYPASS_THRESHOLDS.get(mod3_class_id, 0.75)
        will_bypass = yolo_conf >= bypass_threshold
        bypass_note = (
            "→ BYPASS (weed, conf onemsiz)"
            if bypass_threshold == 0.0 and mod3_class_id == 2
            else f"→ {'BYPASS' if will_bypass else 'VLM calisacak'} (esik={bypass_threshold})"
        )
        print(f"    YOLO: {yolo_name} conf={yolo_conf:.2f}  {bypass_note}  [{yolo_ms}ms]")

    # ── MOD-02→MOD-03 köprüsü: VlmImage'a YOLO bilgisini yaz ──────────────
    from PIL import Image as PILImage
    pil_img = PILImage.open(image_path).convert("RGB").resize((378, 378))
    vlm_image = VlmImage(
        data            = pil_img.tobytes(),
        width           = 378,
        height          = 378,
        stride          = 378 * 3,
        timestamp_ms    = int(time.time() * 1000),
        yolo_class_id   = mod3_class_id,
        yolo_confidence = yolo_conf,
    )

    # ── MOD-03: VLM gate + inference ────────────────────────────────────────
    parse_status, result = vlm_analyze_plant(vlm_image)

    wall_ms = int((time.time() - wall_start) * 1000)
    used_vlm = result.inference_time_ms > 0
    gate_tag  = "VLM kosturuldu" if used_vlm else "YOLO BYPASS"

    print(f"    [{gate_tag}] parse={parse_status.name}")
    print(f"    status={result.status.name}  conf={result.confidence:.2f}  "
          f"action={result.action.name}  severity={result.severity.name}")
    print(f"    diagnosis: {result.diagnosis[:100]}")
    print(f"    YOLO={yolo_ms}ms  VLM={result.inference_time_ms}ms  toplam={wall_ms}ms")

    return {
        "file":              name,
        "yolo_name":         yolo_name,
        "yolo_mod3_class":   mod3_class_id,
        "yolo_confidence":   round(yolo_conf, 3),
        "yolo_time_ms":      yolo_ms,
        "gate":              gate_tag,
        "parse_status":      parse_status.name,
        "plant_status":      result.status.name,
        "confidence":        round(result.confidence, 3),
        "action":            result.action.name,
        "severity":          result.severity.name,
        "diagnosis":         result.diagnosis,
        "vlm_time_ms":       result.inference_time_ms,
        "total_time_ms":     wall_ms,
    }


def print_summary(results: list[dict]) -> None:
    print("\n" + "=" * 64)
    print("OZET — MOD-02 + MOD-03 Entegrasyon Testi")
    print("=" * 64)

    total   = len(results)
    bypass  = sum(1 for r in results if r["gate"] == "YOLO BYPASS")
    vlm_ran = sum(1 for r in results if r["gate"] == "VLM kosturuldu")
    ok      = sum(1 for r in results if r["parse_status"] == "OK")
    errors  = total - ok

    print(f"  Toplam goruntu : {total}")
    print(f"  YOLO bypass    : {bypass}  (VLM atlanildi, anlik)")
    print(f"  VLM kosturuldu : {vlm_ran}")
    print(f"  Parse basari   : {ok}/{total}")
    print(f"  Parse hata     : {errors}")

    if total > 0:
        print(f"  Bypass orani   : %{bypass/total*100:.0f}")

    # Aksiyon dagilimi
    actions = {}
    for r in results:
        actions[r["action"]] = actions.get(r["action"], 0) + 1
    print(f"\n  Aksiyon dagilimi:")
    for action, count in sorted(actions.items()):
        bar = "█" * count
        print(f"    {action:<8}: {bar} ({count})")

    # Sinif dagilimi
    statuses = {}
    for r in results:
        statuses[r["plant_status"]] = statuses.get(r["plant_status"], 0) + 1
    print(f"\n  Bitki sinifi:")
    for st, count in sorted(statuses.items()):
        print(f"    {st:<10}: {count}")

    # Timing
    vlm_times = [r["vlm_time_ms"] for r in results if r["vlm_time_ms"] > 0]
    total_times = [r["total_time_ms"] for r in results]
    if vlm_times:
        print(f"\n  VLM ortalama   : {sum(vlm_times)//len(vlm_times)} ms/goruntu")
    print(f"  Toplam sure    : {sum(total_times)/1000:.1f}s")
    if total > 0:
        print(f"  Goruntu basina : {sum(total_times)//total} ms ort.")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="MOD-02 + MOD-03 entegrasyon testi")
    ap.add_argument("--images", default=r"C:\Bekirrr\ceng\test_images",
                    help="Test goruntuleri klasoru")
    ap.add_argument("--model", default=r"C:\Bekirrr\ceng\src\best.pt",
                    help="YOLO model dosyasi (best.pt)")
    ap.add_argument("--save-json", default=None,
                    help="Sonuclari JSON dosyasina kaydet")
    ap.add_argument("--verbose", action="store_true",
                    help="Detayli log")
    ap.add_argument("--no-vlm", action="store_true",
                    help="VLM yukleme, sadece YOLO bypass ile test et")
    args = ap.parse_args()

    setup_logging(args.verbose)
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

    img_dir = Path(args.images)
    if not img_dir.exists():
        print(f"HATA: Goruntu klasoru bulunamadi: {img_dir}")
        return 2

    images = sorted(
        p for p in img_dir.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if not images:
        print(f"HATA: Klasorde goruntu yok: {img_dir}")
        return 2

    print(f"Goruntu sayisi : {len(images)}")
    print(f"YOLO modeli   : {args.model}")
    print(f"VLM            : {'ATLANACAK (--no-vlm)' if args.no_vlm else 'MoondreamV2'}")
    print()

    # YOLO yukle
    yolo = load_yolo(args.model)

    # VLM yukle (--no-vlm verilmemisse)
    if not args.no_vlm:
        load_vlm_engine()
    else:
        # --no-vlm: tum esikleri 0.0 yap → her sey YOLO bypass olur, VLM hic calismaz
        sys.path.insert(0, str(Path(__file__).parent / "vlm"))
        import vlm_types as _vt
        for k in list(_vt.YOLO_VLM_THRESHOLDS.keys()):
            _vt.YOLO_VLM_THRESHOLDS[k] = 0.0
        import vlm_engine as _eng
        _eng._is_initialized = True
        _eng._model = object()

    all_results = []
    for idx, img_path in enumerate(images, 1):
        try:
            r = run_pipeline_on_image(yolo, str(img_path), idx, len(images))
            all_results.append(r)
        except Exception as exc:
            print(f"    HATA: {exc}")
            import traceback; traceback.print_exc()

    print_summary(all_results)

    if args.save_json:
        out = Path(args.save_json)
        out.write_text(
            json.dumps(all_results, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        print(f"JSON kaydedildi: {out}")

    # VLM kapat
    if not args.no_vlm:
        sys.path.insert(0, str(Path(__file__).parent / "vlm"))
        from vlm_engine import vlm_shutdown
        vlm_shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
