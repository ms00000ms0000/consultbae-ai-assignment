# ConsultBae AI Automation Assignment

## Setup
1. `pip install -r requirements.txt`
2. `python db/merge_pipeline.py`  → builds `db/consultbae.db` from the 3 CSVs
3. `streamlit run audio_app/app.py` → audio collection app

## Structure
- `data/` — raw input CSVs
- `db/` — merge pipeline + SQLite schema
- `n8n/` — exported automation flow (JSON)
- `audio_app/` — Streamlit audio collection app
- `docs/DATA_ISSUES.md` — Task 4 report
- `docs/STRETCH.md` — Task 5

## Stuck Log
(fill during actual work — 2-3 hardest problems, how solved)
