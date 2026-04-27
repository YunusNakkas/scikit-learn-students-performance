"""
EduAI analiz API'si: Gemini ile JSON tavsiye üretir; isteğe bağlı ML bağlamı ekler.
Çalıştırma (proje kökünden): uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
Tarayıcı: http://127.0.0.1:8000/ (Live Server yerine; CSV yazılınca sayfa yenilenmez)
Ayarlar: proje kökünde local.env veya gemini_api_key.txt (TextEdit: Biçim → Düz Metin yapın, .rtf kullanmayın)
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Optional
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .auth import get_current_user, router as auth_router
from .database import SessionLocal, init_db
from .logger import logger
from .ml_context import ensure_sklearn_model, ml_context_paragraph
from .models import Analysis, Goal
from .submission_csv import append_analyze_submission

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_DIR = Path(__file__).resolve().parent
# Gizli anahtarlar (TextEdit bazen local.env.rtf kaydeder — o çalışmaz, düz metin gerekir)
# override=True: terminalde boş GEMINI_API_KEY export edilmişse dosyadaki değer yine de okunur
for _p in (
    PROJECT_ROOT / "local.env",
    PROJECT_ROOT / "local.env.txt",
    _BACKEND_DIR / "local.env",
    _BACKEND_DIR / "local.env.txt",
):
    load_dotenv(_p, override=True)


def _load_gemini_key_from_plain_file() -> None:
    """GEMINI_API_KEY yoksa: tek satırlık düz metin dosyası (TextEdit ile kolay)."""
    if (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip():
        return
    key_path = PROJECT_ROOT / "gemini_api_key.txt"
    if not key_path.is_file():
        return
    try:
        raw = key_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    for line in raw.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            os.environ["GEMINI_API_KEY"] = line
            return


_load_gemini_key_from_plain_file()


class NotlarIn(BaseModel):
    mat: list[float] = Field(..., min_length=3, max_length=3)
    fiz: list[float] = Field(..., min_length=3, max_length=3)
    kim: list[float] = Field(..., min_length=3, max_length=3)


class RutinlerIn(BaseModel):
    uyku: float = Field(..., ge=0, le=24)
    calisma: float = Field(..., ge=0, le=24)


class AnalyzeRequest(BaseModel):
    notlar: NotlarIn
    rutinler: RutinlerIn


def _avg(three: list[float]) -> int:
    return int(round(sum(three) / 3))


def _build_prompt(
    notlar: NotlarIn,
    rutinler: RutinlerIn,
    ortalamalar: dict[str, int],
    ml_extra: str | None,
) -> str:
    n = notlar
    r = rutinler
    o = ortalamalar
    extra = f"\nEk bağlam: {ml_extra}\n" if ml_extra else ""
    return f"""
            Sen uzman ve analitik bir eğitim koçusun. Öğrencinin notları:
            Matematik: 1.Sınav: {n.mat[0]}, 2.Sınav: {n.mat[1]}, Sözlü: {n.mat[2]} (Ort: {o["mat"]})
            Fizik: 1.Sınav: {n.fiz[0]}, 2.Sınav: {n.fiz[1]}, Sözlü: {n.fiz[2]} (Ort: {o["fiz"]})
            Kimya: 1.Sınav: {n.kim[0]}, 2.Sınav: {n.kim[1]}, Sözlü: {n.kim[2]} (Ort: {o["kim"]})

            Öğrencinin günlük rutinleri:
            Uyku: {r.uyku} saat
            Ders Çalışma: {r.calisma} saat
            {extra}
            Öğrenciye her ders için ve genel rutini için çok detaylı, uygulanabilir ve kapsamlı tavsiyeler ver. Sadece "daha çok çalış" gibi basit cümleler KULLANMA. Nasıl bir çalışma stratejisi izlemeli, uyku ve çalışma saati dengesini nasıl sağlamalı detaylandır.

            Aşağıdaki JSON formatında, her ders için ve rutin için en az 3 adet ve her biri 2-3 cümleden oluşan UZUN VE DETAYLI tavsiyeler döndür. Ekstra metin yazma, sadece JSON formatı döndür. DİKKAT: JSON içinde "..." (üç nokta) gibi kısaltmalar kullanma, JSON tamamen hatasız olmalı:
            {{
                "matematikDurum": "Kısa özet",
                "matematikTrend": "Örn: +13 ↑",
                "matematikTavsiyeler": ["Gerçek tavsiye 1", "Gerçek tavsiye 2", "Gerçek tavsiye 3"],
                "fizikDurum": "Kısa özet",
                "fizikTrend": "Örn: -4 ↓",
                "fizikTavsiyeler": ["Gerçek tavsiye 1", "Gerçek tavsiye 2", "Gerçek tavsiye 3"],
                "kimyaDurum": "Kısa özet",
                "kimyaTrend": "Örn: +4 ↑",
                "kimyaTavsiyeler": ["Gerçek tavsiye 1", "Gerçek tavsiye 2", "Gerçek tavsiye 3"],
                "uykuDurum": "Kısa özet",
                "uykuTavsiyeler": ["Uyku ile ilgili gerçek tavsiye 1", "Tavsiye 2"],
                "calismaDurum": "Kısa özet",
                "calismaTavsiyeler": ["Ders çalışma süresi ile ilgili gerçek tavsiye 1", "Tavsiye 2"]
            }}"""


def _build_learning_path_prompt(
    ortalamalar: dict[str, int],
    rutinler: RutinlerIn,
    ml_extra: str | None,
) -> str:
    extra = f"\nEk bağlam: {ml_extra}\n" if ml_extra else ""
    return f"""
            Sen uzman bir eğitim koçusun. Aşağıdaki öğrenci profili için 4 haftalık kişiselleştirilmiş öğrenme yolu hazırla.

            Ders ortalamaları:
            Matematik: {ortalamalar["mat"]}/100
            Fizik: {ortalamalar["fiz"]}/100
            Kimya: {ortalamalar["kim"]}/100

            Günlük rutin:
            Uyku: {rutinler.uyku} saat
            Ders Çalışma: {rutinler.calisma} saat
            {extra}
            ÖNEMLİ KURALLAR:
            - Zayıf derslere daha fazla saat ayır, güçlü dersleri korumaya yönelik plan yap.
            - Her hafta 3 ders için ayrı görev listesi oluştur (haftada 5-7 görev gibi).
            - Görevler somut olsun: "Türev konu tekrarı + 20 soru çöz" gibi. "Çalış" yetmez.
            - Haftalık toplam çalışma saatini öğrencinin günlük çalışma saatine uygun hesapla.
            - Her hafta için ayrıca kısa bir motivasyon notu ekle.

            Sadece şu JSON formatını döndür, başka metin yazma. JSON içinde "..." kullanma:
            {{
                "ozet": "Genel strateji 2-3 cümle",
                "haftalikToplamSaat": 21,
                "haftalar": [
                    {{
                        "hafta": 1,
                        "odak": "Bu hafta hangi derse ağırlık verilecek",
                        "gorevler": {{
                            "matematik": ["Görev 1", "Görev 2", "Görev 3"],
                            "fizik": ["Görev 1", "Görev 2"],
                            "kimya": ["Görev 1", "Görev 2"]
                        }},
                        "motivasyon": "Kısa motivasyon notu"
                    }},
                    {{
                        "hafta": 2,
                        "odak": "...",
                        "gorevler": {{ "matematik": [...], "fizik": [...], "kimya": [...] }},
                        "motivasyon": "..."
                    }},
                    {{
                        "hafta": 3,
                        "odak": "...",
                        "gorevler": {{ "matematik": [...], "fizik": [...], "kimya": [...] }},
                        "motivasyon": "..."
                    }},
                    {{
                        "hafta": 4,
                        "odak": "...",
                        "gorevler": {{ "matematik": [...], "fizik": [...], "kimya": [...] }},
                        "motivasyon": "..."
                    }}
                ]
            }}"""


def _gemini_generate(model, prompt: str, max_retries: int = 3) -> str:
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            return _gemini_text_raw(response)
        except Exception as e:
            msg = str(e)
            if "429" in msg:
                import re as _re
                m = _re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", msg)
                wait = int(m.group(1)) if m else 15
                wait = min(wait, 60)
                if attempt < max_retries - 1:
                    time.sleep(wait + 2)
                    continue
            raise
    raise RuntimeError("Gemini yanıt vermedi")


def _gemini_text_raw(response) -> str:
    try:
        return response.text or ""
    except ValueError:
        cands = getattr(response, "candidates", None) or []
        if not cands:
            return ""
        parts = getattr(cands[0].content, "parts", None) or []
        return "".join(getattr(p, "text", "") or "" for p in parts)


def _parse_ai_json(text: str) -> dict:
    t = text.replace("```json", "").replace("```JSON", "").replace("```", "").strip()
    t = re.sub(r",\s*([}\]])", r"\1", t)
    return json.loads(t)


def _pick_model_name() -> str:
    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        raise HTTPException(
            status_code=500,
            detail=(
                "GEMINI_API_KEY yüklenemedi. Proje köküne (index.html'in yanına) şunlardan birini koyun: "
                "(1) Düz metin local.env, içinde GEMINI_API_KEY=anahtar — TextEdit'te Biçim→Düz Metin; .rtf olmamalı. "
                "(2) Veya düz metin gemini_api_key.txt, tek satırda sadece anahtar."
            ),
        )
    genai.configure(api_key=key)
    return "models/gemini-2.5-flash"


_allowed_origins = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
    if o.strip()
]

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="EduAI Backend", version="1.0.0")
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
init_db()
app.include_router(auth_router)

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    logger.warning(f"Rate limit aşıldı: {request.client.host} → {request.url.path}")
    return JSONResponse(status_code=429, content={"detail": "Çok fazla istek gönderildi. Lütfen bekleyin."})

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and not request.url.path.startswith("/api") and not request.url.path.startswith("/auth"):
        return FileResponse(PROJECT_ROOT / "404.html", status_code=404)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    logger.error(f"Beklenmeyen hata: {request.url.path} → {exc!r}")
    return JSONResponse(status_code=500, content={"detail": "Sunucu hatası oluştu. Lütfen tekrar deneyin."})
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = round((time.time() - start) * 1000)
    logger.info(f"{request.method} {request.url.path} → {response.status_code} ({duration}ms) [{request.client.host}]")
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    key_ok = bool((os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip())
    return {"ok": True, "gemini_key_loaded": key_ok}


@app.post("/api/analyze")
@limiter.limit("10/minute")
def analyze(request: Request, body: AnalyzeRequest, current_user=Depends(get_current_user)):
    for ders, vals in (
        ("mat", body.notlar.mat),
        ("fiz", body.notlar.fiz),
        ("kim", body.notlar.kim),
    ):
        for v in vals:
            if v < 0 or v > 100:
                raise HTTPException(status_code=400, detail=f"{ders} notları 0–100 aralığında olmalı")

    ortalamalar = {
        "mat": _avg(body.notlar.mat),
        "fiz": _avg(body.notlar.fiz),
        "kim": _avg(body.notlar.kim),
    }
    try:
        ensure_sklearn_model(PROJECT_ROOT)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Scikit-learn modeli hazırlanamadı: {e!s}",
        ) from e

    ml_extra, sk_meta = ml_context_paragraph(
        PROJECT_ROOT,
        ortalamalar["mat"],
        ortalamalar["fiz"],
        ortalamalar["kim"],
        body.rutinler.calisma,
        body.rutinler.uyku,
    )
    if not ml_extra:
        raise HTTPException(
            status_code=500,
            detail="Scikit-learn modeli yüklendi ancak tahmin üretilemedi.",
        )
    prompt = _build_prompt(body.notlar, body.rutinler, ortalamalar, ml_extra)

    model_name = _pick_model_name()
    model = genai.GenerativeModel(model_name)
    try:
        raw = _gemini_generate(model, prompt)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini hatası: {e!s}") from e

    if not raw:
        raise HTTPException(status_code=502, detail="Gemini boş yanıt döndü")

    try:
        ai = _parse_ai_json(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=502,
            detail="Model yanıtı JSON olarak çözülemedi; tekrar deneyin.",
        ) from e

    submission_logged = append_analyze_submission(
        PROJECT_ROOT,
        ortalamalar,
        body.rutinler.calisma,
        body.rutinler.uyku,
    )

    genel_ort = (ortalamalar["mat"] + ortalamalar["fiz"] + ortalamalar["kim"]) // 3
    try:
        db = SessionLocal()
        db.add(Analysis(
            user_id=current_user.id,
            mat_avg=ortalamalar["mat"],
            fiz_avg=ortalamalar["fiz"],
            kim_avg=ortalamalar["kim"],
            genel_ort=genel_ort,
            uyku=body.rutinler.uyku,
            calisma=body.rutinler.calisma,
            ai_json=json.dumps(ai, ensure_ascii=False),
        ))
        db.commit()
        db.close()
    except Exception:
        pass

    return {
        "ai": ai,
        "ortalamalar": ortalamalar,
        "model": model_name,
        "sklearn": sk_meta,
        "submission_logged": submission_logged,
    }


@app.get("/api/analytics")
def analytics(current_user=Depends(get_current_user)):
    db = SessionLocal()
    rows = (
        db.query(Analysis)
        .filter(Analysis.user_id == current_user.id)
        .order_by(Analysis.created_at.asc())
        .all()
    )
    db.close()
    return {
        "analyses": [
            {
                "id": r.id,
                "mat": r.mat_avg,
                "fiz": r.fiz_avg,
                "kim": r.kim_avg,
                "genel": r.genel_ort,
                "uyku": r.uyku,
                "calisma": r.calisma,
                "tarih": r.created_at.strftime("%d.%m.%Y %H:%M") if r.created_at else "",
                "ai": json.loads(r.ai_json) if r.ai_json else None,
            }
            for r in rows
        ]
    }


class GoalIn(BaseModel):
    baslik: str
    aciklama: str = ""

class GoalPatch(BaseModel):
    tamamlandi: Optional[int] = None
    baslik: Optional[str] = None
    aciklama: Optional[str] = None

@app.get("/api/goals")
def get_goals(current_user=Depends(get_current_user)):
    db = SessionLocal()
    rows = db.query(Goal).filter(Goal.user_id == current_user.id).order_by(Goal.created_at.desc()).all()
    db.close()
    return {"goals": [{"id": r.id, "baslik": r.baslik, "aciklama": r.aciklama, "tamamlandi": r.tamamlandi, "tarih": r.created_at.strftime("%d.%m.%Y") if r.created_at else ""} for r in rows]}

@app.post("/api/goals", status_code=201)
def create_goal(body: GoalIn, current_user=Depends(get_current_user)):
    if not body.baslik.strip():
        raise HTTPException(status_code=400, detail="Başlık boş olamaz")
    db = SessionLocal()
    goal = Goal(user_id=current_user.id, baslik=body.baslik.strip(), aciklama=body.aciklama.strip())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    result = {"id": goal.id, "baslik": goal.baslik, "aciklama": goal.aciklama, "tamamlandi": goal.tamamlandi, "tarih": goal.created_at.strftime("%d.%m.%Y") if goal.created_at else ""}
    db.close()
    return result

@app.patch("/api/goals/{goal_id}")
def update_goal(goal_id: int, body: GoalPatch, current_user=Depends(get_current_user)):
    db = SessionLocal()
    goal = db.query(Goal).filter(Goal.id == goal_id, Goal.user_id == current_user.id).first()
    if not goal:
        db.close()
        raise HTTPException(status_code=404, detail="Hedef bulunamadı")
    if body.tamamlandi is not None:
        goal.tamamlandi = body.tamamlandi
    if body.baslik is not None:
        goal.baslik = body.baslik.strip()
    if body.aciklama is not None:
        goal.aciklama = body.aciklama.strip()
    db.commit()
    db.close()
    return {"ok": True}

@app.delete("/api/goals/{goal_id}")
def delete_goal(goal_id: int, current_user=Depends(get_current_user)):
    db = SessionLocal()
    goal = db.query(Goal).filter(Goal.id == goal_id, Goal.user_id == current_user.id).first()
    if not goal:
        db.close()
        raise HTTPException(status_code=404, detail="Hedef bulunamadı")
    db.delete(goal)
    db.commit()
    db.close()
    return {"ok": True}


@app.post("/api/learning-path")
def learning_path(body: AnalyzeRequest, current_user=Depends(get_current_user)):
    for ders, vals in (
        ("mat", body.notlar.mat),
        ("fiz", body.notlar.fiz),
        ("kim", body.notlar.kim),
    ):
        for v in vals:
            if v < 0 or v > 100:
                raise HTTPException(status_code=400, detail=f"{ders} notları 0–100 aralığında olmalı")

    ortalamalar = {
        "mat": _avg(body.notlar.mat),
        "fiz": _avg(body.notlar.fiz),
        "kim": _avg(body.notlar.kim),
    }
    try:
        ensure_sklearn_model(PROJECT_ROOT)
    except Exception:
        pass

    ml_extra, _ = ml_context_paragraph(
        PROJECT_ROOT,
        ortalamalar["mat"],
        ortalamalar["fiz"],
        ortalamalar["kim"],
        body.rutinler.calisma,
        body.rutinler.uyku,
    )

    prompt = _build_learning_path_prompt(ortalamalar, body.rutinler, ml_extra)
    model_name = _pick_model_name()
    model = genai.GenerativeModel(model_name)
    try:
        raw = _gemini_generate(model, prompt)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini hatası: {e!s}") from e

    if not raw:
        raise HTTPException(status_code=502, detail="Gemini boş yanıt döndü")

    try:
        plan = _parse_ai_json(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=502,
            detail="Öğrenme yolu JSON olarak çözülemedi; tekrar deneyin.",
        ) from e

    return {"plan": plan, "ortalamalar": ortalamalar, "user": current_user.email}


# Arayüzü buradan aç: CSV güncellenince Live Server sayfayı yenilemez (http://127.0.0.1:8000/)
@app.get("/")
def serve_index():
    return FileResponse(PROJECT_ROOT / "index.html")


@app.get("/login")
def serve_login():
    return FileResponse(PROJECT_ROOT / "login.html")

@app.get("/reset")
def serve_reset():
    return FileResponse(PROJECT_ROOT / "reset.html")

@app.get("/style.css")
def serve_css():
    return FileResponse(PROJECT_ROOT / "style.css")


app.mount("/js", StaticFiles(directory=str(PROJECT_ROOT / "js")), name="js")
