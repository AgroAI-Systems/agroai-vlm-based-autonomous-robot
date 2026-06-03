"""
vlm_engine.py — MOD-03 (VLM) SmolVLM-256M Inference Engine

Bu dosya Umut Akman'ın sorumluluk alanıdır:
  - SmolVLM-256M-Instruct model yükleme / kapatma
  - Prompt mühendisliği (tek kelime çıktı talebi)
  - Pi 4'e uyarlanmış inference çağrısı ve timeout yönetimi
  - Bekir'in vlm_parser.py'siyle entegrasyon (vlm_analyze_plant)

Veri akışı:
  MOD-02 (VlmImage) → vlm_analyze_plant() → [run_smolvlm_inference + parse_vlm_output] → VlmResult → MOD-04

Geliştirici: Umut Akman (250104004997)
Modül Partneri (Parser): Bekir Göktepe (220104004018)
Modül: MOD-03 — VLM Plant Analysis (CSE396 — Group 9)

Bağımlılıklar (Pi 4'e kur):
    pip install transformers torch pillow einops

Model:
    HuggingFaceTB/SmolVLM-256M-Instruct (HuggingFace) — ~500 MB safetensors.
    PyTorch CPU üzerinde Pi 4'te çalışır.
    İlk vlm_init() çağrısında otomatik HuggingFace cache'ine iner.
"""

import logging
import threading
import time
from typing import Optional

from PIL import Image

from vlm_parser import parse_vlm_output
from vlm_types import (
    VLM_MAX_DIAGNOSIS_LEN,
    YOLO_TO_PLANT_STATUS,
    YOLO_VLM_TRIGGER_THRESHOLD,
    YOLO_VLM_THRESHOLDS,
    VlmAction,
    VlmImage,
    VlmPlantStatus,
    VlmResult,
    VlmSeverity,
    VlmStatus,
)

log = logging.getLogger("vlm.engine")

# ---------------------------------------------------------------------------
# Prompt Mühendisliği — v1
# ---------------------------------------------------------------------------
# Tasarım kararları:
# 1. "Respond ONLY with valid JSON" → hallucination riskini azaltır
# 2. Her field için örnekler verildi → modeli enum'larımıza yönlendirir
# 3. "Do not include any text outside the JSON object" → parser Layer 2'yi
#    hafifletir (hallucination filtresi yine de aktif kalır)
# 4. confidence için [0.0, 1.0] açıkça belirtildi → out-of-range azalır
#
# Prompt değişikliği gerekirse PROMPT_VERSION artır ve eski versiyonu
# DEPRECATED olarak tut. Log'a hangi versiyon kullanıldığı yazılır.

PROMPT_VERSION: str = "v3_one_word"

# DEPRECATED — PROMPT_V1 (generic plant, JSON istiyor) git history'de kalır.
# Model 9 fotonun hepsinde JSON üretmedi, placeholder kopyaladı.
PROMPT_V1: str = (
    "Analyze the plant visible in this image and classify it.\n"
    "Respond ONLY with a single valid JSON object — no markdown, no explanation.\n"
    "Format: {\"status\":\"healthy|diseased|weed|unknown\","
    "\"confidence\":0.0-1.0,\"diagnosis\":\"...\",\"action\":\"skip|spray|laser\","
    "\"severity\":\"none|low|medium|high\"}"
)

# DEPRECATED — PROMPT_V2_APPLE da JSON istemekten dolayı modelin
# tek-kelime eğilimine takıldı. Saklı tutuluyor (regression vs).
PROMPT_V2_APPLE: str = (
    "You are an agricultural inspection AI for an apple orchard robot.\n"
    "Classify the plant as healthy, diseased, or weed and respond with JSON."
)

# AKTIF PROMPT — Umut'un vlm_server.py yaklasimini takip eder:
# Tek kelime iste, JSON'u Python tarafi (STATUS_MAP) deterministik uretir.
# Boylece modelin JSON formatina uymama sorunu sifirdan engellenir.
PROMPT_V3_ONE_WORD: str = (
    "Look at this plant. Reply with EXACTLY ONE word, lowercase, no punctuation. "
    "Choose: 'healthy' if it is a healthy apple plant, "
    "'diseased' if it is an apple plant with visible disease symptoms, "
    "'weed' if it is an unwanted weed (not an apple plant). "
    "Answer with only one of: healthy, diseased, weed"
)

