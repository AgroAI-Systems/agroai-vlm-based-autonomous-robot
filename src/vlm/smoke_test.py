"""
smoke_test.py — Moondream + parser zinciri doğrulama scripti

Bu script Moondream kurulumunun ve gerçek inference yolunun çalışıp
çalışmadığını tek seferde test eder. Pi 4'e ilk deploy'da ve laptop'ta
modeli indirdikten sonra çalıştırılır.

Kullanım:
    python smoke_test.py <model_path> <image_path>

Örnek (laptop):
    python smoke_test.py C:\\Bekirrr\\ceng\\models\\moondream-2b-int4.mf test.jpg

Örnek (Pi 4):
    python smoke_test.py /home/pi/models/moondream-2b-int4.mf /home/pi/test.jpg

Beklenen çıktı (başarılı):
    [1/4] Moondream import...             OK
    [2/4] Model yukleniyor...             OK (3.2s)
    [3/4] Inference calistiriliyor...     OK (8.1s)
    [4/4] Parser dogruluyor...            OK
    -> Parse status: OK | plant=HEALTHY conf=0.92 action=SPRAY

Geliştirici: Bekir Göktepe (220104004018)
Modül: MOD-03 — VLM Plant Analysis (CSE396 — Group 9)
"""

import sys
import time
from pathlib import Path


def _step(idx: int, total: int, label: str) -> None:
    print(f"[{idx}/{total}] {label:<35}", end="", flush=True)


def _ok(extra: str = "") -> None:
    print(f"OK {extra}".rstrip())


def _fail(msg: str) -> None:
    print(f"FAIL\n     ! {msg}")
    sys.exit(1)


def main() -> int:
    if len(sys.argv) != 3:
        print("Kullanim: python smoke_test.py <model_path> <image_path>")
        print("  model_path : moondream-2b-int4.mf dosyasinin yolu")
        print("  image_path : bir bitki/yaprak fotografi (.jpg/.png)")
        return 2

    model_path = Path(sys.argv[1])
    image_path = Path(sys.argv[2])

    if not model_path.exists():
        _fail(f"model bulunamadi: {model_path}")
    if not image_path.exists():
        _fail(f"goruntu bulunamadi: {image_path}")

    print(f"Model dosyasi : {model_path}  ({model_path.stat().st_size / 1e6:.0f} MB)")
    print(f"Goruntu       : {image_path}")
    print()

    # ---------------------------------------------------------------------
    # 1. moondream paketi import edilebiliyor mu?
    # ---------------------------------------------------------------------
    _step(1, 4, "Moondream import...")
    try:
        import moondream as md   # noqa: F401
    except ImportError as exc:
        _fail(
            f"moondream paketi yok: {exc}\n"
            "       Kur: pip install moondream pillow\n"
            "       (Not: Python 3.10/3.11 onerilir; 3.14'te wheel olmayabilir.)"
        )
    _ok()

    # ---------------------------------------------------------------------
    # 2. Model yukleniyor mu?
    # ---------------------------------------------------------------------
    _step(2, 4, "Model yukleniyor...")
    t0 = time.time()
    try:
        model = md.vl(model=str(model_path))
    except Exception as exc:
        _fail(f"model yuklenemedi: {exc}")
    load_s = time.time() - t0
    _ok(f"({load_s:.1f}s)")

    # ---------------------------------------------------------------------
    # 3. Tek bir inference calistir
    # ---------------------------------------------------------------------
    _step(3, 4, "Inference calistiriliyor...")
    try:
        from PIL import Image
    except ImportError:
        _fail("Pillow kurulu degil: pip install pillow")

    img = Image.open(image_path).convert("RGB").resize((378, 378))

    # vlm_engine.py'deki ACTIVE_PROMPT ile ayni mantik
    prompt = (
        "Analyze the plant visible in this image and classify it.\n"
        "Respond ONLY with a single valid JSON object — no markdown, no explanation, "
        "no text before or after the JSON.\n\n"
        '{"status":"<healthy|diseased|weed|unknown>",'
        '"confidence":<0.0-1.0>,'
        '"diagnosis":"<one concise sentence>",'
        '"action":"<skip|spray|laser>",'
        '"severity":"<none|low|medium|high>"}'
    )

    t0 = time.time()
    try:
        result = model.query(img, prompt)
        raw_answer = result["answer"] if isinstance(result, dict) else str(result)
    except Exception as exc:
        _fail(f"inference hata verdi: {exc}")
    inf_s = time.time() - t0
    _ok(f"({inf_s:.1f}s)")

    # ---------------------------------------------------------------------
    # 4. Parser ham metni dogru parse ediyor mu?
    # ---------------------------------------------------------------------
    _step(4, 4, "Parser dogruluyor...")
    try:
        from vlm_parser import parse_vlm_output
    except ImportError as exc:
        _fail(f"vlm_parser import edilemedi: {exc}")

    parse_status, parsed = parse_vlm_output(raw_answer, int(inf_s * 1000))
    _ok()

    # ---------------------------------------------------------------------
    # Sonuc ozeti
    # ---------------------------------------------------------------------
    print()
    print("-- HAM MODEL CIKTISI ---------------------------------")
    print(raw_answer)
    print("------------------------------------------------------")
    print()
    print("-- PARSE SONUCU --------------------------------------")
    print(f"  Parse status   : {parse_status.name}")
    print(f"  Plant status   : {parsed.status.name}")
    print(f"  Confidence     : {parsed.confidence:.2f}")
    print(f"  Diagnosis      : {parsed.diagnosis}")
    print(f"  Action         : {parsed.action.name}")
    print(f"  Severity       : {parsed.severity.name}")
    print(f"  Inference time : {parsed.inference_time_ms} ms")
    print("------------------------------------------------------")
    print()
    print(f"Toplam sure: model_load={load_s:.1f}s + inference={inf_s:.1f}s")
    print(
        "Smoke test BASARILI. Pipeline uctan uca calisiyor."
        if parse_status.name == "OK"
        else "Smoke test PARSE FAIL — model JSON disi cikti uretti, prompt iyilestirmesi gerekebilir."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
