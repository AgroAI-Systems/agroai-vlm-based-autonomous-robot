"""
vlm_errors.py — MOD-03 (VLM) hata yönetimi ve string converter'lar

mod3.h'deki C fonksiyonlarının Python karşılıkları:
  vlm_status_to_string()
  vlm_plant_status_to_string()
  vlm_action_to_string()
  vlm_severity_to_string()

Geliştirici: Bekir Göktepe (220104004018)
Modül: MOD-03 — VLM Plant Analysis (CSE396 — Group 9)
"""

from vlm_types import VlmAction, VlmPlantStatus, VlmSeverity, VlmStatus


# ---------------------------------------------------------------------------
# Status → Human-readable string dönüşümleri
# (mod3.h'deki C implementasyonunun birebir Python karşılığı)
# ---------------------------------------------------------------------------

_STATUS_STRINGS: dict[VlmStatus, str] = {
    VlmStatus.OK:                "VLM_OK",
    VlmStatus.ERR_INIT:          "VLM_ERR_INIT",
    VlmStatus.ERR_INVALID_INPUT: "VLM_ERR_INVALID_INPUT",
    VlmStatus.ERR_INFERENCE:     "VLM_ERR_INFERENCE",
    VlmStatus.ERR_TIMEOUT:       "VLM_ERR_TIMEOUT",
    VlmStatus.ERR_PARSE:         "VLM_ERR_PARSE",
    VlmStatus.ERR_MEMORY:        "VLM_ERR_MEMORY",
}

_PLANT_STATUS_STRINGS: dict[VlmPlantStatus, str] = {
    VlmPlantStatus.HEALTHY:  "HEALTHY",
    VlmPlantStatus.DISEASED: "DISEASED",
    VlmPlantStatus.WEED:     "WEED",
    VlmPlantStatus.UNKNOWN:  "UNKNOWN",
}

_ACTION_STRINGS: dict[VlmAction, str] = {
    VlmAction.SKIP:  "SKIP",
    VlmAction.SPRAY: "SPRAY",
    VlmAction.LASER: "LASER",
}

_SEVERITY_STRINGS: dict[VlmSeverity, str] = {
    VlmSeverity.NONE:   "NONE",
    VlmSeverity.LOW:    "LOW",
    VlmSeverity.MEDIUM: "MEDIUM",
    VlmSeverity.HIGH:   "HIGH",
}


def vlm_status_to_string(status: VlmStatus) -> str:
    """
    mod3.h: const char* vlm_status_to_string(vlm_status_t status)

    Bilinmeyen değer için "VLM_STATUS_UNKNOWN" döndürür (crash etmez).
    """
    return _STATUS_STRINGS.get(status, f"VLM_STATUS_UNKNOWN({int(status)})")


def vlm_plant_status_to_string(status: VlmPlantStatus) -> str:
    """
    mod3.h: const char* vlm_plant_status_to_string(vlm_plant_status_t status)
    """
    return _PLANT_STATUS_STRINGS.get(status, f"PLANT_STATUS_UNKNOWN({int(status)})")


def vlm_action_to_string(action: VlmAction) -> str:
    """
    mod3.h: const char* vlm_action_to_string(vlm_action_t action)
    """
    return _ACTION_STRINGS.get(action, f"ACTION_UNKNOWN({int(action)})")


def vlm_severity_to_string(severity: VlmSeverity) -> str:
    """Severity enum'unu okunabilir string'e çevirir."""
    return _SEVERITY_STRINGS.get(severity, f"SEVERITY_UNKNOWN({int(severity)})")


# ---------------------------------------------------------------------------
# Pi 4 termal telemetry sabiti
# ---------------------------------------------------------------------------

# Pi 4'te termal throttling 80°C üzerinde tetiklenir ve inference'ı
# 45 s'den 90 s'ye çıkarabilir. Bu eşiğin üstü log'a warning düşer.
INFERENCE_TIME_WARNING_THRESHOLD_MS: int = 60_000  # 60 saniye