# Aktif prompt
ACTIVE_PROMPT: str = PROMPT_V3_ONE_WORD


# ---------------------------------------------------------------------------
# Umut'un STATUS_MAP — deterministik ham metin → JSON üretici
# ---------------------------------------------------------------------------
# Model tek kelime döndürdüğünde bu eşleme ile dolu JSON string'i kurarız,
# parse_vlm_output bunu sorunsuz okur. Mantık vlm_server.py ile birebir aynı.
#
# Severity kararı: WEED için NONE (yabani ot "şiddetli" olmaz, eylem tek tip).

_RAW_TO_JSON_MAP: dict[str, tuple[str, str, str]] = {
    # status: (action, severity, kisa diagnosis)
    "healthy":  ("skip",  "none",   "Healthy apple plant detected; no action required."),
    "diseased": ("spray", "medium", "Disease symptoms detected on apple; pump treatment recommended."),
    "weed":     ("laser", "none",   "Unwanted weed detected; laser elimination recommended."),
}

# Cevap tek temiz kelime ise yuksek guven, gurultulu ise orta
_CONF_CLEAN: float  = 0.85
_CONF_NOISY: float  = 0.60

# ---------------------------------------------------------------------------
# Pi 4 sabitleri
# ---------------------------------------------------------------------------
# mod3.h: #define VLM_TIMEOUT_MS 30000 (Pi 5 için)
# Pi 4'te inference 20–45 s sürer, termal throttle altında 90 s'ye çıkabilir.
# Eğer mod3.h güncellenirse bu sabiti de güncelle.

VLM_TIMEOUT_MS: int = 15_000  # 15 saniye — timeout olursa YOLO fallback devreye girer

# Modelin beklediği kare boyutu (mod3.h VLM_CROP_SIZE ile uyumlu)
VLM_CROP_SIZE: int = 224  # px

# ---------------------------------------------------------------------------
# Global model state (singleton)
# ---------------------------------------------------------------------------
# SmolVLM-256M: ~500 MB disk, ~1.0 GB RAM, timeout=15s → YOLO fallback

_model = None          # transformers model
_processor = None      # AutoProcessor (SmolVLM)
_tokenizer = None      # alias — backward compat icin
_model_lock = threading.Lock()
_is_initialized: bool = False

# HuggingFace model repo
HF_MODEL_ID: str = "HuggingFaceTB/SmolVLM-256M-Instruct"
HF_REVISION: str = None   # latest


# ---------------------------------------------------------------------------
# Public API — mod3.h fonksiyon kontratı
# ---------------------------------------------------------------------------

def vlm_init(model_path: str = HF_MODEL_ID, verbose_logging: bool = False) -> VlmStatus:
    """
    mod3.h: vlm_status_t vlm_init(const vlm_config_t *config)

    SmolVLM-256M modelini belleğe yükler. Uygulama başında bir kez çağrılır.

    Args:
        model_path:      HuggingFace model repo ID veya yerel cache yolu.
                         Default: "HuggingFaceTB/SmolVLM-256M-Instruct" — ilk seferde
                         ~/.cache/huggingface/hub altına indirir (~500 MB).
                         Pi 4'te de aynı path; bir kez indirip git'e
                         koyma, HuggingFace cache'i kullan.
        verbose_logging: True ise DEBUG seviyesi log aktif olur.

    Returns:
        VlmStatus.OK             — yükleme başarılı
        VlmStatus.ERR_INIT       — yükleme başarısız (paket/internet vb.)
        VlmStatus.ERR_MEMORY     — bellek yetersiz
    """
    global _model, _processor, _tokenizer, _is_initialized

    if verbose_logging:
        logging.getLogger("vlm").setLevel(logging.DEBUG)

    with _model_lock:
        if _is_initialized:
            log.debug("vlm_init: already initialized, skipping.")
            return VlmStatus.OK

        log.info(f"vlm_init: loading {model_path} (SmolVLM-256M)")

        try:
            from transformers import AutoProcessor, AutoModelForVision2Seq

            _processor = AutoProcessor.from_pretrained(model_path)
            _model = AutoModelForVision2Seq.from_pretrained(
                model_path, low_cpu_mem_usage=True,
            )
            _model.eval()

            # INT8 dynamic quantization — text decoder'ı hedef al.
            # SmolVLM'in vision encoder'ı (SigLIP) quantize_dynamic'i full-model
            # modunda reddediyor; text_model alt bileşeni standart Llama-based.
            import torch as _torch
            try:
                log.info("vlm_init: applying INT8 dynamic quantization (text model only)...")
                _text_model = getattr(getattr(_model, "model", None), "text_model", None)
                if _text_model is not None:
                    _model.model.text_model = _torch.quantization.quantize_dynamic(
                        _text_model, {_torch.nn.Linear}, dtype=_torch.qint8,
                    )
                    log.info("vlm_init: text model INT8 quantization done.")
                else:
                    log.warning("vlm_init: text_model subcomponent not found — skipping INT8")
            except Exception as _qe:
                log.warning(f"vlm_init: quantize_dynamic failed ({_qe}) — continuing without INT8")

            _tokenizer = _processor  # backward compat
            _is_initialized = True
            log.info("vlm_init: SmolVLM-256M loaded successfully.")
            return VlmStatus.OK

        except ImportError as exc:
            log.error(
                f"vlm_init: missing dependency: {exc}\n"
                "       Install: pip install transformers torch pillow einops"
            )
            return VlmStatus.ERR_INIT

        except MemoryError:
            log.error("vlm_init: not enough memory to load model (~1 GB required)")
            return VlmStatus.ERR_MEMORY

        except Exception as exc:
            log.error(f"vlm_init: unexpected error: {exc}")
            return VlmStatus.ERR_INIT


