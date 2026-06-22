# ApplyJobsAgent

Google Sheets'teki iş-başvuru listenizi sürekli izleyen ve yeni bir ilan satırı
girdiğinizde o ilana özel, ATS-optimize **İngilizce CV** üreten bir agent.

Her yeni satır için:

1. **N (CV No)** sütununa sıradaki numarayı yazar.
2. **K (İlan Linki)** sütunundaki linke gider ve ilan açıklamasını okur (Playwright;
   LinkedIn dahil firma kendi siteleri de desteklenir).
3. ATS CV Optimization talimatına göre CV üretir (`config/ats_prompt.md`).
4. CV'yi `cv_<no>.md` olarak `~/Desktop/İş Arama/Job Applications/2026/CVs/` altına kaydeder.

## Tetikleme kuralı

Bir satır şu durumda işlenir: **K (link) dolu**, **N (CV No) boş** ve **B (Başvuru)**
sütunu `Geçmiş` / `Vazgeçildi` / `✓` *değil* (yani `+`, `++` veya boş).

## Kurulum

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 1. Google Service Account
Liste Drive'da bir **Excel (.xlsx)** dosyası olarak tutulur; uygulama dosyayı Drive API ile
indirir, openpyxl ile düzenler ve aynı dosyanın üzerine geri yükler.

1. Google Cloud Console'da bir proje açın ve **Google Drive API**'yi etkinleştirin.
2. Bir **Service Account** oluşturup JSON anahtarı indirin.
3. Anahtarı `credentials/service_account.json` olarak kaydedin.
4. Drive'daki `.xlsx` dosyanızı, service account e-postası ile (`...@...iam.gserviceaccount.com`)
   **Düzenleyen (Editor)** olarak paylaşın.
5. `.env` içindeki `SPREADSHEET_ID`, bu `.xlsx` dosyasının Drive linkindeki id'dir.

> Not: Dosya programatik olarak yeniden yazıldığı için açılır listeler (data validation) ve
> koşullu biçimlendirme korunur; yine de ilk çalıştırmadan önce dosyanın bir yedeğini almanız önerilir.

### 2. Ortam değişkenleri
```bash
cp .env.example .env
# .env içini doldurun: ANTHROPIC_API_KEY, SPREADSHEET_ID, SHEET_NAME, ...
```
`SHEET_NAME` sekme adıdır (Türkçe Google'da genelde `Sayfa1`).

### 3. LinkedIn oturumu (tek seferlik)
```bash
python scripts/linkedin_login.py
```
Açılan tarayıcıda LinkedIn'e giriş yapın, terminalde ENTER'a basın. Oturum
`credentials/linkedin_state.json` dosyasına kaydedilir. Çerezler süresi dolarsa
bu komutu tekrar çalıştırın.

### 4. Google Docs çıktısı için OAuth (tek seferlik)
Agent, her CV'yi `config/cv_template.docx` şablonundan üretip Drive'daki **"Resumes Based on
Jobs"** klasörüne `cv_<no>` adıyla **gerçek bir Google Doc** olarak da kaydeder. Service account
kişisel Drive'da yeni dosya oluşturamadığı için bu adım **OAuth** (kendi hesabınız) ile yapılır.

1. Google Cloud Console → **APIs & Services → OAuth consent screen** → External → kendinizi
   **Test user** ekleyin. (Token'ın 7 günde dolmaması için uygulamayı **Publish / Production**
   durumuna alın; kişisel kullanımda doğrulama gerekmez, "unverified" uyarısını kabul edin.)
2. **Credentials → Create credentials → OAuth client ID → Desktop app** → JSON'u indirin →
   `credentials/oauth_client.json` olarak kaydedin.
3. Drive'da **"Resumes Based on Jobs"** klasörünün var olduğundan emin olun (kendi hesabınız
   olduğu için paylaşım gerekmez).
4. Giriş yapın:
   ```bash
   python scripts/google_login.py
   ```
   Tarayıcıda izin verin → token `credentials/oauth_token.json` dosyasına kaydedilir.

> Bu adımı atlarsanız Markdown CV yine üretilir; sadece Google Doc oluşturma atlanır (loglanır).

## Çalıştırma

Sürekli izleme (polling):
```bash
python -m src.applyjobs.main
```

Tek seferlik tarama (cron/test için):
```bash
python scripts/run_once.py            # aday satırları işler
python scripts/run_once.py --dry-run  # sadece listeler, hiçbir şey yazmaz
```

## Üretilen dosyalar

| Dosya | Konum |
|-------|-------|
| `cv_<no>.md` | `OUTPUT_DIR` (optimize CV, Markdown) |
| `cv_<no>.docx` | `OUTPUT_DIR` (Docs'a yüklenen yerel kopya) |
| `cv_<no>` (Google Doc) | Drive → "Resumes Based on Jobs" |
| `cv_<no>_analysis.md` | `ANALYSIS_DIR` (Türkçe ATS analizi + skor) |
| `job_description_<no>.md` | `JOB_DESCRIPTION_DIR` (çekilen ilan metni) |

## Yapı

```
config/      cv_base.md, projects_list.md, ats_prompt.md, cv_template.docx
credentials/ service_account.json, linkedin_state.json, oauth_client.json, oauth_token.json (gitignored)
src/applyjobs/
  config.py       ayarlar ve yollar
  sheets.py       Sheets oku/yaz (service account)
  scraper.py      Playwright ile ilan açıklaması
  generator.py    Anthropic ile CV üretimi
  docx_builder.py Markdown CV'yi .docx şablonuna doldurur
  drive_docs.py   .docx'i Google Doc'a dönüştürüp Drive'a yükler (OAuth)
  pipeline.py     satır işleme akışı
  main.py         polling döngüsü
scripts/     linkedin_login.py, google_login.py, run_once.py
state/       processed.json, last_cv_no (gitignored)
```

## Notlar
- Varsayılan model `claude-sonnet-4-6` (`.env`'de `CLAUDE_MODEL` ile değiştirilebilir).
- CV girdiniz değişirse `config/cv_base.md` ve `config/projects_list.md` dosyalarını güncelleyin.
