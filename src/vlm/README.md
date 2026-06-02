# MOD-03 — VLM Plant Analysis

**CSE396 — Group 9 / Akıllı Tarım Robotu**
**Geliştirici:** Bekir Göktepe (220104004018)
**Modül Partneri (inference):** Umut Akman
**Donanım Hedefi:** Raspberry Pi 4 Model B, 8 GB RAM

---

## Modülün Görevi

MOD-03, MoondreamV2 VLM çıktısını alıp MOD-04 (Karar Motoru)'nun güvenle kullanabileceği,
doğrulanmış bir `VlmResult` struct'ına çeviren "savunma katmanı"dır. Akış:

```
MOD-02 (YOLO + ROI) ──► MOD-03 (VLM gate + parse) ──► MOD-04 (Decision) ──► Aktüatör
```

**YOLO bypass gate** (Pi 4 optimizasyonu): MOD-02 YOLO sınıflandırması ≥ %75 güvenliyse
VLM hiç çağrılmaz, sonuç YOLO çıktısından sentezlenir. Pi 4'te ~30 sn → 0 sn kazanç.

---

## Dosya Yapısı

```
src/vlm/
├── vlm_types.py      # mod3.h enum/struct karşılıkları + YOLO bypass sabitleri
├── vlm_parser.py     # JSON parse + validation + error handling (6 katmanlı defense)
├── vlm_errors.py     # Status code → string converter'lar
├── vlm_engine.py     # MoondreamV2 inference + YOLO bypass gate + entegrasyon
├── mock_vlm.py       # Test mock'u (20+ senaryo, deterministic)
├── smoke_test.py     # Moondream + parser uçtan uca doğrulama
├── benchmark.py      # YOLO bypass kazanç simülasyonu
├── demo.py           # İnteraktif mission demosu
├── requirements.txt
├── tests/
│   ├── test_parser.py    # 50+ parser/validation/regression testi
│   ├── test_engine.py    # 30+ gate/synthesis/integration testi
│   └── fixtures/         # örnek ham VLM çıktıları
└── README.md
```

---

## Kurulum (Laptop / Pi 4)

### Bağımlılıklar

```bash
python -m venv .venv
# Windows
.venv\Scripts\Activate.ps1
# Linux/Pi
source .venv/bin/activate

pip install -r requirements.txt
```

**Python sürümü:** 3.10 veya 3.11 önerilir. Moondream paketi şu an Python 3.14
için wheel yayınlamadı; 3.14 üzerinde sadece parser/test/mock çalışır,
gerçek inference yapılamaz.

### Model Dosyası (sadece gerçek inference için)

```
https://huggingface.co/vikhyatk/moondream2/tree/main
→ moondream-2b-int4.mf  (~1 GB, Pi 4 için ideal)
```

Pi 4'te `~/models/moondream-2b-int4.mf` altına koy.

---

## Hızlı Başlangıç

### 1) Tüm testleri koş

```bash
cd src/vlm
pytest tests/ -v
```

Beklenen: **87+ test, hepsi yeşil, ~0.3 sn**.

### 2) Tarla mission demosu (mock VLM ile)

```bash
python demo.py --plants 20
```

Çıktı: her bitki için YOLO sınıfı, güveni, sonuç ve VLM çağrılıp çağrılmadığı.

### 3) Pi 4 kazanç benchmarkı

```bash
python benchmark.py --plants 100 --vlm-ms 30000 --high-conf-ratio 0.80
```

Tipik çıktı: **5x speedup, 50 dk → 10 dk** (saha senaryosu).

### 4) Gerçek modelle smoke test

```bash
python smoke_test.py /path/to/moondream-2b-int4.mf /path/to/plant.jpg
```

### 5) Tek görüntü üzerinde uçtan uca pipeline

```bash
python vlm_engine.py <model_path> <image_path>
```

---

## YOLO Bypass Gate Mimarisi

```
vlm_analyze_plant(image: VlmImage)
        │
        ├── _validate_image() ── ERR_INVALID_INPUT
        │
        ├── _yolo_confident_enough(image)? ── YES ──► _synthesize_from_yolo()
        │                                                  └── VlmResult (inference_time_ms=0)
        │                                                      diagnosis="yolo_bypass: ..."
        │
        └── NO ──► run_moondream_inference() ──► parse_vlm_output() ──► VlmResult
```

