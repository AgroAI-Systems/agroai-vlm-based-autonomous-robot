"""
vlm_parser.py — MOD-03 (VLM) JSON parsing, validation ve error handling

Felsefe: Bu modül asla exception fırlatmaz. Her girdide —
null, boş, bozuk JSON, halüsinasyon — (VlmStatus, VlmResult) çifti döner.
MOD-04 her zaman dolu ve kullanılmaya hazır bir struct alır.

Defense-in-depth katmanları:
  Layer 1: Tip / null check
  Layer 2: JSON bloğunu metinden çıkarma (hallucination filtresi)
  Layer 3: json.loads syntax check
  Layer 4: Schema check (dict mi?)
  Layer 5: Field bazında validation (her field bağımsız fallback'lı)
  Layer 6: Range / enum mapping (clamp, UNKNOWN fallback)
  Layer 7: Keyword extraction fallback — JSON yoksa metinde
           'healthy/diseased/weed' kelimelerini ara, OK ile dön.
           (MoondreamV2 'answer_question' API'si kısa cevap üretir;
            modelin 'diseased' veya 'Malus domesticica' gibi düz metin
            cevapları da değerlendirmeye katılır.)

Geliştirici: Bekir Göktepe (220104004018)
Modül: MOD-03 — VLM Plant Analysis (CSE396 — Group 9)
"""

import json
import logging
from typing import Tuple

from vlm_errors import INFERENCE_TIME_WARNING_THRESHOLD_MS
from vlm_types import (
    ACTION_MAP,
    PLANT_STATUS_MAP,
    SEVERITY_MAP,
    VLM_MAX_DIAGNOSIS_LEN,
    VlmAction,
    VlmPlantStatus,
    VlmResult,
    VlmSeverity,
    VlmStatus,
)

log = logging.getLogger("vlm.parser")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_vlm_output(
    raw_text: str,
    inference_time_ms: int,
) -> Tuple[VlmStatus, VlmResult]:
    """
    Ham VLM çıktı metnini doğrulanmış VlmResult struct'ına çevirir.

    Args:
        raw_text:          MoondreamV2'den gelen ham metin (herhangi bir format).
        inference_time_ms: Inference süresi; log + telemetry için.

    Returns:
        (VlmStatus, VlmResult): status kodu ve dolu struct.
        Parse başarısız olsa bile struct güvenli varsayılanlarla DOLU döner —
        asla None içermez, asla exception fırlatmaz.
    """
    # Pi 4 termal throttling uyarısı
    if isinstance(inference_time_ms, int) and inference_time_ms > INFERENCE_TIME_WARNING_THRESHOLD_MS:
        log.warning(
            f"Slow inference: {inference_time_ms} ms — possible thermal throttle on Pi 4"
        )

    # Layer 1: Tip / null check
    if not raw_text or not isinstance(raw_text, str):
        _log_parse_failure("empty_or_non_string", str(raw_text) if raw_text is not None else "None")
        return VlmStatus.ERR_PARSE, _safe_default(inference_time_ms, "empty_or_non_string")

    # Layer 2: Hallucination filtresi — JSON bloğunu metinden çıkar
    json_str = _extract_json_block(raw_text)
    if json_str is None:
        # Layer 7 fallback: belki tek kelime cevap geldi ("diseased", "Malus domestica" vb.)
        kw_result = _try_keyword_extraction(raw_text, inference_time_ms)
        if kw_result is not None:
            log.info(f"VLM parsed via keyword fallback (no JSON): {kw_result.status.name}")
            return VlmStatus.OK, kw_result
        _log_parse_failure("no_json_found", raw_text)
        return VlmStatus.ERR_PARSE, _safe_default(inference_time_ms, "no_json_found")

    # Layer 3: JSON syntax check
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        # Layer 7 fallback: bozuk JSON ama metinde anahtar kelime olabilir
        kw_result = _try_keyword_extraction(raw_text, inference_time_ms)
        if kw_result is not None:
            log.info(f"VLM parsed via keyword fallback (json decode fail): {kw_result.status.name}")
            return VlmStatus.OK, kw_result
        _log_parse_failure(f"json_decode_fail: {exc}", raw_text)
        return VlmStatus.ERR_PARSE, _safe_default(inference_time_ms, "json_decode_fail")

    # Layer 4: Schema check
    if not isinstance(data, dict):
        kw_result = _try_keyword_extraction(raw_text, inference_time_ms)
        if kw_result is not None:
            log.info(f"VLM parsed via keyword fallback (not a dict): {kw_result.status.name}")
            return VlmStatus.OK, kw_result
        _log_parse_failure(f"not_a_dict (got {type(data).__name__})", raw_text)
        return VlmStatus.ERR_PARSE, _safe_default(inference_time_ms, "not_a_dict")

    # Layer 5 + 6: Field bazında validation (her field bağımsız fallback)
    result = VlmResult(
        status            = _validate_plant_status(data.get("status")),
        confidence        = _validate_confidence(data.get("confidence")),
        diagnosis         = _validate_diagnosis(data.get("diagnosis")),
        action            = _validate_action(data.get("action")),
        severity          = _validate_severity(data.get("severity")),
        inference_time_ms = inference_time_ms,
    )

    # Belleği erken serbest bırak — Pi 4'te RAM kıymetli
    raw_text = None  # noqa: F841

    return VlmStatus.OK, result


