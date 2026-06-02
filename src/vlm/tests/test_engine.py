"""
test_engine.py — MOD-03 (VLM) engine + YOLO bypass gate testleri

Çalıştır:
    cd src/vlm
    pytest tests/test_engine.py -v

Bu testler vlm_engine.py'deki:
  - YOLO bypass gate (yüksek YOLO güveninde VLM atlanması)
  - _yolo_confident_enough() eşik kontrolü
  - _synthesize_from_yolo() YOLO→VlmResult dönüşümü
  - _emergency_result() güvenli fallback
mantıklarını doğrular.

Geliştirici: Bekir Göktepe (220104004018)
Modül: MOD-03 — VLM Plant Analysis (CSE396 — Group 9)
"""

import os
import sys

# src/vlm klasörünü import path'e ekle
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import vlm_engine
from vlm_engine import (
    _emergency_result,
    _synthesize_from_yolo,
    _yolo_confident_enough,
    vlm_analyze_plant,
)
from vlm_types import (
    YOLO_CLASS_DISEASED,
    YOLO_CLASS_HEALTHY,
    YOLO_CLASS_UNKNOWN,
    YOLO_CLASS_WEED,
    YOLO_VLM_TRIGGER_THRESHOLD,
    YOLO_VLM_THRESHOLDS,
    VlmAction,
    VlmImage,
    VlmPlantStatus,
    VlmResult,
    VlmSeverity,
    VlmStatus,
)


# ---------------------------------------------------------------------------
# Test yardımcıları
# ---------------------------------------------------------------------------

def _make_image(
    yolo_class: int = YOLO_CLASS_UNKNOWN,
    yolo_conf: float = 0.0,
    width: int = 378,
    height: int = 378,
) -> VlmImage:
    """Test için geçerli bir VlmImage üret."""
    return VlmImage(
        data            = b"\x00" * (width * height * 3),
        width           = width,
        height          = height,
        stride          = width * 3,
        timestamp_ms    = 1_700_000_000,
        yolo_class_id   = yolo_class,
        yolo_confidence = yolo_conf,
    )


@pytest.fixture
def fake_engine_ready(monkeypatch):
    """Engine'i 'init edilmiş' göster, böylece vlm_analyze_plant init kontrolünden geçer."""
    monkeypatch.setattr(vlm_engine, "_is_initialized", True)
    monkeypatch.setattr(vlm_engine, "_model", object())   # placeholder


# ===========================================================================
# _yolo_confident_enough — eşik kontrol davranışı
# ===========================================================================

class TestYoloConfidentEnough:
    # --- HEALTHY / DISEASED — eşik bazlı ---

    def test_high_confidence_healthy_passes(self):
        img = _make_image(YOLO_CLASS_HEALTHY, 0.92)
        assert _yolo_confident_enough(img) is True

    def test_high_confidence_diseased_passes(self):
        img = _make_image(YOLO_CLASS_DISEASED, 0.88)
        assert _yolo_confident_enough(img) is True

    def test_exactly_at_threshold_passes(self):
        """0.75 tam eşik → bypass (>=)."""
        img = _make_image(YOLO_CLASS_HEALTHY, YOLO_VLM_THRESHOLDS[YOLO_CLASS_HEALTHY])
        assert _yolo_confident_enough(img) is True

    def test_just_below_threshold_blocks(self):
        img = _make_image(YOLO_CLASS_HEALTHY, YOLO_VLM_THRESHOLDS[YOLO_CLASS_HEALTHY] - 0.001)
        assert _yolo_confident_enough(img) is False

    def test_low_confidence_healthy_goes_to_vlm(self):
        """Healthy düşük conf → VLM çalışmalı."""
        img = _make_image(YOLO_CLASS_HEALTHY, 0.40)
        assert _yolo_confident_enough(img) is False

    def test_low_confidence_diseased_goes_to_vlm(self):
        """Diseased düşük conf → VLM çalışmalı."""
        img = _make_image(YOLO_CLASS_DISEASED, 0.50)
        assert _yolo_confident_enough(img) is False

    # --- WEED — confidence sıfır bile olsa her zaman bypass ---

    def test_weed_zero_confidence_still_bypasses(self):
        """WEED için eşik 0.0 — confidence önemli değil, her zaman bypass."""
        img = _make_image(YOLO_CLASS_WEED, 0.0)
        assert _yolo_confident_enough(img) is True

    def test_weed_very_low_confidence_still_bypasses(self):
        img = _make_image(YOLO_CLASS_WEED, 0.10)
        assert _yolo_confident_enough(img) is True

    def test_weed_high_confidence_bypasses(self):
        img = _make_image(YOLO_CLASS_WEED, 0.99)
        assert _yolo_confident_enough(img) is True

    # --- Bilinmeyen / geçersiz sınıflar ---

    def test_unknown_class_blocks_even_high_conf(self):
        """YOLO sınıflandıramazsa güven ne olursa olsun VLM çalışsın."""
        img = _make_image(YOLO_CLASS_UNKNOWN, 0.99)
        assert _yolo_confident_enough(img) is False

    def test_invalid_class_blocks(self):
        """Tanınmayan class_id (örn. 42) bypass'i tetiklemez."""
        img = _make_image(yolo_class=42, yolo_conf=0.95)
        assert _yolo_confident_enough(img) is False

    def test_zero_confidence_healthy_blocks(self):
        img = _make_image(YOLO_CLASS_HEALTHY, 0.0)
        assert _yolo_confident_enough(img) is False

    def test_defaults_block_bypass(self):
        """MOD-02 yolo alanlarını doldurmadıysa defaults bypass tetiklemez."""
        img = VlmImage(
            data=b"\x00" * 100, width=10, height=10, stride=30, timestamp_ms=0,
        )
        assert _yolo_confident_enough(img) is False


