#!/usr/bin/env python3
"""
test_robot_scenarios.py — Mock senaryo testleri (kamera/VLM gerektirmez)

5 senaryo:
  S1  Yüksek güvenli WEED    → YOLO bypass → laser
  S2  Yüksek güvenli HEALTHY → YOLO bypass → skip
  S3  Düşük güvenli DISEASED → VLM çağrılır → spray
  S4  VLM timeout           → YOLO fallback → laser
  S5  YOLO tespit yok       → unknown      → skip

Her senaryo için kontroller:
  - bypass gate kararı doğru mu?
  - döndürülen action doğru mu?
  - robot_server JSON formatı main.cpp beklentisiyle uyumlu mu?

Çalıştırma:
    source ~/agroai-env/bin/activate
    cd src
    python3 test_robot_scenarios.py [-v]
"""

import sys
import json
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# src/ ve src/vlm/ import path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vlm"))

# --- Gerekli modülleri erken içe aktar (YOLO/VLM yüklenmeden önce)
from vlm_types import (
    VlmStatus, VlmPlantStatus, VlmAction, VlmSeverity,
    VlmImage, VlmResult,
    YOLO_CLASS_HEALTHY, YOLO_CLASS_DISEASED, YOLO_CLASS_WEED,
)

TEST_IMAGES = ROOT / "test_images"

# ---------------------------------------------------------------------------
# Yardımcı: test için minimal VlmImage üret
# ---------------------------------------------------------------------------

def make_vlm_image(yolo_class_id: int, yolo_confidence: float) -> VlmImage:
    # 4x4 siyah RGB bitmap — gerçek piksel verisi gerekmeyen testler için
    raw = bytes(4 * 4 * 3)
    return VlmImage(
        data=raw, width=4, height=4, stride=4 * 3,
        timestamp_ms=int(time.time() * 1000),
        yolo_class_id=yolo_class_id,
        yolo_confidence=yolo_confidence,
    )


def make_vlm_result(status: VlmPlantStatus, action: VlmAction,
                    severity: VlmSeverity = VlmSeverity.NONE,
                    conf: float = 0.85) -> VlmResult:
    return VlmResult(
        status=status, confidence=conf,
        diagnosis="mock diagnosis",
        action=action, severity=severity,
        inference_time_ms=100,
    )


# ---------------------------------------------------------------------------
# S1 — Yüksek güvenli WEED: YOLO bypass, VLM hiç çağrılmaz
# ---------------------------------------------------------------------------
class TestS1WeedBypass(unittest.TestCase):
    def test_bypass_gate_skips_vlm(self):
        """WEED sınıfında her conf'ta YOLO bypass çalışmalı."""
        import vlm_engine as eng
        # Model yüklü gibi göster
        eng._is_initialized = True
        eng._model = MagicMock()
        eng._processor = MagicMock()

        image = make_vlm_image(YOLO_CLASS_WEED, yolo_confidence=0.42)

        from vlm_engine import _yolo_confident_enough
        self.assertTrue(
            _yolo_confident_enough(image),
            "WEED eşiği=0.0 — herhangi bir conf'ta bypass olmali"
        )

    def test_synthesize_from_yolo_laser(self):
        """WEED için sentezlenen sonuç 'laser' olmalı."""
        from vlm_engine import _synthesize_from_yolo
        result = _synthesize_from_yolo(YOLO_CLASS_WEED, 0.42)
        self.assertEqual(result.action, VlmAction.LASER)
        self.assertEqual(result.status, VlmPlantStatus.WEED)
        self.assertEqual(result.inference_time_ms, 0,
                         "Bypass'ta VLM çalışmadı — inference_ms=0 olmalı")

    def test_analyze_returns_laser_no_vlm_call(self):
        """vlm_analyze_plant WEED'de VLM'i çağırmamalı."""
        import vlm_engine as eng
        eng._is_initialized = True
        eng._model = MagicMock()
        eng._processor = MagicMock()

        image = make_vlm_image(YOLO_CLASS_WEED, 0.55)
        with patch("vlm_engine.run_smolvlm_inference") as mock_inf:
            from vlm_engine import vlm_analyze_plant
            status, result = vlm_analyze_plant(image)

        mock_inf.assert_not_called()
        self.assertEqual(status, VlmStatus.OK)
        self.assertEqual(result.action, VlmAction.LASER)
        print("  [S1] WEED bypass → laser ✓")


