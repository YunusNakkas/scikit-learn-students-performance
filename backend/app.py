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
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ml_context import ensure_sklearn_model, ml_context_paragraph
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


def _gemini_text(response) -> str:
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


_cached_gemini_model: str | None = None


def _pick_model_name() -> str:
    global _cached_gemini_model
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
    if _cached_gemini_model:
        return _cached_gemini_model
    for m in genai.list_models():
        methods = getattr(m, "supported_generation_methods", None) or []
        name = (m.name or "").lower()
        if "generatecontent" in [x.lower() for x in methods] and "gemini" in name:
            _cached_gemini_model = m.name
            return m.name
    raise HTTPException(status_code=503, detail="Uygun Gemini modeli bulunamadı")


app = FastAPI(title="EduAI Backend", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    key_ok = bool((os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip())
    return {"ok": True, "gemini_key_loaded": key_ok}


@app.post("/api/analyze")
def analyze(body: AnalyzeRequest):
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
        response = model.generate_content(prompt)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini hatası: {e!s}") from e

    raw = _gemini_text(response).strip()
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

    return {
        "ai": ai,
        "ortalamalar": ortalamalar,
        "model": model_name,
        "sklearn": sk_meta,
        "submission_logged": submission_logged,
    }


# Arayüzü buradan aç: CSV güncellenince Live Server sayfayı yenilemez (http://127.0.0.1:8000/)
@app.get("/")
def serve_index():
    return FileResponse(PROJECT_ROOT / "index.html")


@app.get("/style.css")
def serve_css():
    return FileResponse(PROJECT_ROOT / "style.css")


app.mount("/js", StaticFiles(directory=str(PROJECT_ROOT / "js")), name="js")