def vlm_shutdown() -> None:
    """
    mod3.h: void vlm_shutdown(void)

    Model belleğini serbest bırakır. Uygulama kapanırken çağrılır.
    Pi 4'te RAM kıymetli — temiz kapatma önemli.
    """
    global _model, _processor, _tokenizer, _is_initialized

    with _model_lock:
        if not _is_initialized:
            return
        try:
            del _model
            del _processor
            _model = None
            _processor = None
            _tokenizer = None
            _is_initialized = False
            log.info("vlm_shutdown: model unloaded.")
        except Exception as exc:
            log.warning(f"vlm_shutdown: error during cleanup: {exc}")


def vlm_analyze_plant(image: VlmImage) -> tuple[VlmStatus, VlmResult]:
    """
    mod3.h: vlm_status_t vlm_analyze_plant(const vlm_image_t *image, vlm_result_t *result)

    Ana public API. MOD-04 bu fonksiyonu çağırır.

    Pipeline:
        VlmImage → PIL Image → SmolVLM-256M → ham metin → parse_vlm_output → VlmResult

    Args:
        image: MOD-02'den gelen ROI frame (VlmImage dataclass).

    Returns:
        (VlmStatus, VlmResult) — her zaman dolu bir struct döner, asla crash etmez.

    Not: vlm_init() çağrılmadan bu fonksiyon çağrılırsa ERR_INIT döner.
    """
    # Init kontrolü
    if not _is_initialized or _model is None:
        log.error("vlm_analyze_plant called before vlm_init()")
        return VlmStatus.ERR_INIT, _emergency_result("engine_not_initialized")

    # Girdi validasyonu (MOD-02 bug'larına karşı)
    status = _validate_image(image)
    if status != VlmStatus.OK:
        return status, _emergency_result("invalid_image_input")

    # ════════════════════════════════════════════════════════════════════
    # YOLO BYPASS GATE — Pi 4 performans optimizasyonu
    # ════════════════════════════════════════════════════════════════════
    # MOD-02 YOLO sınıflandırması yeterince güvenliyse VLM inference'ı
    # tamamen atla; sonucu YOLO çıktısından sentezle.
    # MOD-04 farkı görmez (aynı VlmResult struct'ını alır).
    if _yolo_confident_enough(image):
        threshold = YOLO_VLM_THRESHOLDS.get(image.yolo_class_id, YOLO_VLM_TRIGGER_THRESHOLD)
        from vlm_types import YOLO_CLASS_WEED
        reason = (
            "WEED class — confidence ignored, YOLO always trusted"
            if image.yolo_class_id == YOLO_CLASS_WEED
            else f"conf={image.yolo_confidence:.2f} >= threshold={threshold}"
        )
        log.info(
            f"YOLO bypass: class_id={image.yolo_class_id} {reason} "
            f"— skipping VLM inference"
        )
        return VlmStatus.OK, _synthesize_from_yolo(
            image.yolo_class_id, image.yolo_confidence
        )
    # ════════════════════════════════════════════════════════════════════

    # YOLO bilgisi yoksa veya düşük güvenliyse → gerçek VLM yoluna devam
    if image.yolo_class_id in YOLO_TO_PLANT_STATUS:
        log.info(
            f"VLM invoked: yolo_class_id={image.yolo_class_id} "
            f"conf={image.yolo_confidence:.2f} < {YOLO_VLM_TRIGGER_THRESHOLD} "
            f"— requesting second opinion from SmolVLM"
        )
    else:
        log.info(
            "VLM invoked: no YOLO classification provided "
            "(yolo_class_id=-1 or unknown) — running full inference"
        )

    # PIL Image'a dönüştür
    try:
        pil_image = _vlm_image_to_pil(image)
    except Exception as exc:
        log.error(f"vlm_analyze_plant: image conversion failed: {exc}")
        return VlmStatus.ERR_INVALID_INPUT, _emergency_result("image_conversion_failed")

    # Inference (15s timeout)
    raw_text, elapsed_ms = run_smolvlm_inference(pil_image, ACTIVE_PROMPT)

    # Ham metnin bellekten düşmesi için erken temizle (Pi 4 RAM)
    pil_image = None  # noqa: F841

    # Timeout veya inference hatası — YOLO verisi varsa onu kullan
    if not raw_text:
        if image.yolo_class_id in YOLO_TO_PLANT_STATUS:
            log.warning(
                f"vlm_analyze_plant: timeout/error after {elapsed_ms} ms "
                f"— falling back to YOLO result (class_id={image.yolo_class_id}, "
                f"conf={image.yolo_confidence:.2f})"
            )
            return VlmStatus.OK, _synthesize_from_yolo(image.yolo_class_id, image.yolo_confidence)
        log.warning(
            f"vlm_analyze_plant: timeout/error after {elapsed_ms} ms, no YOLO data — unknown"
        )
        return VlmStatus.ERR_TIMEOUT, _emergency_result("vlm_timeout_no_yolo_fallback")

    # Umut yaklaşımı: ham tek kelime cevabı, deterministik JSON'a çevir
    synthetic_json = _classify_raw_to_json(raw_text)

    # Parser'a devret (Bekir'in katmanı, doğrulama + güvenli default)
    parse_status, result = parse_vlm_output(synthetic_json, elapsed_ms)

    if parse_status != VlmStatus.OK:
        log.warning(
            f"vlm_analyze_plant: parse failed after {elapsed_ms} ms — "
            f"reason: {result.diagnosis}"
        )

    return parse_status, result


