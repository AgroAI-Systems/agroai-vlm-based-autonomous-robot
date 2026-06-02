"""
test_parser.py — MOD-03 (VLM) parser unit test suite

Çalıştır:
    cd src/vlm
    pytest tests/test_parser.py -v

Hedef: %90+ coverage, sıfır crash, tüm patolojik senaryolar test edilmiş.

Geliştirici: Bekir Göktepe (220104004018)
Modül: MOD-03 — VLM Plant Analysis (CSE396 — Group 9)
"""

import sys
import os

# src/vlm klasörünü import path'e ekle (pytest'i herhangi bir dizinden çalıştırmak için)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from mock_vlm import SCENARIOS, MockVlmEngine
from vlm_parser import _extract_json_block, parse_vlm_output
from vlm_types import VlmAction, VlmPlantStatus, VlmResult, VlmSeverity, VlmStatus


# ===========================================================================
# Başarılı parse senaryoları
# ===========================================================================

class TestValidScenarios:
    def test_valid_healthy(self):
        status, result = parse_vlm_output(SCENARIOS["valid_healthy"], 12000)
        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.HEALTHY
        assert result.confidence == pytest.approx(0.92)
        assert result.action == VlmAction.SKIP   # apple healthy → no intervention
        assert result.severity == VlmSeverity.NONE
        assert result.inference_time_ms == 12000

    def test_valid_diseased(self):
        status, result = parse_vlm_output(SCENARIOS["valid_diseased"], 25000)
        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.DISEASED
        assert result.confidence == pytest.approx(0.81)   # apple scab senaryosu
        assert result.action == VlmAction.SPRAY
        assert result.severity == VlmSeverity.MEDIUM
        assert "apple" in result.diagnosis.lower() or "scab" in result.diagnosis.lower()

    def test_valid_weed(self):
        status, result = parse_vlm_output(SCENARIOS["valid_weed"], 18000)
        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.WEED
        assert result.confidence == pytest.approx(0.86)
        assert result.action == VlmAction.LASER
        assert result.severity == VlmSeverity.HIGH

    def test_low_confidence_still_ok(self):
        """Düşük confidence parse hatası değildir — MOD-04'ün kararı."""
        status, result = parse_vlm_output(SCENARIOS["low_confidence"], 30000)
        assert status == VlmStatus.OK
        assert result.confidence == pytest.approx(0.32)
        assert result.action == VlmAction.SKIP

    def test_unicode_diagnosis_preserved(self):
        status, result = parse_vlm_output(SCENARIOS["unicode_diagnosis"], 22000)
        assert status == VlmStatus.OK
        assert "sarı" in result.diagnosis
        assert "küf" in result.diagnosis


# ===========================================================================
# Parse hataları — ERR_PARSE + safe_default
# ===========================================================================

class TestParseFailures:
    def test_empty_string_returns_err_parse(self):
        status, result = parse_vlm_output("", 0)
        assert status == VlmStatus.ERR_PARSE
        assert result.status == VlmPlantStatus.UNKNOWN
        assert result.action == VlmAction.SKIP
        assert result.confidence == 0.0

    def test_none_input_returns_err_parse(self):
        status, result = parse_vlm_output(None, 0)
        assert status == VlmStatus.ERR_PARSE
        assert result.action == VlmAction.SKIP

    def test_malformed_json_with_keyword_layer7_recovers(self):
        """
        Layer 7 davranışı: bozuk JSON ama içinde 'healthy' kelimesi var
        → keyword fallback ile OK döner. Bekir'in defense-in-depth katmanının
        zaferi — eskiden ERR_PARSE'tı, şimdi anlamlı sonuç çıkıyor.
        """
        status, result = parse_vlm_output(SCENARIOS["malformed"], 8000)
        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.HEALTHY
        assert "keyword_fallback" in result.diagnosis

    def test_free_text_only_layer7_recovers(self):
        # "This plant looks very healthy! No issues detected." → Layer 7 yakalar
        status, result = parse_vlm_output(SCENARIOS["free_text_only"], 5000)
        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.HEALTHY

    def test_inference_failed_string_returns_err_parse(self):
        status, result = parse_vlm_output(SCENARIOS["inference_failed"], 0)
        assert status == VlmStatus.ERR_PARSE

    def test_integer_input_returns_err_parse(self):
        status, result = parse_vlm_output(42, 0)  # type: ignore
        assert status == VlmStatus.ERR_PARSE

    def test_list_input_returns_err_parse(self):
        status, result = parse_vlm_output([], 0)  # type: ignore
        assert status == VlmStatus.ERR_PARSE


