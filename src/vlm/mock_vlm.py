"""
mock_vlm.py — MOD-03 (VLM) deterministik test mock'u

Gerçek MoondreamV2 modeli olmadan parser geliştirmek ve test etmek için.
Laptop'ta milisaniyeler içinde koşar; Pi 4'te 20-45 saniye beklemek gerekmez.

KULLANIM:
    from mock_vlm import MockVlmEngine, SCENARIOS

    engine = MockVlmEngine(scenario="valid_healthy")
    raw_text, elapsed_ms = engine.run_inference(image, prompt)

    # Veya direkt string:
    raw_text = SCENARIOS["malformed"]

MOD-04 entegrasyon testleri için MockVlmEngine'i vlm_engine.py'deki
gerçek engine yerine geçirebilirsiniz.

Geliştirici: Bekir Göktepe (220104004018)
Modül: MOD-03 — VLM Plant Analysis (CSE396 — Group 9)
"""

import time

# ---------------------------------------------------------------------------
# Önceden hazırlanmış senaryo string'leri
# Her yeni patolojik durum keşfedildiğinde buraya eklenmeli (regression suite).
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, str] = {
    # --- Geçerli senaryolar (elma odaklı, V2_APPLE prompt'la uyumlu) ---
    "valid_healthy": (
        '{"status": "healthy", "confidence": 0.92, '
        '"diagnosis": "apple leaves uniformly green, intact, no spots or wilting", '
        '"action": "skip", "severity": "none"}'
    ),

    "valid_diseased": (
        '{"status": "diseased", "confidence": 0.81, '
        '"diagnosis": "olive-green velvety spots on apple leaves — apple scab (Venturia inaequalis) suspected", '
        '"action": "spray", "severity": "medium"}'
    ),

    "valid_weed": (
        '{"status": "weed", "confidence": 0.86, '
        '"diagnosis": "broadleaf weed in orchard row, dandelion-like growth", '
        '"action": "laser", "severity": "high"}'
    ),

    # --- Spesifik elma hastalıkları (regression suite + demo örnekleri) ---
    "apple_scab": (
        '{"status": "diseased", "confidence": 0.88, '
        '"diagnosis": "olive-green velvety spots on multiple apple leaves — Venturia inaequalis", '
        '"action": "spray", "severity": "medium"}'
    ),

    "apple_fire_blight": (
        '{"status": "diseased", "confidence": 0.84, '
        '"diagnosis": "blackened scorched shoots and curled leaves — fire blight (Erwinia amylovora)", '
        '"action": "spray", "severity": "high"}'
    ),

    "apple_powdery_mildew": (
        '{"status": "diseased", "confidence": 0.79, '
        '"diagnosis": "white powdery coating on young apple shoots — powdery mildew", '
        '"action": "spray", "severity": "low"}'
    ),

    "apple_cedar_rust": (
        '{"status": "diseased", "confidence": 0.83, '
        '"diagnosis": "bright orange spots on apple leaves — cedar apple rust", '
        '"action": "spray", "severity": "medium"}'
    ),

    "weed_dandelion": (
        '{"status": "weed", "confidence": 0.90, '
        '"diagnosis": "dandelion (Taraxacum) in apple orchard row", '
        '"action": "laser", "severity": "high"}'
    ),

    "weed_grass": (
        '{"status": "weed", "confidence": 0.74, '
        '"diagnosis": "tall grass between apple trees", '
        '"action": "laser", "severity": "medium"}'
    ),

    "low_confidence": (
        '{"status": "diseased", "confidence": 0.32, '
        '"diagnosis": "uncertain, possible nutrient deficiency or lighting artifact", '
        '"action": "skip", "severity": "low"}'
    ),

    # --- Patolojik senaryolar ---
    "malformed": (
        '{"status": "healthy", "confidence": 0.92,'  # Kapatılmamış '}'
    ),

    "hallucinated": (
        'I analyzed the plant carefully. It looks healthy to me! '
        'Here is the structured JSON output: '
        '{"status": "healthy", "confidence": 0.90, '
        '"diagnosis": "plant appears healthy overall", '
        '"action": "spray", "severity": "none"} '
        'I hope this analysis is helpful!'
    ),

    "empty": "",

    "out_of_range_confidence_high": (
        '{"status": "healthy", "confidence": 5.5, '
        '"diagnosis": "looks good", "action": "spray", "severity": "none"}'
    ),

    "out_of_range_confidence_negative": (
        '{"status": "diseased", "confidence": -0.3, '
        '"diagnosis": "something wrong", "action": "spray", "severity": "low"}'
    ),

    "wrong_enum": (
        '{"status": "purple_dragon", "confidence": 0.7, '
        '"diagnosis": "this is a fantasy plant", '
        '"action": "teleport", "severity": "medium"}'
    ),

    "unicode_diagnosis": (
        '{"status": "diseased", "confidence": 0.81, '
        '"diagnosis": "Yaprak üzerinde sarı lekeler — küf şüphesi", '
        '"action": "spray", "severity": "medium"}'
    ),

    "missing_field": (
        '{"status": "healthy", "diagnosis": "leaves intact", '
        '"action": "spray", "severity": "none"}'
        # confidence field'ı eksik
    ),

    "wrong_type_confidence": (
        '{"status": "healthy", "confidence": "very high", '
        '"diagnosis": "ok", "action": "spray", "severity": "none"}'
    ),

    "nested_json": (
        '{"status": {"value": "healthy"}, "confidence": 0.88, '
        '"diagnosis": "nested status field", "action": "spray", "severity": "none"}'
    ),

    "mixed_case_status": (
        '{"status": "HEALTHY", "confidence": 0.75, '
        '"diagnosis": "uppercase status test", "action": "SPRAY", "severity": "NONE"}'
    ),

    "whitespace_values": (
        '{"status": "  healthy  ", "confidence": 0.80, '
        '"diagnosis": "  padded values  ", "action": "  spray  ", "severity": "  none  "}'
    ),

    "extra_fields": (
        '{"status": "weed", "confidence": 0.91, '
        '"diagnosis": "dandelion confirmed", "action": "laser", "severity": "high", '
        '"secret_field": "xyz", "model_version": "moondream-v2-int4", "raw_logits": [0.1, 0.9]}'
    ),

    "inference_failed": "INFERENCE_FAILED",

    "free_text_only": "This plant looks very healthy! No issues detected.",

    "nan_confidence": (
        '{"status": "healthy", "confidence": NaN, '
        '"diagnosis": "nan test", "action": "spray", "severity": "none"}'
        # JSON standardında NaN geçersiz → json.loads patlar → ERR_PARSE
    ),
}