# ---------------------------------------------------------------------------
# Core Inference — Umut'un ana fonksiyonu
# ---------------------------------------------------------------------------

def run_smolvlm_inference(
    pil_image: Image.Image,
    prompt: str,
) -> tuple[str, int]:
    """
    SmolVLM-256M'e görüntü + prompt göndererek ham metin alır.

    Args:
        pil_image: PIL Image objesi (RGB).
        prompt:    Modele gönderilecek soru/talimat.

    Returns:
        (raw_output_text, inference_time_ms)
        Timeout veya inference hatası durumunda ("", elapsed_ms) döner.
        Asla exception fırlatmaz.
    """
    start_ns = time.monotonic_ns()

    # Timeout: VLM_TIMEOUT_MS kadar bekle, sonra boş string dön
    result_holder: list[str] = [""]
    error_holder:  list[Optional[Exception]] = [None]

    def _inference_worker():
        try:
            import torch
            _pil = pil_image  # local ref — del after encoding to free PIL memory
            messages = [{"role": "user", "content": [
                {"type": "image"},
                {"type": "text", "text": prompt},
            ]}]
            text = _processor.apply_chat_template(messages, add_generation_prompt=True)
            inputs = _processor(text=text, images=[_pil], return_tensors="pt")
            del _pil  # PIL pixels already encoded into tensors — free immediately
            with torch.no_grad():
                out_ids = _model.generate(
                    **inputs, max_new_tokens=5, do_sample=False,
                )
            # sadece yeni token'ları decode et
            new_ids = out_ids[0][inputs["input_ids"].shape[1]:]
            answer = _processor.decode(new_ids, skip_special_tokens=True).strip()
            result_holder[0] = answer if isinstance(answer, str) else ""
        except Exception as exc:
            error_holder[0] = exc
            result_holder[0] = ""

    thread = threading.Thread(target=_inference_worker, daemon=True)
    thread.start()

    timeout_s = VLM_TIMEOUT_MS / 1000.0
    thread.join(timeout=timeout_s)

    elapsed_ms = (time.monotonic_ns() - start_ns) // 1_000_000

    if thread.is_alive():
        # Timeout — thread hâlâ çalışıyor, daemon olduğu için process çıkışında temizlenir
        log.error(
            f"run_smolvlm_inference: TIMEOUT after {elapsed_ms} ms "
            f"(limit={VLM_TIMEOUT_MS} ms) — returning empty string"
        )
        return "", elapsed_ms

    if error_holder[0] is not None:
        log.error(
            f"run_smolvlm_inference: inference error after {elapsed_ms} ms: "
            f"{error_holder[0]}"
        )
        return "", elapsed_ms

    raw_text = result_holder[0]

    # 4 KB üstünü truncate et — pi 4 RAM + parser güvenliği
    MAX_RAW_LEN = 4096
    if len(raw_text) > MAX_RAW_LEN:
        log.warning(
            f"run_smolvlm_inference: output truncated "
            f"({len(raw_text)} → {MAX_RAW_LEN} bytes)"
        )
        raw_text = raw_text[:MAX_RAW_LEN]

    log.debug(
        f"run_smolvlm_inference: done in {elapsed_ms} ms, "
        f"output_len={len(raw_text)}, prompt_version={PROMPT_VERSION}"
    )

    return raw_text, elapsed_ms


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

