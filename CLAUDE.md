# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**EduAI** — A student performance analysis web app. The user enters math/physics/chemistry scores and daily study/sleep hours; the backend runs a scikit-learn Random Forest model for z-score profiling, then sends enriched context to Google Gemini to generate structured JSON advice. Results are rendered in a browser UI and each submission is appended to the training CSV.

## Running the Backend

```bash
# From project root — always use this form (not cd backend && uvicorn app:app)
uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/` in the browser. Do **not** open `index.html` via VS Code Live Server — the CSV write-back won't work and the page won't update after submissions.

## API Key Setup

The backend auto-discovers the Gemini key from (in order):
1. `local.env` in project root — `GEMINI_API_KEY=your_key`
2. `gemini_api_key.txt` in project root — raw key on one line

Both files must be plain text (not `.rtf`). Use TextEdit → Format → Make Plain Text on macOS.

**Warning:** `students_performance_starter.py` still has a hardcoded API key at line 11 — do not commit it.

## ML Model

- **File:** `tavsiye_modeli_v4.joblib` (project root)
- **Training:** Auto-triggered on first `/api/analyze` call if the `.joblib` is missing, using `StudentsPerformance_Extended.csv`
- **Algorithm:** Random Forest (300 trees, balanced class weights) with `StandardScaler` in a Pipeline; labels = quintile bins (0–4) of the average academic score
- **Prediction flow:** `ensure_sklearn_model()` → `ml_context_paragraph()` → z-score analysis → paragraph injected into Gemini prompt

## Architecture

```
index.html + style.css + js/app.js   ← Browser SPA (vanilla JS)
        ↕  POST /api/analyze (JSON)
backend/app.py                        ← FastAPI; validates input, builds prompt, calls Gemini
backend/ml_context.py                 ← sklearn model train/load + z-score paragraphs
backend/submission_csv.py             ← Thread-safe CSV append of each web submission
StudentsPerformance_Extended.csv      ← Dataset + grows with each submission
tavsiye_modeli_v4.joblib              ← Serialized Pipeline; auto-rebuilt if deleted
```

The FastAPI app also serves `index.html`, `style.css`, and `js/` statically so the whole app runs from one origin (`http://127.0.0.1:8000`).

## CSV Growth Loop

Every successful `/api/analyze` call appends one row to `StudentsPerformance_Extended.csv` with `test preparation course = "eduai_web"` as a marker. This means the training data grows over time. Delete the `.joblib` file to force retraining on the updated dataset.

## Installing Dependencies

```bash
# Uses .venv_backend (separate from .venv)
pip install -r backend/requirements.txt
```

## Tests

```bash
python model_test_f1.py   # Cross-validation F1 report for the sklearn model
python test_round.py      # Ad-hoc round/scoring tests
python -m pytest backend/test_performance.py  # Backend performance tests
```

## Key Files

| File | Purpose |
|---|---|
| `backend/app.py` | FastAPI app, Gemini integration, prompt builder |
| `backend/ml_context.py` | Model training, loading, z-score logic |
| `backend/submission_csv.py` | Thread-safe CSV append |
| `students_performance_starter.py` | Standalone CLI version (legacy; hardcoded key) |
| `recommendation/` | Older design docs and model artifacts (not used by the web backend) |
