"""
vlm_types.py — MOD-03 (VLM) Python type definitions

Bu dosya mod3.h'deki C kontratının Python tarafındaki karşılığıdır.
Integer değerleri mod3.h ile BİREBİR AYNI olmalı — aksi takdirde
MOD-04 entegrasyonunda sessiz hatalar oluşur.

Geliştirici: Bekir Göktepe (220104004018)
Modül: MOD-03 — VLM Plant Analysis (CSE396 — Group 9)
"""

from dataclasses import dataclass
from enum import IntEnum


# ---------------------------------------------------------------------------
# Enums (mod3.h ile birebir eşleşen integer değerler)
# ---------------------------------------------------------------------------

class VlmStatus(IntEnum):
    """vlm_status_t karşılığı — operasyon dönüş kodları."""
    OK                = 0
    ERR_INIT          = -1
    ERR_INVALID_INPUT = -2
    ERR_INFERENCE     = -3
    ERR_TIMEOUT       = -4
    ERR_PARSE         = -5
    ERR_MEMORY        = -6


class VlmPlantStatus(IntEnum):
    """vlm_plant_status_t karşılığı — bitki sınıflandırması."""
    HEALTHY  = 0
    DISEASED = 1
    WEED     = 2
    UNKNOWN  = 3


class VlmAction(IntEnum):
    """vlm_action_t karşılığı — önerilen aksiyon."""
    SKIP  = 0
    SPRAY = 1
    LASER = 2


class VlmSeverity(IntEnum):
    """vlm_severity_t karşılığı — hastalık/yabancı ot şiddeti."""
    NONE   = 0
    LOW    = 1
    MEDIUM = 2
    HIGH   = 3


# ---------------------------------------------------------------------------
# String → Enum eşleme tabloları (case-insensitive kullanım için)
# ---------------------------------------------------------------------------

PLANT_STATUS_MAP: dict[str, VlmPlantStatus] = {
    "healthy":  VlmPlantStatus.HEALTHY,
    "diseased": VlmPlantStatus.DISEASED,
    "weed":     VlmPlantStatus.WEED,
    "unknown":  VlmPlantStatus.UNKNOWN,
}

ACTION_MAP: dict[str, VlmAction] = {
    "skip":  VlmAction.SKIP,
    "spray": VlmAction.SPRAY,
    "laser": VlmAction.LASER,
}

SEVERITY_MAP: dict[str, VlmSeverity] = {
    "none":   VlmSeverity.NONE,
    "low":    VlmSeverity.LOW,
    "medium": VlmSeverity.MEDIUM,
    "high":   VlmSeverity.HIGH,
}


# ---------------------------------------------------------------------------
# VlmImage — mod3.h'deki vlm_image_t'nin Python karşılığı
# (MOD-02'den gelir, MOD-03 sadece okur)
# ---------------------------------------------------------------------------

@dataclass
class VlmImage:
    """
    vlm_image_t karşılığı — MOD-02'nin sağladığı ROI frame.

    YOLO bypass alanları (yolo_class_id, yolo_confidence) opsiyoneldir:
    MOD-02 bunları doldurursa MOD-03 yüksek güvenli durumlarda VLM'i
    tamamen atlar (Pi 4'te ~30 sn tasarruf). Doldurulmazsa (defaults)
    eski davranış aynen sürer: her zaman VLM çalışır.
    """
    data:         bytes  # RGB pixel buffer, row-major
    width:        int    # 378 px (VLM_CROP_SIZE)
    height:       int    # 378 px
    stride:       int    # width * 3 (padding yoksa)
    timestamp_ms: int    # MOD-02'nin capture timestamp'i (ms)
    # --- YOLO bypass için (opsiyonel, MOD-02'nin doldurması beklenir) ---
    yolo_class_id:   int   = -1   # 0=healthy, 1=diseased, 2=weed, -1=bilinmiyor
    yolo_confidence: float = 0.0  # [0.0, 1.0]


# ---------------------------------------------------------------------------
# VlmResult — mod3.h'deki vlm_result_t'nin Python karşılığı
# ---------------------------------------------------------------------------