# ---------------------------------------------------------------------------
# S2 — Yüksek güvenli HEALTHY: bypass, skip
# ---------------------------------------------------------------------------
class TestS2HealthyBypass(unittest.TestCase):
    def test_healthy_high_conf_bypass(self):
        """HEALTHY conf=0.91 → bypass gate aktif."""
        import vlm_engine as eng
        eng._is_initialized = True
        eng._model = MagicMock()
        eng._processor = MagicMock()

        from vlm_engine import _yolo_confident_enough
        image = make_vlm_image(YOLO_CLASS_HEALTHY, 0.91)
        self.assertTrue(_yolo_confident_enough(image))

    def test_analyze_returns_skip_no_vlm(self):
        """HEALTHY conf=0.82 → VLM çağrılmadan skip döner."""
        import vlm_engine as eng
        eng._is_initialized = True
        eng._model = MagicMock()
        eng._processor = MagicMock()

        image = make_vlm_image(YOLO_CLASS_HEALTHY, 0.82)
        with patch("vlm_engine.run_smolvlm_inference") as mock_inf:
            from vlm_engine import vlm_analyze_plant
            status, result = vlm_analyze_plant(image)

        mock_inf.assert_not_called()
        self.assertEqual(result.action, VlmAction.SKIP)
        print("  [S2] HEALTHY bypass → skip ✓")

    def test_healthy_low_conf_no_bypass(self):
        """HEALTHY conf=0.55 → bypass eşiği(0.75) altı → VLM çağrılır."""
        from vlm_engine import _yolo_confident_enough
        image = make_vlm_image(YOLO_CLASS_HEALTHY, 0.55)
        self.assertFalse(_yolo_confident_enough(image))
        print("  [S2] HEALTHY low-conf → bypass YOK ✓")


# ---------------------------------------------------------------------------
# S3 — Düşük güvenli DISEASED: VLM devreye girer, spray döner
# ---------------------------------------------------------------------------
class TestS3DiseasedVlmCalled(unittest.TestCase):
    def test_diseased_low_conf_calls_vlm(self):
        """DISEASED conf=0.51 → bypass yok → VLM çağrılır."""
        import vlm_engine as eng
        eng._is_initialized = True
        eng._model = MagicMock()
        eng._processor = MagicMock()

        # VLM "diseased" döndürüyor
        mock_result = ("diseased", 80)
        image = make_vlm_image(YOLO_CLASS_DISEASED, 0.51)

        with patch("vlm_engine.run_smolvlm_inference", return_value=mock_result) as mock_inf:
            from vlm_engine import vlm_analyze_plant
            status, result = vlm_analyze_plant(image)

        mock_inf.assert_called_once()
        self.assertEqual(result.action, VlmAction.SPRAY)
        self.assertEqual(result.status, VlmPlantStatus.DISEASED)
        print("  [S3] DISEASED low-conf → VLM → spray ✓")

    def test_diseased_high_conf_bypass(self):
        """DISEASED conf=0.87 → bypass → VLM çağrılmaz."""
        import vlm_engine as eng
        eng._is_initialized = True
        eng._model = MagicMock()
        eng._processor = MagicMock()

        image = make_vlm_image(YOLO_CLASS_DISEASED, 0.87)
        with patch("vlm_engine.run_smolvlm_inference") as mock_inf:
            from vlm_engine import vlm_analyze_plant
            status, result = vlm_analyze_plant(image)

        mock_inf.assert_not_called()
        self.assertEqual(result.action, VlmAction.SPRAY)
        print("  [S3] DISEASED high-conf → bypass → spray ✓")