# ---------------------------------------------------------------------------
# Layer 2: JSON bloğunu metinden çıkarma
# ---------------------------------------------------------------------------

def _extract_json_block(text: str) -> "str | None":
    """
    İlk '{' ile son '}' arasındaki substring'i döndürür.

    Model halüsinasyon yaptığında ("Here is the JSON: {...} Hope it helps!")
    gereksiz metin parantezler arasına alınmış JSON'u gizler.
    Bu O(n) find/rfind çifti ile güvenli ve hızlı şekilde çözülür.

    Returns:
        JSON substring veya bulunamazsa None.
    """
    start = text.find('{')
    end   = text.rfind('}')
    if start == -1 or end == -1 or start >= end:
        return None
    return text[start:end + 1]


# ---------------------------------------------------------------------------
# Layer 5-6: Field-level validation fonksiyonları
# ---------------------------------------------------------------------------

def _validate_plant_status(value) -> VlmPlantStatus:
    """
    'healthy' / 'HEALTHY' / 'Healthy' → VlmPlantStatus.HEALTHY
    Bilinmeyen / yanlış tip → VlmPlantStatus.UNKNOWN
    """
    if not isinstance(value, str):
        return VlmPlantStatus.UNKNOWN
    return PLANT_STATUS_MAP.get(value.lower().strip(), VlmPlantStatus.UNKNOWN)


def _validate_confidence(value) -> float:
    """
    Confidence değerini [0.0, 1.0] aralığına sıkıştırır.
    Yanlış tip, NaN, veya out-of-range → güvenli fallback.
    """
    if not isinstance(value, (int, float)):
        return 0.0
    f = float(value)
    # NaN check (NaN != NaN her zaman True)
    if f != f:
        return 0.0
    return max(0.0, min(1.0, f))


def _validate_diagnosis(value) -> str:
    """
    Diagnosis string'ini normalize eder ve 255 karaktere keser.
    mod3.h: VLM_MAX_DIAGNOSIS_LEN=256 (255 char + 1 null terminator).
    """
    if value is None or not isinstance(value, str):
        return "no_diagnosis"
    cleaned = value.strip()
    if not cleaned:
        return "no_diagnosis"
    return cleaned[:VLM_MAX_DIAGNOSIS_LEN - 1]


def _validate_action(value) -> VlmAction:
    """
    'spray' / 'SPRAY' → VlmAction.SPRAY
    Bilinmeyen / yanlış tip → VlmAction.SKIP (güvenli varsayılan)
    """
    if not isinstance(value, str):
        return VlmAction.SKIP
    return ACTION_MAP.get(value.lower().strip(), VlmAction.SKIP)


def _validate_severity(value) -> VlmSeverity:
    """
    'high' / 'HIGH' → VlmSeverity.HIGH
    Bilinmeyen / yanlış tip → VlmSeverity.NONE
    """
    if not isinstance(value, str):
        return VlmSeverity.NONE
    return SEVERITY_MAP.get(value.lower().strip(), VlmSeverity.NONE)


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

def _safe_default(inference_time_ms: int, reason: str) -> VlmResult:
    """
    Parse başarısız olduğunda döndürülen güvenli varsayılan struct.
    MOD-04 bu struct'ı alınca ACTION_SKIP yaparak güvenle geçer.
    """
    return VlmResult(
        status            = VlmPlantStatus.UNKNOWN,
        confidence        = 0.0,
        diagnosis         = f"parse_error: {reason}"[:VLM_MAX_DIAGNOSIS_LEN - 1],
        action            = VlmAction.SKIP,
        severity          = VlmSeverity.NONE,
        inference_time_ms = inference_time_ms,
    )


# ---------------------------------------------------------------------------
# Layer 7: Keyword extraction fallback
# ---------------------------------------------------------------------------