def _validate_image(image: VlmImage) -> VlmStatus:
    """
    MOD-02'den gelen VlmImage'ın temel bütünlüğünü kontrol eder.
    Bu kontroller MOD-02 bug'larını erken yakalar, silently ignore etmez.
    """
    if image is None:
        log.error("_validate_image: image is None")
        return VlmStatus.ERR_INVALID_INPUT

    if image.data is None or len(image.data) == 0:
        log.error("_validate_image: image.data is None or empty")
        return VlmStatus.ERR_INVALID_INPUT

    if image.width == 0 or image.height == 0:
        log.error(f"_validate_image: zero dimension ({image.width}x{image.height})")
        return VlmStatus.ERR_INVALID_INPUT

    # Beklenen boyut kontrolü (soft warning — crash etme)
    if image.width != VLM_CROP_SIZE or image.height != VLM_CROP_SIZE:
        log.warning(
            f"_validate_image: unexpected size {image.width}x{image.height} "
            f"(expected {VLM_CROP_SIZE}x{VLM_CROP_SIZE}) — continuing anyway"
        )

    # Beklenen buffer boyutu: width * height * 3 (RGB)
    expected_len = image.stride * image.height
    if len(image.data) < expected_len:
        log.error(
            f"_validate_image: buffer too small "
            f"(got {len(image.data)}, expected >= {expected_len})"
        )
        return VlmStatus.ERR_INVALID_INPUT

    return VlmStatus.OK


def _vlm_image_to_pil(image: VlmImage) -> Image.Image:
    """
    VlmImage (raw RGB bytes) → PIL Image (RGB mode).

    PIL, SmolVLM processor'ının beklediği formattır.
    Pillow 10+ ile uyumlu: frombytes düz row-major RGB buffer'ı bekler.
    Eğer stride width*3'ten büyükse (padding varsa) padding'i strip ederiz.
    """
    expected_stride = image.width * 3
    if image.stride == expected_stride:
        # Padding yok — doğrudan frombytes
        buf = bytes(image.data) if not isinstance(image.data, bytes) else image.data
    else:
        # Padding var — her satırdan sadece width*3 byte al
        rows = []
        for y in range(image.height):
            row_start = y * image.stride
            rows.append(image.data[row_start:row_start + expected_stride])
        buf = b"".join(rows)

    pil_img = Image.frombytes(
        mode="RGB",
        size=(image.width, image.height),
        data=buf,
    )
    # SmolVLM RGB bekliyor — format güvencesi
    if pil_img.mode != "RGB":
        pil_img = pil_img.convert("RGB")
    return pil_img