# mod3.h: #define VLM_MAX_DIAGNOSIS_LEN 256  (255 char + null terminator)
VLM_MAX_DIAGNOSIS_LEN: int = 256


@dataclass
class VlmResult:
    """
    vlm_result_t karşılığı — parse edilen, doğrulanmış VLM çıktısı.

    Tüm field'lar her zaman geçerli değerler içerir.
    Parse başarısız olsa bile güvenli varsayılanlarla dolu döner —
    asla None içermez.
    """
    status:            VlmPlantStatus = VlmPlantStatus.UNKNOWN
    confidence:        float          = 0.0
    diagnosis:         str            = "no_diagnosis"
    action:            VlmAction      = VlmAction.SKIP
    severity:          VlmSeverity    = VlmSeverity.NONE
    inference_time_ms: int            = 0

    def to_c_compatible_dict(self) -> dict:
        """
        C tarafına / log'a / dashboard'a verilebilir düz dict.

        diagnosis 255 karaktere kesilir: mod3.h VLM_MAX_DIAGNOSIS_LEN=256
        sabitinin içine null-terminator için 1 byte yer bırakılır.
        """
        return {
            "status":            int(self.status),
            "confidence":        float(self.confidence),
            "diagnosis":         self.diagnosis[:VLM_MAX_DIAGNOSIS_LEN - 1],
            "action":            int(self.action),
            "severity":          int(self.severity),
            "inference_time_ms": int(self.inference_time_ms),
        }


# ---------------------------------------------------------------------------
# YOLO → VLM bypass gate (Pi 4 performans optimizasyonu)
# ---------------------------------------------------------------------------
# Mantık: MOD-02'nin YOLO sınıflandırması bu eşiğin üstünde güven veriyorsa,
# MOD-03 inference'ı tamamen atlayıp YOLO çıktısından VlmResult sentezler.
# MOD-04 farkı görmez — aynı struct'ı alır.
#
# Eşik mission_config'ten override edilebilir hale gelirse bu sabit yedek
# default olarak kalır.

YOLO_CLASS_HEALTHY:  int = 0
YOLO_CLASS_DISEASED: int = 1
YOLO_CLASS_WEED:     int = 2
YOLO_CLASS_UNKNOWN:  int = -1   # MOD-02 sınıflandıramazsa bu kullanılır

YOLO_TO_PLANT_STATUS: dict[int, VlmPlantStatus] = {
    YOLO_CLASS_HEALTHY:  VlmPlantStatus.HEALTHY,
    YOLO_CLASS_DISEASED: VlmPlantStatus.DISEASED,
    YOLO_CLASS_WEED:     VlmPlantStatus.WEED,
}

# ---------------------------------------------------------------------------
# Sınıf bazlı YOLO bypass eşikleri
# ---------------------------------------------------------------------------
# WEED: 0.0 → YOLO ne derse desin, confidence'a bakılmadan direkt bypass.
#   Sebep: ot vs elma görsel ayrımında YOLO güvenilir, VLM bu sınırda
#   zorlanıyor (sağlıklı elma yaprağını ot olarak görebiliyor).
#
# HEALTHY / DISEASED: 0.75 → Yüksek confidence'ta bypass, altında VLM.
#   Sebep: healthy vs diseased ince bir ayrım, VLM'in second opinion'ı değerli.
#
# Varsayılan (bilinmeyen sınıf): 1.0+1 → asla bypass etme, her zaman VLM.

YOLO_VLM_TRIGGER_THRESHOLD: float = 0.75  # Genel fallback (geriye dönük uyum)

YOLO_VLM_THRESHOLDS: dict[int, float] = {
    YOLO_CLASS_WEED:     0.0,   # her conf'ta bypass — ot tespitine güven
    YOLO_CLASS_HEALTHY:  0.75,  # yüksek conf'ta bypass, düşükte VLM
    YOLO_CLASS_DISEASED: 0.75,  # yüksek conf'ta bypass, düşükte VLM
}