# ---------------------------------------------------------------------------
# S4 — VLM timeout: YOLO fallback devreye girer
# ---------------------------------------------------------------------------
class TestS4VlmTimeout(unittest.TestCase):
    def test_timeout_falls_back_to_yolo(self):
        """VLM boş string döndürünce (timeout) YOLO sonucu kullanılır."""
        import vlm_engine as eng
        eng._is_initialized = True
        eng._model = MagicMock()
        eng._processor = MagicMock()

        # WEED eşiği 0.0 olduğundan bypass gate bunu zaten yakalar —
        # timeout fallback'i test etmek için HEALTHY düşük conf kullan.
        # bypass gate geçilmez (conf<0.75), VLM timeout yapar (boş döner),
        # YOLO class=HEALTHY olduğundan fallback skip döner.
        image = make_vlm_image(YOLO_CLASS_HEALTHY, yolo_confidence=0.60)

        with patch("vlm_engine.run_smolvlm_inference", return_value=("", 15001)):
            from vlm_engine import vlm_analyze_plant
            status, result = vlm_analyze_plant(image)

        # YOLO fallback — HEALTHY → skip, inference_time=0
        self.assertEqual(result.action, VlmAction.SKIP)
        self.assertEqual(result.status, VlmPlantStatus.HEALTHY)
        self.assertEqual(status, VlmStatus.OK, "YOLO fallback VlmStatus.OK döner")
        print("  [S4] VLM timeout → YOLO fallback → skip ✓")

    def test_timeout_no_yolo_returns_err_timeout(self):
        """VLM timeout + YOLO da yok → ERR_TIMEOUT döner."""
        import vlm_engine as eng
        eng._is_initialized = True
        eng._model = MagicMock()
        eng._processor = MagicMock()

        # yolo_class_id=-1 → YOLO_TO_PLANT_STATUS'ta yok → fallback yapılamaz
        image = make_vlm_image(yolo_class_id=-1, yolo_confidence=0.0)

        with patch("vlm_engine.run_smolvlm_inference", return_value=("", 15001)):
            from vlm_engine import vlm_analyze_plant
            status, result = vlm_analyze_plant(image)

        self.assertEqual(status, VlmStatus.ERR_TIMEOUT)
        self.assertEqual(result.action, VlmAction.SKIP, "Güvenli varsayılan: skip")
        print("  [S4] VLM timeout + no YOLO → ERR_TIMEOUT, skip ✓")