def _emergency_result(reason: str) -> VlmResult:
    """
    vlm_init/image_validation gibi pre-parse hatalarda döndürülen güvenli struct.
    Bu seviyede parse_vlm_output henüz çağrılmadığından burada üretilir.
    """
    return VlmResult(
        status            = VlmPlantStatus.UNKNOWN,
        confidence        = 0.0,
        diagnosis         = f"engine_error: {reason}"[:VLM_MAX_DIAGNOSIS_LEN - 1],
        action            = VlmAction.SKIP,
        severity          = VlmSeverity.NONE,
        inference_time_ms = 0,
    )


# ---------------------------------------------------------------------------
# Umut yaklaşımı — ham metin → deterministik JSON
# ---------------------------------------------------------------------------

def _classify_raw_to_json(raw_text: str) -> str:
    """
    Modelin tek kelime cevabını alıp _RAW_TO_JSON_MAP üzerinden tam JSON
    string'i üretir. parse_vlm_output bunu sorunsuz okur.

    Mantık vlm_server.py:analyze_image ile birebir aynı:
      - "diseased" / "weed" / "healthy" kelimesini ara (öncelik sırası önemli)
      - Bulursa eylem + severity + diagnosis'i STATUS_MAP'ten al
      - Bulamazsa unknown + skip + safe default
      - Confidence: cevap tam olarak tek kelimeyse 0.85, gürültülüyse 0.60
    """
    import json as _json   # geç import

    if not raw_text or not isinstance(raw_text, str):
        return _json.dumps({
            "status": "unknown",
            "confidence": 0.0,
            "diagnosis": "empty or non-string model output",
            "action": "skip",
            "severity": "none",
        })

    text_lower = raw_text.lower()
    matched: "str | None" = None
    # Öncelik: diseased > weed > healthy
    # (Modelin "weed" ve "healthy" birlikte saçma cümle kurma riskine karşı)
    for candidate in ("diseased", "weed", "healthy"):
        if candidate in text_lower:
            matched = candidate
            break

    if matched is None:
        return _json.dumps({
            "status":     "unknown",
            "confidence": 0.0,
            "diagnosis":  f"unrecognized model output: {raw_text.strip()[:180]}",
            "action":     "skip",
            "severity":   "none",
        })

    action, severity, diagnosis = _RAW_TO_JSON_MAP[matched]

    # Temiz tek kelime → yüksek confidence; etrafında gürültü varsa düşük
    clean = raw_text.strip().lower().strip(".!?,;:\"' ")
    confidence = _CONF_CLEAN if clean == matched else _CONF_NOISY

    return _json.dumps({
        "status":     matched,
        "confidence": confidence,
        "diagnosis":  diagnosis,
        "action":     action,
        "severity":   severity,
    })


# ---------------------------------------------------------------------------
# YOLO Bypass yardımcıları
# ---------------------------------------------------------------------------
# Gate atlanırsa — YOLO'nun verdiği sınıfa göre action/severity defaults.
# Mantık PROMPT_V1'deki kuralı birebir takip eder; bu sayede MOD-04 hem
# bypass durumunda hem gerçek VLM durumunda aynı semantiği görür.

_YOLO_BYPASS_ACTION: dict[VlmPlantStatus, VlmAction] = {
    VlmPlantStatus.HEALTHY:  VlmAction.SKIP,    # sağlıklı elma — dokunma
    VlmPlantStatus.DISEASED: VlmAction.SPRAY,   # hastalıklı elma — ilaçla
    VlmPlantStatus.WEED:     VlmAction.LASER,   # yabani ot — lazerle yak
    VlmPlantStatus.UNKNOWN:  VlmAction.SKIP,    # belirsiz — güvenli geç
}

# Severity haritası (vlm_server.py STATUS_MAP ile birebir aynı):
#  HEALTHY  → NONE (sağlıklı, müdahale yok)
#  DISEASED → MEDIUM (hastalık tespit, ilaçla)
#  WEED     → NONE (yabani ot; eylem tek tip, severity ayrımı anlamsız)
#  UNKNOWN  → NONE (güvenli geç)
_YOLO_BYPASS_SEVERITY: dict[VlmPlantStatus, VlmSeverity] = {
    VlmPlantStatus.HEALTHY:  VlmSeverity.NONE,
    VlmPlantStatus.DISEASED: VlmSeverity.MEDIUM,
    VlmPlantStatus.WEED:     VlmSeverity.NONE,
    VlmPlantStatus.UNKNOWN:  VlmSeverity.NONE,
}