**Eşik:** `YOLO_VLM_TRIGGER_THRESHOLD = 0.75` (vlm_types.py'da sabit).
**Aksiyon haritası** (bypass yolu):

| YOLO sınıfı | plant_status | action | severity |
|-------------|--------------|--------|----------|
| HEALTHY (0) | HEALTHY      | SPRAY  | NONE     |
| DISEASED (1)| DISEASED     | SPRAY  | MEDIUM   |
| WEED (2)    | WEED         | LASER  | MEDIUM   |
| UNKNOWN(-1) | UNKNOWN      | SKIP   | NONE     |

**MOD-04 etkisi:** Sıfır. `vlm_analyze_plant` her zaman dolu `VlmResult` döner —
gate'in içeride çalışıp çalışmadığını MOD-04 ayırt edemez (diagnosis prefix'i
"yolo_bypass:" hariç).

---

## MOD-02 Tarafında Gereken Tek Değişiklik

YOLO bypass'ın aktif çalışması için MOD-02'nin `VlmImage`'ı doldururken
2 yeni alanı set etmesi gerekir:

```python
vlm_image = VlmImage(
    data            = roi_bytes,
    width           = 378,
    height          = 378,
    stride          = 378 * 3,
    timestamp_ms    = frame.timestamp_ms,
    yolo_class_id   = best_bbox.class_id,    # YENİ — 0/1/2 (healthy/diseased/weed)
    yolo_confidence = best_bbox.confidence,  # YENİ — [0.0, 1.0]
)
```

Doldurmazsa defaults (`-1`, `0.0`) → gate hiç tetiklenmez → eski davranış.
**Geriye dönük tam uyumlu.**

---

## API Kontratı (MOD-04 için)

```python
status, result = vlm_analyze_plant(image)

# Garantiler:
# - result HER ZAMAN VlmResult instance'ı, asla None
# - result.confidence HER ZAMAN [0.0, 1.0]
# - result.status HER ZAMAN 4 enum'dan biri
# - result.action HER ZAMAN 3 enum'dan biri
# - result.diagnosis HER ZAMAN <= 255 karakter str
# - Asla exception fırlatmaz
```

---

## Pi 4 Notları

| Konu                  | Değer                           |
|-----------------------|---------------------------------|
| `VLM_TIMEOUT_MS`      | 75_000 ms (Pi 4 + termal headroom) |
| Inference süresi      | 20-45 sn (cold start: 30+ sn)   |
| Termal eşik           | 60_000 ms üzeri → throttle warn |
| Model RAM             | ~1.7 GB (8 GB Pi 4 rahat sığar) |
| Swap                  | `sudo swapoff -a` (mutlaka)     |

---

## Test Stratejisi

| Test kategorisi              | Dosya              | Sayı |
|------------------------------|--------------------|------|
| Parser validation/fallback   | test_parser.py     | ~30  |
| Result struct garantileri    | test_parser.py     | 5    |
| Mock senaryo crash-free      | test_parser.py     | 20   |
| YOLO bypass gate             | test_engine.py     | 17   |
| YOLO synthesis               | test_engine.py     | 7    |
| Engine integration           | test_engine.py     | 7    |
| **Toplam**                   |                    | **87+** |

```bash
pytest tests/ --cov=. --cov-report=term-missing
```

Hedef coverage: parser %85+, types %100, gate %100.

---

## Yapılacaklar (Pi 4 Eldeyken)

- [ ] `pip install moondream pillow` (Pi 4'te 3.11 ile)
- [ ] Model dosyasını Pi'a SCP ile kopyala
- [ ] `sudo swapoff -a`
- [ ] `python smoke_test.py <model> <plant.jpg>` çalıştır
- [ ] 5 ardışık inference crash-free mı? (warm-up + termal)
- [ ] Gerçek timing'lerle benchmark'ı koş, README'ye not düş
- [ ] MOD-02 ekibiyle YOLO `class_id` eşleme tablosunu yazıya geçir
- [ ] mod3.h'deki `VLM_TIMEOUT_MS = 30000` → `75000` (Pi 4'e uyumlu yap)