# MoondreamV2 'answer_question' API'si kısa cevap üretir. Bekir'in 9 fotoluk
# laptop testinde modelin tipik düz metin cevapları:
#   "diseased"                    → DISEASED
#   "Malus domesticica"           → HEALTHY (botanik adı = sağlıklı elma teşhisi)
#   '"diseased" apple plant'      → DISEASED
#   "CURUK ELMALAR"               → DISEASED (Turkish: "çürük" = rotten)
#   "<healthy>"                   → HEALTHY
# Bu liste yeni patolojik çıktı görüldükçe büyür.

# Tek kelime cevaplara verilen default confidence
_KEYWORD_CONFIDENCE: float = 0.60   # JSON'dan az, mock'tan fazla — ortayolu

# Bekir'in MOD-04 ekibiyle yapacağı kontrat: tek kelime cevaplarda
# MOD-04 confidence < HIGH eşiğini görür ve isterse rescan ister.

# Anahtar kelime → VlmPlantStatus eşleme (lowercased substring araması)
_KEYWORD_TO_STATUS: list[tuple[tuple[str, ...], VlmPlantStatus]] = [
    # Önce spesifik hastalık adları (DISEASED sayılır)
    (("scab", "blight", "rust", "rot", "mildew", "lesion", "wilt",
      "curuk", "çürük", "hastalik", "hastalık", "diseased"),
     VlmPlantStatus.DISEASED),
    # Yabani ot işaretleri
    (("weed", "dandelion", "thistle", "grass", "yabani", "ot ", " ot"),
     VlmPlantStatus.WEED),
    # Sağlıklı işaretleri
    (("healthy", "saglikli", "sağlıklı", "intact", "uniform green",
      "malus domestica", "malus domesticica"),
     VlmPlantStatus.HEALTHY),
]

# YOLO bypass'taki aksiyon haritası ile birebir aynı kalır — tek karar noktası
_KEYWORD_ACTION: dict[VlmPlantStatus, VlmAction] = {
    VlmPlantStatus.HEALTHY:  VlmAction.SKIP,
    VlmPlantStatus.DISEASED: VlmAction.SPRAY,
    VlmPlantStatus.WEED:     VlmAction.LASER,
    VlmPlantStatus.UNKNOWN:  VlmAction.SKIP,
}

# vlm_server.py STATUS_MAP ile tutarli: WEED için severity NONE
# (yabani otta severity ayrımı eylem değiştirmiyor — laser her durumda)
_KEYWORD_SEVERITY: dict[VlmPlantStatus, VlmSeverity] = {
    VlmPlantStatus.HEALTHY:  VlmSeverity.NONE,
    VlmPlantStatus.DISEASED: VlmSeverity.MEDIUM,
    VlmPlantStatus.WEED:     VlmSeverity.NONE,
    VlmPlantStatus.UNKNOWN:  VlmSeverity.NONE,
}


def _try_keyword_extraction(
    raw_text: str,
    inference_time_ms: int,
) -> "VlmResult | None":
    """
    Metin içinde sınıf anahtar kelimelerini ara. Bulursa dolu VlmResult döndürür,
    bulamazsa None döner (caller safe_default'a düşer).

    Bu Layer 7 — JSON çıkmadığında devreye girer ("answer_question" tarzı
    kısa cevaplara karşı savunma).
    """
    if not raw_text or not isinstance(raw_text, str):
        return None

    text_lower = raw_text.lower()

    # Placeholder cevaplar ("<healthy|diseased|weed|unknown>") gerçek değer içermez
    # — pipe varsa veya tüm 4 enum birden geçiyorsa bunu görmezden gel.
    if "|" in text_lower and "healthy" in text_lower and "diseased" in text_lower:
        return None

    matched_status: "VlmPlantStatus | None" = None
    for keywords, status in _KEYWORD_TO_STATUS:
        if any(kw in text_lower for kw in keywords):
            matched_status = status
            break

    if matched_status is None:
        return None

    return VlmResult(
        status            = matched_status,
        confidence        = _KEYWORD_CONFIDENCE,
        diagnosis         = (
            f"keyword_fallback: {matched_status.name} extracted from "
            f"non-JSON model output: {raw_text.strip()[:150]}"
        )[:VLM_MAX_DIAGNOSIS_LEN - 1],
        action            = _KEYWORD_ACTION[matched_status],
        severity          = _KEYWORD_SEVERITY[matched_status],
        inference_time_ms = inference_time_ms,
    )


def _log_parse_failure(reason: str, raw_text: str) -> None:
    """
    Parse hatalarını raw_text ile birlikte loglar.
    1 KB üstündeki metni truncate eder — RAM koruma + log şişmesin.
    """
    if len(raw_text) > 1000:
        truncated = raw_text[:1000] + "...[truncated]"
    else:
        truncated = raw_text
    log.warning(f"VLM parse failure [{reason}]\nRaw output: {truncated}")