# ===========================================================================
# _synthesize_from_yolo — YOLO → VlmResult dönüşümü
# ===========================================================================

class TestSynthesizeFromYolo:
    def test_healthy_maps_to_skip_none(self):
        result = _synthesize_from_yolo(YOLO_CLASS_HEALTHY, 0.92)
        assert isinstance(result, VlmResult)
        assert result.status == VlmPlantStatus.HEALTHY
        assert result.action == VlmAction.SKIP    # apple healthy → no intervention
        assert result.severity == VlmSeverity.NONE
        assert result.confidence == pytest.approx(0.92)

    def test_diseased_maps_to_spray_medium(self):
        result = _synthesize_from_yolo(YOLO_CLASS_DISEASED, 0.80)
        assert result.status == VlmPlantStatus.DISEASED
        assert result.action == VlmAction.SPRAY
        assert result.severity == VlmSeverity.MEDIUM

    def test_weed_maps_to_laser_none(self):
        # Umut tutarlılığı (vlm_server.py STATUS_MAP): WEED severity=NONE
        # — eylem (laser) zaten tek tip, severity ayrımı anlamsız
        result = _synthesize_from_yolo(YOLO_CLASS_WEED, 0.88)
        assert result.status == VlmPlantStatus.WEED
        assert result.action == VlmAction.LASER
        assert result.severity == VlmSeverity.NONE

    def test_unknown_yolo_class_falls_back_to_skip(self):
        result = _synthesize_from_yolo(YOLO_CLASS_UNKNOWN, 0.5)
        assert result.status == VlmPlantStatus.UNKNOWN
        assert result.action == VlmAction.SKIP

    def test_diagnosis_marks_bypass(self):
        result = _synthesize_from_yolo(YOLO_CLASS_HEALTHY, 0.92)
        assert "yolo_bypass" in result.diagnosis
        assert "HEALTHY" in result.diagnosis

    def test_inference_time_is_zero(self):
        """Bypass'ta VLM çalışmadı → inference_time_ms = 0 (telemetry'de görünür)."""
        result = _synthesize_from_yolo(YOLO_CLASS_WEED, 0.85)
        assert result.inference_time_ms == 0

    def test_diagnosis_length_safe(self):
        result = _synthesize_from_yolo(YOLO_CLASS_HEALTHY, 0.92)
        assert len(result.diagnosis) <= 255


# ===========================================================================
# vlm_analyze_plant — uçtan uca gate davranışı
# ===========================================================================

