# EduAI — Uyarlanabilir Öğrenme Platformu

Öğrenci performansını yapay zeka ile analiz eden, kişiselleştirilmiş öğrenme tavsiyeleri ve 4 haftalık öğrenme yolu üreten bir web uygulaması.

---

## Özellikler

- **Performans Analizi** — Matematik, Fizik, Kimya notları ve günlük rutin (uyku/çalışma saati) girilir; scikit-learn Random Forest modeli z-skor profili çıkarır, Google Gemini ile detaylı tavsiyeler üretilir
- **Kişiselleştirilmiş Öğrenme Yolu** — Öğrenci profiline göre 4 haftalık, ders bazlı görev planı
- **Öğrenme Analitiği** — Chart.js ile zaman içindeki not trendleri, ilk analizden bu yana değişim
- **Geçmiş Analizler** — Tüm analizler ve Gemini tavsiyeleri veritabanında saklanır, geçmişe dönük incelenebilir
- **Hedef Yönetimi** — Kişisel öğrenme hedefleri eklenip tamamlanabilir
- **Kullanıcı Yönetimi** — Kayıt, giriş, profil düzenleme, şifre değiştirme, şifre sıfırlama
- **PDF İndirme** — Analiz raporu tek tıkla PDF'e aktarılır
- **Mobil Uyumluluk** — Tüm ekran boyutlarında çalışır

---

## Teknoloji Yığını

| Katman | Teknoloji |
|--------|-----------|
| Backend | FastAPI, Python |
| Veritabanı | PostgreSQL (Neon) + SQLAlchemy ORM + Alembic |
| Kimlik Doğrulama | JWT (python-jose) + bcrypt (passlib) |
| Makine Öğrenmesi | scikit-learn (Random Forest, StandardScaler) |
| Yapay Zeka | Google Gemini API (gemini-2.5-flash) |
| Frontend | Vanilla JS SPA, Chart.js, html2pdf.js |
| Güvenlik | Rate limiting (slowapi), CORS, rotating logger |

---

## Kurulum

### 1. Depoyu klonla

```bash
git clone <repo-url>
cd "scikit-learn kopyası"
```

### 2. Bağımlılıkları yükle

```bash
pip install -r backend/requirements.txt
```

### 3. Ortam değişkenlerini ayarla

Proje kökünde `local.env` dosyası oluştur:

```env
GEMINI_API_KEY=your_gemini_api_key
JWT_SECRET_KEY=gizli-bir-anahtar-belirle
ALLOWED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
DATABASE_URL=postgresql://kullanici:sifre@host/dbadi?sslmode=require
```

> **Gemini API anahtarı:** [Google AI Studio](https://aistudio.google.com/) → "Get API key"
>
> **PostgreSQL:** [Neon.tech](https://neon.tech) ücretsiz plan yeterlidir. `DATABASE_URL` olmadan uygulama yerel SQLite'a düşer.

### 4. Veritabanı tablolarını oluştur

```bash
python -m alembic upgrade head
```

---

## Çalıştırma

```bash
# Proje kökünden çalıştır
uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

Tarayıcıda aç: **http://127.0.0.1:8000**

> `index.html`'i doğrudan tarayıcıda açma — CSV yazılımı ve API çağrıları çalışmaz.

---

## Proje Yapısı

```
├── backend/
│   ├── app.py              # FastAPI ana uygulama, tüm API endpoint'leri
│   ├── auth.py             # JWT kimlik doğrulama, kayıt/giriş/şifre sıfırlama
│   ├── models.py           # SQLAlchemy modelleri (User, Goal, Analysis, PasswordResetToken)
│   ├── database.py         # Veritabanı bağlantısı (PostgreSQL/SQLite)
│   ├── ml_context.py       # scikit-learn model eğitimi, yükleme, z-skor analizi
│   ├── submission_csv.py   # Thread-safe CSV ekleme
│   ├── email_utils.py      # SMTP e-posta gönderimi (şifre sıfırlama)
│   ├── logger.py           # Dönen dosya logger (logs/app.log)
│   └── requirements.txt
├── alembic/                # Veritabanı migration dosyaları
├── js/
│   └── app.js              # Frontend SPA mantığı
├── index.html              # Ana uygulama sayfası
├── login.html              # Giriş/kayıt sayfası
├── reset.html              # Şifre sıfırlama sayfası
├── 404.html                # Hata sayfası
├── style.css               # Uygulama stilleri
├── StudentsPerformance_Extended.csv  # Eğitim verisi (her analizle büyür)
├── tavsiye_modeli_v4.joblib          # Eğitilmiş ML modeli
└── local.env               # Gizli anahtarlar (git'e eklenmez)
```

---

## ML Modeli

- **Algoritma:** Random Forest (300 ağaç, dengeli sınıf ağırlıkları) + StandardScaler Pipeline
- **Etiketler:** 3 dersin ortalama puanına göre 5 beşlik dilim (0–4)
- **Tahmin akışı:** `ensure_sklearn_model()` → `ml_context_paragraph()` → z-skor analizi → Gemini prompt'una eklenir
- **Otomatik yeniden eğitim:** `tavsiye_modeli_v4.joblib` silinirse ilk `/api/analyze` çağrısında CSV'den yeniden eğitilir
- **Büyüyen veri:** Her başarılı analiz CSV'ye yeni satır ekler (`test preparation course = "eduai_web"` işaretli)

---

## API Endpoint'leri

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| POST | `/auth/register` | Yeni kullanıcı kaydı |
| POST | `/auth/login` | Giriş, JWT token döner |
| GET | `/auth/me` | Mevcut kullanıcı bilgisi |
| PATCH | `/auth/profile` | Ad/soyad güncelle |
| POST | `/auth/change-password` | Şifre değiştir |
| POST | `/auth/forgot-password` | Şifre sıfırlama bağlantısı gönder |
| POST | `/auth/reset-password` | Yeni şifre belirle |
| POST | `/api/analyze` | Not analizi + Gemini tavsiyesi |
| POST | `/api/learning-path` | 4 haftalık öğrenme yolu |
| GET | `/api/analytics` | Geçmiş analizler + trend |
| GET/POST | `/api/goals` | Hedef listesi / yeni hedef |
| PATCH/DELETE | `/api/goals/{id}` | Hedef güncelle / sil |

---

## Güvenlik

- Şifreler **bcrypt** ile hashlenir, düz metin asla saklanmaz
- JWT token'lar sadece bellekte tutulur, `localStorage`'a yazılmaz
- Auth endpoint'leri **rate limiting** ile korunur (kayıt: 5/dk, giriş: 10/dk)
- CORS sadece izin verilen origin'lere açık
- Tüm istekler zaman damgalı log dosyasına yazılır (`logs/app.log`)
- Veritabanı URL ve gizli anahtarlar `.gitignore`'daki `local.env`'de tutulur

---

## Test

```bash
python model_test_f1.py          # ML modeli çapraz doğrulama F1 raporu
python test_round.py             # Not yuvarlama testleri
python -m pytest backend/test_performance.py  # Backend performans testleri
```