def _yolo_confident_enough(image: VlmImage) -> bool:
    """
    Sınıf bazlı YOLO bypass koşulu.

    YOLO_VLM_THRESHOLDS'daki sınıf-spesifik eşiği kullanır:
      WEED     → eşik 0.0 → her confidence'ta bypass (ot tespitine güven)
      HEALTHY  → eşik 0.75 → yüksek conf'ta bypass, düşükte VLM
      DISEASED → eşik 0.75 → yüksek conf'ta bypass, düşükte VLM
      bilinmeyen → bypass yok, VLM çalışır

    Mantık: YOLO ot vs elma ayrımında güvenilir; healthy vs diseased
    ayrımında VLM'in second opinion'ı değerli.
    """
    if image.yolo_class_id not in YOLO_TO_PLANT_STATUS:
        return False
    threshold = YOLO_VLM_THRESHOLDS.get(
        image.yolo_class_id,
        YOLO_VLM_TRIGGER_THRESHOLD + 1.0,   # bilinmeyen sınıf → asla bypass
    )
    return image.yolo_confidence >= threshold


def _synthesize_from_yolo(yolo_class_id: int, yolo_confidence: float) -> VlmResult:
    """
    VLM hiç çağrılmadığında YOLO sonucundan VlmResult üretir.
    MOD-04 bu struct'ı normal bir VLM çıktısı gibi alır.

    diagnosis'a "yolo_bypass:" prefix konur — log'larda ve saha raporunda
    bu kararın YOLO'dan geldiği görünür. inference_time_ms = 0 olduğu için
    raporda da hangi bitkilerde VLM çalışmadığı kolayca sayılabilir.
    """
    plant_status = YOLO_TO_PLANT_STATUS.get(yolo_class_id, VlmPlantStatus.UNKNOWN)

    return VlmResult(
        status            = plant_status,
        confidence        = float(yolo_confidence),
        diagnosis         = (
            f"yolo_bypass: class={plant_status.name} "
            f"conf={yolo_confidence:.2f} (VLM not invoked)"
        )[:VLM_MAX_DIAGNOSIS_LEN - 1],
        action            = _YOLO_BYPASS_ACTION[plant_status],
        severity          = _YOLO_BYPASS_SEVERITY[plant_status],
        inference_time_ms = 0,   # VLM çalışmadı — raporda kazanım görünür
    )


# ---------------------------------------------------------------------------
# CLI test yardımcısı — "python vlm_engine.py <model_path> <image_path>" ile çalıştır
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if len(sys.argv) < 2:
        print("Kullanım: python vlm_engine.py <image_path> [model_repo]")
        print(f"  image_path  : test görüntüsü (.jpg / .png)")
        print(f"  model_repo  : opsiyonel — HF repo (default: {HF_MODEL_ID})")
        sys.exit(1)

    image_path = sys.argv[1]
    model_path = sys.argv[2] if len(sys.argv) >= 3 else HF_MODEL_ID

    # Model yükle
    status = vlm_init(model_path, verbose_logging=True)
    if status != VlmStatus.OK:
        print(f"[HATA] Model yüklenemedi: {status}")
        sys.exit(1)

    # Test görüntüsünü VlmImage'a dönüştür
    pil_img = Image.open(image_path).convert("RGB").resize((VLM_CROP_SIZE, VLM_CROP_SIZE))
    raw_bytes = pil_img.tobytes()
    test_image = VlmImage(
        data         = raw_bytes,
        width        = VLM_CROP_SIZE,
        height       = VLM_CROP_SIZE,
        stride       = VLM_CROP_SIZE * 3,
        timestamp_ms = int(time.time() * 1000),
    )

    # Analiz et
    parse_status, result = vlm_analyze_plant(test_image)

    print("\n── VLM SONUCU ──────────────────────────────")
    print(f"  Parse status   : {parse_status.name}")
    print(f"  Plant status   : {result.status.name}")
    print(f"  Confidence     : {result.confidence:.2f}")
    print(f"  Diagnosis      : {result.diagnosis}")
    print(f"  Action         : {result.action.name}")
    print(f"  Severity       : {result.severity.name}")
    print(f"  Inference time : {result.inference_time_ms} ms")
    print("────────────────────────────────────────────\n")

    vlm_shutdown()