class TestVlmAnalyzeWithGate:

    def test_high_yolo_conf_bypasses_inference(self, monkeypatch, fake_engine_ready):
        """Yüksek YOLO güveninde run_moondream_inference HİÇ çağrılmamalı."""
        def _explode(*args, **kwargs):
            raise AssertionError(
                "YOLO bypass'ta run_moondream_inference çağrılmamalıydı!"
            )
        monkeypatch.setattr(vlm_engine, "run_moondream_inference", _explode)

        img = _make_image(YOLO_CLASS_HEALTHY, 0.92)
        status, result = vlm_analyze_plant(img)

        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.HEALTHY
        assert result.action == VlmAction.SKIP   # apple healthy → no intervention
        assert result.inference_time_ms == 0
        assert "yolo_bypass" in result.diagnosis

    def test_low_yolo_conf_falls_through_to_inference(
        self, monkeypatch, fake_engine_ready
    ):
        """Düşük YOLO güveninde gerçek inference çağrılmalı."""
        called = {"count": 0}

        def _fake_inference(pil_image, prompt):
            called["count"] += 1
            return (
                '{"status":"diseased","confidence":0.78,'
                '"diagnosis":"yellow spots","action":"spray","severity":"medium"}',
                22_000,
            )

        monkeypatch.setattr(vlm_engine, "run_moondream_inference", _fake_inference)

        img = _make_image(YOLO_CLASS_HEALTHY, 0.40)  # 0.40 < 0.75
        status, result = vlm_analyze_plant(img)

        assert called["count"] == 1
        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.DISEASED
        assert result.inference_time_ms == 22_000

    def test_missing_yolo_info_runs_inference(self, monkeypatch, fake_engine_ready):
        """yolo_class_id=-1 (defaults) → gate atlanmaz, VLM çalışır."""
        called = {"count": 0}

        def _fake(pil, p):
            called["count"] += 1
            return (
                '{"status":"healthy","confidence":0.9,"diagnosis":"ok",'
                '"action":"spray","severity":"none"}',
                15_000,
            )

        monkeypatch.setattr(vlm_engine, "run_moondream_inference", _fake)

        img = _make_image()  # defaults: yolo_class=-1, conf=0.0
        status, result = vlm_analyze_plant(img)

        assert called["count"] == 1
        assert status == VlmStatus.OK

    def test_uninitialized_engine_returns_err_init(self, monkeypatch):
        """vlm_init çağrılmadan vlm_analyze_plant çağrılırsa ERR_INIT döner."""
        monkeypatch.setattr(vlm_engine, "_is_initialized", False)
        monkeypatch.setattr(vlm_engine, "_model", None)

        img = _make_image(YOLO_CLASS_HEALTHY, 0.92)
        status, result = vlm_analyze_plant(img)

        assert status == VlmStatus.ERR_INIT
        assert isinstance(result, VlmResult)
        assert result.action == VlmAction.SKIP   # güvenli default

    def test_invalid_image_returns_err_invalid_input(self, fake_engine_ready):
        """Boyutu sıfır görüntü → ERR_INVALID_INPUT."""
        img = VlmImage(data=b"", width=0, height=0, stride=0, timestamp_ms=0)
        status, result = vlm_analyze_plant(img)

        assert status == VlmStatus.ERR_INVALID_INPUT
        assert result.action == VlmAction.SKIP

    def test_threshold_boundary_bypass(self, monkeypatch, fake_engine_ready):
        """conf=0.75 tam → bypass; conf=0.7499 → VLM çalışır."""
        monkeypatch.setattr(
            vlm_engine, "run_moondream_inference",
            lambda *a, **k: pytest.fail("inference çağrıldı, bypass beklenirken!"),
        )
        img = _make_image(YOLO_CLASS_HEALTHY, YOLO_VLM_THRESHOLDS[YOLO_CLASS_HEALTHY])
        status, result = vlm_analyze_plant(img)
        assert status == VlmStatus.OK
        assert result.inference_time_ms == 0

    def test_threshold_just_below_invokes_vlm(self, monkeypatch, fake_engine_ready):
        called = {"count": 0}

        def _fake(pil, p):
            called["count"] += 1
            return "healthy", 12_000

        monkeypatch.setattr(vlm_engine, "run_moondream_inference", _fake)
        img = _make_image(YOLO_CLASS_HEALTHY, YOLO_VLM_THRESHOLDS[YOLO_CLASS_HEALTHY] - 0.01)
        vlm_analyze_plant(img)
        assert called["count"] == 1

    def test_weed_zero_conf_bypasses_vlm(self, monkeypatch, fake_engine_ready):
        """WEED confidence=0.0 bile olsa VLM çağrılmamalı."""
        monkeypatch.setattr(
            vlm_engine, "run_moondream_inference",
            lambda *a, **k: pytest.fail("WEED'de VLM çağrılmamalı!"),
        )
        img = _make_image(YOLO_CLASS_WEED, 0.0)
        status, result = vlm_analyze_plant(img)
        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.WEED
        assert result.action == VlmAction.LASER
        assert result.inference_time_ms == 0

    def test_weed_low_conf_bypasses_vlm(self, monkeypatch, fake_engine_ready):
        """WEED conf=0.20 — hala bypass, VLM çalışmaz."""
        monkeypatch.setattr(
            vlm_engine, "run_moondream_inference",
            lambda *a, **k: pytest.fail("WEED'de VLM çağrılmamalı!"),
        )
        img = _make_image(YOLO_CLASS_WEED, 0.20)
        status, result = vlm_analyze_plant(img)
        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.WEED


# ===========================================================================
# _emergency_result — güvenli pre-parse fallback
# ===========================================================================

class TestEmergencyResult:
    def test_returns_safe_struct(self):
        result = _emergency_result("test_reason")
        assert isinstance(result, VlmResult)
        assert result.status == VlmPlantStatus.UNKNOWN
        assert result.action == VlmAction.SKIP
        assert result.confidence == 0.0
        assert "engine_error" in result.diagnosis
        assert "test_reason" in result.diagnosis

    def test_diagnosis_truncated(self):
        long_reason = "x" * 1000
        result = _emergency_result(long_reason)
        assert len(result.diagnosis) <= 255
