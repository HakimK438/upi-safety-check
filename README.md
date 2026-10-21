# UPI Safety Check

A fraud and payment-safety dashboard for small UPI merchants. It answers three questions in plain words: **did the money arrive, where did money go missing, and which payments look like fraud.**

Backend: FastAPI + scikit-learn / XGBoost / LightGBM / PyTorch (`backend/`). Frontend: React + Vite + Tailwind + Recharts PWA (`frontend/`). No login, English only.

> **All data and every score here is synthetic.** The four fraud models were trained and tested on synthetic payments in the IEEE-CIS layout, and the Dashboard sample is made from their unseen test period. Nothing says anything about real UPI fraud rates.

## Run it

Everything the app needs is in the repository (synthetic data, trained models, sample).

Backend (Python 3.12):
```
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt            # see the note in the file about the CPU build of PyTorch
.venv\Scripts\python -m uvicorn app.main:app --port 8010
```
Frontend (Node 20+), in a second terminal:
```
cd frontend
npm install
npm run dev                                              # http://localhost:5173 (proxies /api to :8010)
```
Open http://localhost:5173. The first start analyses the sample business (about half a minute) and caches it in `backend/data/merchant_sample/_analyzed.pkl`; later starts are quick.

Tests: `cd backend && python -m pytest -q` · `cd frontend && npx tsc --noEmit && npm run build`

## The pages

| Group | Page | Route | What it does |
|---|---|---|---|
| Counter | Fraud check | `/` | Score one payment with the 4 models; compare them (precision, recall, F1, confusion matrix, ROC, PR) |
| Counter | Dashboard | `/dashboard` | Sales, money in the bank, refunds, not received, risk; slicers; charts filter each other |
| Counter | Check a payment | `/check` | Bank reference (UTR) + amount: found and matching, found but different, or not found |
| Counter | Bank record | `/ledger` | Money in your bank; add a payment or import a CSV |
| Business | Payments | `/transactions` | 5 tabs with counts, search, filters, detail drawer, CSV export |
| Business | Missing money | `/reconciliation` | One waterfall and four causes with links |
| Business | Risk alerts | `/risk` | Safe / Check / Fraud counts and a review queue (Fraud / Fine marks are saved for the next retrain) |
| Business | Action center | `/actions` | Do now, this week, done |
| Business | My data | `/data` | Upload your four files, and a data explorer with EDA |
| Help | Scam messages | `/messages` | Paste an SMS; compare the 3 message models |
| Help | How it works | `/about` | The flow, how the models were trained and tested, limits |

Every payment can be opened in Fraud check pre-filled from the merchant's own payment history, and every page links to the next one. A user guide is in [HOW-TO-USE.md](HOW-TO-USE.md).

## Folder structure

```
backend/
  app/                 FastAPI app (main.py) and the merchant package: analytics, dashboard, reconcile, risk, explore, fraud and spam models
  data/                the synthetic data (train_transaction.csv, train_identity.csv, _patterns.csv), spam.csv, and merchant_sample/ (the Dashboard sample)
  models/              the trained fraud models (fraud_models.joblib), the older upload risk model, the model registry
  ml/                  scripts that regenerate the data, the models and the sample
  tests/               pytest suite
  Dockerfile           backend image (used by Render)
frontend/              React app (src/pages, src/components, src/lib)
render.yaml            Render blueprint for the backend
docs/                  DECISIONS.md (design decisions) and ml/ (evaluation results shown on the Fraud check page)
```

## How the pieces fit

```
data/ (synthetic payments) --ml/train_fraud.py--> models/fraud_models.joblib + docs/ml/fraud_results.json
   |
   +-- test period (days 150-182, never seen) --ml/make_merchant_sample.py--> data/merchant_sample/transactions.csv (scored by XGBoost)
                                                                                 |
   orders, refunds, settlements generated from it (problems planted) --app/merchant/sample.py--> in-memory sample business
                                                                                 |
                      /api/merchant/{dataset}/dashboard | transactions | risk | explore | ... --> the pages
```

- **Models:** time split only (train days 0-119, validation 120-149, test 150-182). Three-zone decision: Block, Check, Approve. Details in [docs/DECISIONS.md](docs/DECISIONS.md).
- **Uploads** (`POST /api/merchant/datasets`) are validated and held in memory for 2 hours. They are scored by the older risk model, not the four fraud models.
- **Review marks** (Fraud / Fine on Risk alerts) are written to `backend/data/review_labels/` (not committed).

## Deploy

The frontend is static and goes on **Vercel**. The backend (FastAPI + PyTorch/XGBoost models) is too large for Vercel functions, so it runs as a Docker service on **Render**. The two are joined by one environment variable.

1. **Backend on Render.** New > Blueprint > pick this repository and branch; Render reads `render.yaml` and builds `backend/Dockerfile`. The plan is `standard` (2 GB) because the backend uses about 580 MB once PyTorch loads, which is more than the 512 MB plans have. When it is live, note its address, for example `https://upi-safety-check-api.onrender.com`. Check `https://<that address>/api/health`. The first request after a start analyses the sample (about half a minute).
2. **Frontend on Vercel.** Add New > Project > import this repository, branch `clean-release`, and set **Root Directory** to `frontend`. Framework preset: Vite (`frontend/vercel.json` sets the build and the single-page fallback). Under Environment Variables add `VITE_API_BASE` = `https://<the Render address>/api`, then Deploy.
3. **CORS.** The API already accepts any `https://*.vercel.app` address (`CORS_ORIGIN_REGEX` in `render.yaml`). For a custom domain, add it to `CORS_ORIGINS` on Render (comma-separated).

Local Docker test of the backend: `docker build -f backend/Dockerfile -t upi-safety-api .` then `docker run -p 8010:8010 upi-safety-api`.

## Regenerating the data and models (optional)

Only needed to rebuild from scratch. `ml/make_synthetic_ieee.py` copies value pools (amounts, email domains, devices) from the real IEEE-CIS files, which are not in this repository (Kaggle competition rules): download `train_transaction.csv` and `train_identity.csv` into `backend/data/raw/ieee_cis/` first.
```
cd backend
python ml/make_synthetic_ieee.py      # synthetic payments -> data/
python ml/train_fraud.py              # the 4 models + evaluation (about 10 minutes)
python ml/make_merchant_sample.py     # the Dashboard sample -> data/merchant_sample/
```

## Data notes

- `data/spam.csv` is the public UCI SMS Spam Collection. The optional Indian scam-message set (Shade63) has no licence, so it is **not** included; without it the Scam messages page trains on the English set only. To use it, place `sentinel_dataset_multiclass.csv` in `backend/data/shade63/` (git-ignored).
- The real IEEE-CIS and ULB credit-card datasets are not included.

## Limits

- Synthetic data throughout; the planted problems in orders, refunds and settlements are the only "leakage" the app can find in the sample.
- Fraud check judges card-style signals and has not been tested on real UPI payments.
- Scam message data is template-heavy, so real messages may score lower.
- Rate limiting is in memory only; dataset isolation relies on unguessable ids.