# ===========================================================================
# Hallucination filtresi
# ===========================================================================

class TestHallucinationFilter:
    def test_hallucinated_text_extracted_and_parsed(self):
        """Model JSON'u serbest metin içine gömdüğünde parse başarılı olmalı."""
        status, result = parse_vlm_output(SCENARIOS["hallucinated"], 14000)
        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.HEALTHY
        assert result.confidence == pytest.approx(0.90)

    def test_extract_json_block_basic(self):
        text = 'Here is the result: {"key": "value"} done.'
        extracted = _extract_json_block(text)
        assert extracted == '{"key": "value"}'

    def test_extract_json_block_no_braces(self):
        assert _extract_json_block("no braces here") is None

    def test_extract_json_block_only_open(self):
        assert _extract_json_block("{ no close") is None

    def test_extract_json_block_empty_string(self):
        assert _extract_json_block("") is None

    def test_extract_json_block_nested(self):
        text = 'prefix {"outer": {"inner": 1}} suffix'
        extracted = _extract_json_block(text)
        # İlk { ile son } arasını alır
        assert extracted == '{"outer": {"inner": 1}}'


# ===========================================================================
# Field-level validation — fallback davranışı
# ===========================================================================

class TestFieldValidation:
    def test_missing_confidence_falls_back_to_zero(self):
        status, result = parse_vlm_output(SCENARIOS["missing_field"], 13000)
        assert status == VlmStatus.OK          # Diğer field'lar geçerli
        assert result.confidence == 0.0        # Fallback

    def test_confidence_clamped_high(self):
        status, result = parse_vlm_output(SCENARIOS["out_of_range_confidence_high"], 10000)
        assert status == VlmStatus.OK
        assert result.confidence == pytest.approx(1.0)

    def test_confidence_clamped_negative(self):
        status, result = parse_vlm_output(SCENARIOS["out_of_range_confidence_negative"], 10000)
        assert status == VlmStatus.OK
        assert result.confidence == pytest.approx(0.0)

    def test_wrong_type_confidence_falls_back(self):
        status, result = parse_vlm_output(SCENARIOS["wrong_type_confidence"], 9000)
        assert status == VlmStatus.OK
        assert result.confidence == 0.0

    def test_wrong_enum_status_falls_back_to_unknown(self):
        status, result = parse_vlm_output(SCENARIOS["wrong_enum"], 9000)
        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.UNKNOWN
        assert result.action == VlmAction.SKIP  # 'teleport' → SKIP

    def test_nested_status_falls_back_to_unknown(self):
        status, result = parse_vlm_output(SCENARIOS["nested_json"], 11000)
        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.UNKNOWN

    def test_mixed_case_values_normalized(self):
        # mock_vlm bu senaryoda action="SPRAY" (büyük harf) gönderiyor;
        # parser bunu küçük harfe çevirip enum'a map eder — kararı VLM verdi, biz değil.
        status, result = parse_vlm_output(SCENARIOS["mixed_case_status"], 10000)
        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.HEALTHY
        assert result.action == VlmAction.SPRAY

    def test_whitespace_values_stripped(self):
        status, result = parse_vlm_output(SCENARIOS["whitespace_values"], 10000)
        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.HEALTHY
        assert result.action == VlmAction.SPRAY
        assert result.severity == VlmSeverity.NONE

    def test_extra_fields_ignored(self):
        status, result = parse_vlm_output(SCENARIOS["extra_fields"], 12000)
        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.WEED

    def test_diagnosis_truncated_to_255(self):
        long_diag = "x" * 1000
        payload = (
            f'{{"status":"healthy","confidence":0.9,'
            f'"diagnosis":"{long_diag}","action":"spray","severity":"none"}}'
        )
        status, result = parse_vlm_output(payload, 5000)
        assert status == VlmStatus.OK
        assert len(result.diagnosis) <= 255


# ===========================================================================
# VlmResult struct garantileri
# ===========================================================================

