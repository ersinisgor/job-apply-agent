# ApplyJobsAgent — Kullanım Kılavuzu

Uygulama 7/24 kendi kendine çalışmaz. Drive'daki tabloyu **yalnızca sen terminalden
başlattığın sürece** izler. Aşağıdaki iki kullanım şeklinden birini seç.

> Her komuttan önce proje klasörüne girmen gerekir:
> ```bash
> cd /Users/mac/code/ersinisgor/ApplyJobsAgent
> ```

---

## Seçenek A — Sürekli izleme ("başlat ve unut")

Terminal açık kaldığı sürece her 60 saniyede bir tabloyu kontrol eder; yeni ilan
girdikçe ~1 dakika içinde otomatik işler (CV No + Match Rate + Google Doc).

```bash
cd /Users/mac/code/ersinisgor/ApplyJobsAgent
./.venv/bin/python -m src.applyjobs.main
```

- **Durdurmak için:** terminalde `Ctrl + C`
- ⚠️ Terminali kapatırsan, bilgisayarı kapatırsan veya **uyku moduna** geçerse izleme durur.
  Çalışması için pencere açık ve bilgisayar uyanık olmalı.

---

## Seçenek B — Tek seferlik (toplu)

Birkaç ilanı tabloya ekledikten sonra **bir kez** çalıştır; bekleyen tüm satırları
işleyip kapanır.

```bash
cd /Users/mac/code/ersinisgor/ApplyJobsAgent
./.venv/bin/python scripts/run_once.py
```

İşlemeden önce sadece hangi satırların işleneceğini görmek istersen (hiçbir şey yazmaz):

```bash
cd /Users/mac/code/ersinisgor/ApplyJobsAgent
./.venv/bin/python scripts/run_once.py --dry-run
```

Sadece tek bir satırı denemek istersen (örnek: 250. satır):

```bash
./.venv/bin/python scripts/run_once.py --row 250
```

---

## ⚠️ ÖNEMLİ: Yeni ilan girerken veri kaybını önleme

Uygulama, tabloyu güncellerken **tüm `.xlsx` dosyasını indirip geri yükler.** Sen aynı anda
tabloyu tarayıcıda düzenliyorsan, senin yazdıkların Drive'a gecikmeli kaydedildiği için
çakışma olur ve uygulamanın yüklediği sürüm senin son girdiğin hücreleri (B/C/F/G/H gibi)
silebilir. (Uygulama bu sütunlara asla yazmaz; sorun eşzamanlı düzenlemeden kaynaklanır.)

**Kural — yeni bir ilan satırı eklerken:**
1. Satırın **tüm** bilgilerini gir (Başvuru, Easy Apply, Yer, Uzaktan, Çalışma Şekli, İlan Linki...).
2. **~15-20 saniye bekle** (Google'ın kaydetmesi için) veya tablo sekmesini kapat.
3. Sonra uygulamanın işlemesine bırak.
4. Uygulama o satırı işlerken (~1.5 dk) **o satırı tarayıcıda düzenleme.**

> Not: Uygulama artık tabloya **yalnızca CV üretildikten sonra, tek seferde** yazıyor (CV No + Match Rate
> birlikte). Bu, senin girişlerine ~1.5 dk senkronizasyon süresi tanır ve çakışma riskini azaltır — ama
> yukarıdaki kurala uymak yine de en güvenlisidir.
>
> En kesin yöntem: ilanları gir, tabloyu kapat, sonra **Seçenek B** (tek seferlik) ile çalıştır.

## Hangi satırlar işlenir?

İlan linki (K) dolu **ve** CV No (N) boş olan satırlar.
B sütunu (Başvuru) şu değerlerdeyse **atlanır:** `Geçmiş`, `Vazgeçildi`, `Başvurulmuş`, `✓`.
Yani `+`, `++` veya boş olanlar işlenir.

## Üretilen dosyalar

| Çıktı | Konum |
|-------|-------|
| `cv_<no>.md` | Masaüstü/İş Arama/Job Applications/2026/CVs |
| `cv_<no>.docx` | aynı CVs klasörü (yerel kopya) |
| `cv_<no>` (Google Doc) | Drive → Resumes based on Jobs |
| `cv_<no>_analysis.md` | .../2026/CV_Analysis |
| `job_description_<no>.md` | .../2026/Job Description |
| CV No → N sütunu, Match Rate → P sütunu | Drive'daki tablo |

---

## Huntr entegrasyonu (opsiyonel)

Açıkken, Huntr board'una kaydettiğin yeni ilanın **linkini** sheet'e (K) yazar. Sonra uygulama o
linke gidip ilan sayfasından **Firma (J, tıklanabilir), Pozisyon (L), Yer (F), Çalışma Şekli (H)**
sütunlarını doldurur (sadece boş hücreleri) ve CV üretir.
- **G (Uzaktan)** otomatik doldurulmaz → elle girersin (LinkedIn bu bilgiyi otomasyona vermiyor).
- **C (Easy Apply)** LinkedIn ilanlarında boş kalır (elle), LinkedIn dışı linklerde "Yok".

**Açma:** `.env`'de `HUNTR_BOARD_URL=<board adresin>` ayarla. **Kapatma:** o satırı boş bırak/sil
→ uygulama Huntr'sız eski hâline döner (kod değişmez).

**İlk kurulum (tek seferlik):**
```bash
./.venv/bin/python scripts/huntr_login.py     # tarayıcıda Huntr'a giriş yap, ENTER
```
- İlk çalıştırmada mevcut Huntr ilanların "görüldü" işaretlenir (içeri alınmaz); sadece bundan
  sonra kaydettiklerin sheet'e eklenir.
- Manuel test: `./.venv/bin/python scripts/run_once.py --huntr`
- Çekme sorun çıkarırsa: `./.venv/bin/python scripts/huntr_debug.py` → `huntr_debug/` klasörünü paylaş.

**Geri dönüş cümleleri (bana söyleyeceklerin):**
- **"Huntr'ı kapat"** → geçici/anında durdur (`.env`'den `HUNTR_BOARD_URL` kaldırılır).
- **"Huntr entegrasyonunu tamamen geri al"** → kod Huntr öncesine döndürülür (git restore point).

## Kimlik bilgileri (tekrar gerekir mi?)

- **Anthropic / Google OAuth / Service Account:** kalıcı, tekrar giriş gerekmez.
- **LinkedIn çerezleri:** zamanla dolabilir. İlan açıklamaları çekilemezse (loglarda
  LinkedIn hatası) bir kez daha çalıştır:
  ```bash
  ./.venv/bin/python scripts/linkedin_login.py
  ```

---

## Sık karşılaşılan durumlar

- **"command not found: python" benzeri hata:** `python` yerine her zaman `./.venv/bin/python`
  yaz (projeye özel Python budur).
- **Yanlış klasördeyim:** her komuttan önce `cd /Users/mac/code/ersinisgor/ApplyJobsAgent`.
- **Bir ilan atlandı:** ilan yayından kalkmış olabilir; o satır işlenmez, diğerleri devam eder.
  İlgili satırın CV No (N) hücresini silip tekrar çalıştırırsan yeniden denenir.