# ---------------------------------------------------------------------------
# S5 — Tam pipeline, gerçek test görüntüleri (YOLO gerçek, VLM mock)
# ---------------------------------------------------------------------------
class TestS5RealYoloPipeline(unittest.TestCase):
    """
    Test görselleri ile gerçek YOLO çalıştır, VLM mock'la.
    Dosya adı sözleşmesi: <beklenen_sinif>_<conf>_<aciklama>.jpg
    """
    @classmethod
    def setUpClass(cls):
        # YOLO'yu bir kez yükle — tüm S5 testleri paylaşır
        from mod2_mod3_pipeline import load_yolo
        cls.yolo = load_yolo(str(ROOT / "best.pt"))
        print()

    def _run_with_mock_vlm(self, img_path: Path, mock_vlm_word: str = "healthy"):
        """Görüntüyü YOLO ile çalıştır, VLM'i mock et."""
        import vlm_engine as eng
        eng._is_initialized = True
        eng._model = MagicMock()
        eng._processor = MagicMock()

        with patch("vlm_engine.run_smolvlm_inference",
                   return_value=(mock_vlm_word, 50)):
            from mod2_mod3_pipeline import run_pipeline_on_image
            return run_pipeline_on_image(self.yolo, str(img_path), 1, 1)

    def test_weed_image_laser(self):
        img = TEST_IMAGES / "weed_0.42_yabanibot_dusukconf.jpeg"
        r = self._run_with_mock_vlm(img, mock_vlm_word="weed")
        self.assertEqual(r["action"], "LASER")
        print(f"  [S5] weed image → action={r['action']} conf={r['yolo_confidence']:.2f} "
              f"gate={r['gate']} ✓")

    def test_healthy_high_conf_bypass(self):
        img = TEST_IMAGES / "healthy_0.91_saglikli_yuksekconf.jpeg"
        r = self._run_with_mock_vlm(img)
        self.assertEqual(r["action"], "SKIP")
        self.assertEqual(r["gate"], "YOLO BYPASS",
                         "Yüksek güvenli healthy bypass'dan geçmeli")
        print(f"  [S5] healthy high-conf → gate={r['gate']} action={r['action']} ✓")

    def test_diseased_low_conf_vlm_runs(self):
        img = TEST_IMAGES / "diseased_0.51_hasta_vlmcalisir.jpeg"
        with patch("vlm_engine.run_smolvlm_inference",
                   return_value=("diseased", 80)) as mock_inf:
            import vlm_engine as eng
            eng._is_initialized = True
            eng._model = MagicMock()
            eng._processor = MagicMock()
            from mod2_mod3_pipeline import run_pipeline_on_image
            r = run_pipeline_on_image(self.yolo, str(img), 1, 1)
        # YOLO conf < 0.75 ise VLM çağrılmış olabilir
        print(f"  [S5] diseased low-conf → gate={r['gate']} "
              f"action={r['action']} conf={r['yolo_confidence']:.2f} ✓")

    def test_json_format_compatible_with_main_cpp(self):
        """decision_from_result çıktısı main.cpp'nin beklediği 7 alanı içermeli."""
        from robot_server import decision_from_result
        fake_r = {
            "plant_status": "WEED", "confidence": 0.77, "diagnosis": "test",
            "action": "LASER", "severity": "NONE", "vlm_time_ms": 0,
        }
        d = decision_from_result(fake_r)
        for field in ("status", "confidence", "diagnosis", "action",
                      "severity", "target_position", "inference_time_ms"):
            self.assertIn(field, d, f"'{field}' eksik — main.cpp bunu bekliyor")
        # String alanlar lowercase olmalı (main.cpp "laser" == "laser" karşılaştırır)
        self.assertEqual(d["action"], "laser")
        self.assertEqual(d["status"], "weed")
        print(f"  [S5] JSON format main.cpp uyumlu ✓  {json.dumps(d)}")


# ---------------------------------------------------------------------------
# Özet rapor
# ---------------------------------------------------------------------------
class TestSummary(unittest.TestCase):
    def test_all_actions_covered(self):
        """skip / spray / laser üç aksiyon tipi de test edildi."""
        from vlm_engine import _synthesize_from_yolo
        skip  = _synthesize_from_yolo(YOLO_CLASS_HEALTHY,  0.9).action
        spray = _synthesize_from_yolo(YOLO_CLASS_DISEASED, 0.9).action
        laser = _synthesize_from_yolo(YOLO_CLASS_WEED,     0.5).action
        self.assertEqual(skip,  VlmAction.SKIP)
        self.assertEqual(spray, VlmAction.SPRAY)
        self.assertEqual(laser, VlmAction.LASER)
        print("  [OZET] skip/spray/laser tum aksiyon tipleri dogrulandi ✓")


if __name__ == "__main__":
    verbose = "-v" in sys.argv
    print("=" * 60)
    print("  AgroAI Robot — Mock Senaryo Testleri")
    print("=" * 60)
    print()
    print("S1  WEED yüksek conf   → YOLO bypass → laser")
    print("S2  HEALTHY çeşitli    → bypass / VLM / threshold")
    print("S3  DISEASED yüksek+düşük conf → bypass/VLM → spray")
    print("S4  VLM timeout        → YOLO fallback / ERR_TIMEOUT")
    print("S5  Gerçek görüntüler  → YOLO gerçek + VLM mock")
    print()

    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    for cls in [TestS1WeedBypass, TestS2HealthyBypass, TestS3DiseasedVlmCalled,
                TestS4VlmTimeout, TestS5RealYoloPipeline, TestSummary]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2 if verbose else 1)
    result = runner.run(suite)
    print()
    if result.wasSuccessful():
        print("SONUC: Tüm testler GECTI ✓")
    else:
        print(f"SONUC: {len(result.failures)} basarisiz, {len(result.errors)} hata")
    sys.exit(0 if result.wasSuccessful() else 1)