# ---------------------------------------------------------------------------
# MockVlmEngine
# ---------------------------------------------------------------------------

class MockVlmEngine:
    """
    MoondreamV2 inference'ını taklit eden deterministik mock.

    Gerçek model yerine bu sınıfı kullanarak:
    - Laptop'ta saniyeler içinde test yapılır
    - Pi 4 yavaş inference beklenmez
    - Deterministic çıktılarla regression suite koşulur

    Args:
        scenario:           SCENARIOS sözlüğündeki senaryo adı.
        simulate_latency_ms: Simüle edilecek gecikme (ms).
                            Pi 4'ün 30 s gecikmesini test etmek için 30000 kullan.
    """

    def __init__(self, scenario: str = "valid_healthy", simulate_latency_ms: int = 0):
        if scenario not in SCENARIOS:
            raise ValueError(
                f"Unknown scenario '{scenario}'. "
                f"Available: {list(SCENARIOS.keys())}"
            )
        self.scenario   = scenario
        self.latency    = simulate_latency_ms
        self.call_count = 0   # YOLO bypass testleri için: kaç kez inference yapıldı?

    def run_inference(self, image, prompt: str) -> tuple[str, int]:
        """
        Umut'un run_moondream_inference() fonksiyonuyla aynı imzayı kullanır.

        Args:
            image:  VlmImage (mock'ta kullanılmaz, gerçekte kullanılır).
            prompt: Prompt string (mock'ta kullanılmaz).

        Returns:
            (raw_output_text, inference_time_ms)
        """
        self.call_count += 1
        if self.latency > 0:
            time.sleep(self.latency / 1000.0)
        return SCENARIOS[self.scenario], self.latency

    def set_scenario(self, scenario: str) -> None:
        """Test sırasında senaryoyu değiştirmek için."""
        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown scenario '{scenario}'.")
        self.scenario = scenario

    def reset(self) -> None:
        """Sayaçları sıfırla — testler arası temizlik için."""
        self.call_count = 0