class TestResultGuarantees:
    def test_result_always_has_valid_confidence_range(self):
        """Her senaryoda confidence [0.0, 1.0] aralığında olmalı."""
        for name, text in SCENARIOS.items():
            _, result = parse_vlm_output(text, 10000)
            assert 0.0 <= result.confidence <= 1.0, (
                f"Scenario '{name}': confidence={result.confidence} out of range"
            )

    def test_result_action_always_valid(self):
        """Her senaryoda action geçerli bir VlmAction olmalı."""
        for name, text in SCENARIOS.items():
            _, result = parse_vlm_output(text, 10000)
            assert result.action in (VlmAction.SKIP, VlmAction.SPRAY, VlmAction.LASER), (
                f"Scenario '{name}': invalid action={result.action}"
            )

    def test_result_diagnosis_always_string(self):
        """Her senaryoda diagnosis bir string olmalı."""
        for name, text in SCENARIOS.items():
            _, result = parse_vlm_output(text, 10000)
            assert isinstance(result.diagnosis, str), (
                f"Scenario '{name}': diagnosis is not str"
            )
            assert len(result.diagnosis) <= 255, (
                f"Scenario '{name}': diagnosis exceeds 255 chars"
            )

    def test_result_status_always_valid(self):
        """Her senaryoda plant status geçerli bir VlmPlantStatus olmalı."""
        valid_statuses = set(VlmPlantStatus)
        for name, text in SCENARIOS.items():
            _, result = parse_vlm_output(text, 10000)
            assert result.status in valid_statuses, (
                f"Scenario '{name}': invalid status={result.status}"
            )

    @pytest.mark.parametrize("scenario_name", list(SCENARIOS.keys()))
    def test_no_scenario_crashes(self, scenario_name):
        """Hiçbir senaryo parser'ı crash ettirmemeli — temel crash-free garantisi."""
        try:
            status, result = parse_vlm_output(SCENARIOS[scenario_name], 10000)
            assert isinstance(result, VlmResult)
        except Exception as exc:
            pytest.fail(f"Scenario '{scenario_name}' raised exception: {exc}")

    def test_safe_default_inference_time_preserved(self):
        """ERR_PARSE durumunda bile inference_time_ms doğru aktarılmalı."""
        _, result = parse_vlm_output("", 42000)
        assert result.inference_time_ms == 42000

    def test_ok_inference_time_preserved(self):
        _, result = parse_vlm_output(SCENARIOS["valid_healthy"], 33000)
        assert result.inference_time_ms == 33000


# ===========================================================================
# to_c_compatible_dict testi
# ===========================================================================

class TestCCompatibleDict:
    def test_dict_keys_present(self):
        _, result = parse_vlm_output(SCENARIOS["valid_healthy"], 10000)
        d = result.to_c_compatible_dict()
        assert set(d.keys()) == {
            "status", "confidence", "diagnosis",
            "action", "severity", "inference_time_ms"
        }

    def test_dict_status_is_int(self):
        _, result = parse_vlm_output(SCENARIOS["valid_weed"], 10000)
        d = result.to_c_compatible_dict()
        assert isinstance(d["status"], int)
        assert d["status"] == int(VlmPlantStatus.WEED)   # mod3.h: VLM_STATUS_WEED = 2

    def test_dict_action_is_int(self):
        _, result = parse_vlm_output(SCENARIOS["valid_weed"], 10000)
        d = result.to_c_compatible_dict()
        assert isinstance(d["action"], int)
        assert d["action"] == int(VlmAction.LASER)        # mod3.h: VLM_ACTION_LASER = 2

    def test_dict_diagnosis_length(self):
        long_diag = "y" * 1000
        payload = (
            f'{{"status":"healthy","confidence":0.9,'
            f'"diagnosis":"{long_diag}","action":"spray","severity":"none"}}'
        )
        _, result = parse_vlm_output(payload, 5000)
        d = result.to_c_compatible_dict()
        assert len(d["diagnosis"]) <= 255


# ===========================================================================
# MockVlmEngine testi
# ===========================================================================

class TestMockVlmEngine:
    def test_mock_returns_tuple(self):
        engine = MockVlmEngine("valid_healthy")
        raw, ms = engine.run_inference(None, "test prompt")
        assert isinstance(raw, str)
        assert isinstance(ms, int)

    def test_mock_unknown_scenario_raises(self):
        with pytest.raises(ValueError):
            MockVlmEngine("nonexistent_scenario")

    def test_mock_set_scenario(self):
        engine = MockVlmEngine("valid_healthy")
        engine.set_scenario("valid_weed")
        raw, _ = engine.run_inference(None, "")
        assert "weed" in raw

    def test_mock_with_parser_integration(self):
        """Mock → parse_vlm_output zinciri tam çalışmalı."""
        engine = MockVlmEngine("valid_diseased")
        raw, ms = engine.run_inference(None, "analyze plant")
        status, result = parse_vlm_output(raw, ms)
        assert status == VlmStatus.OK
        assert result.status == VlmPlantStatus.DISEASED
