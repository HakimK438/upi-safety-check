# Decisions

- **OCR runs on the phone (Tesseract WASM), not the server.** Server OCR measured p50 11.8 s and needs internet; on-device is ~0.7 s warm on a laptop, offline, nothing uploaded. Server OCR stays only as an opt-in "deeper scan". Engine files (~7 MB) are served from our own origin and cached, never from a CDN.
- **Grayscale + 1% auto-contrast before OCR.** Without it white-on-colour headers are unreadable (timestamp 62% -> 92%, app 44% -> 92%).
- **UTR is the key; the amount is confirmed by the user when OCR cannot match it.** OCR reads the rupee sign as a digit ("3440.5" for 440.5) or misses short amounts. We never silently strip digits: a real small payment re-used under an edited larger amount is a known trick.
- **Near-miss UTR (<=2 digits) is "probable", never green.** A camera misread is far likelier than a different payment, but the user must compare the highlighted digits.
- **Bank SMS join the ledger, but only with a 12-digit UPI reference.** SMS can be spoofed, so SMS-only credits >= Rs 10,000 ask for a bank-app glance (arbitrary default, `SMS_ONLY_LARGE_PAISE`). SMS never extend what the statement covers, so an SMS-only ledger cannot say "not found".
- **The model reads, rules decide.** No model ever produces the verdict.
- **Check log keeps only amount, outcome, method and timing**, on-device, to power the dashboard and a measured speed figure.

## 2026-10-21: real fraud data, five-model comparison, one Fraud check page
- Synthetic UPI datasets dropped for training: `upi_transactions_2024.csv` has random labels (time-split ROC-AUC 0.47) and `upi_fraud_gh` is synthetic with weak signal. Real UPI fraud labels are not public.
- Train on IEEE-CIS (Vesta, real chargeback labels); ULB card data is a second real benchmark. Card payments, not UPI, and the UI says so.
- Two feature sets: deployable (fields a gateway gives + history from the merchant's own payments) ships; research (+ masked bank-side columns) only measures the gap.
- Training rows: all fraud + 25% of genuine for speed. Validation and test keep the real rate; isotonic calibration on validation fixes the probability shift.
- Model choice on validation PR-AUC, never on test. Cut-off chosen by cost (missed fraud = its amount, false alarm = $25 review (staff time + a delayed genuine customer)).
- The model and its stored results stay in US dollars, as in the data.

## 2026-10-21: Fraud check page redesign (Phase A2) and rupees on screen
- One scrolling page in 5 numbered steps replaces the 6 tabs; scoring runs only when the merchant presses **Check payment** (it no longer re-scores while typing).
- A horizontal Approve | Check | Block bar replaces the speedometer. Each zone takes a third of the bar so small risks stay readable; the cut-off values are printed under the boundaries.
- "Models agree" counts the models that fall in the same zone as the shipped model, using the shipped model's cut-offs.
- Zone colours are used only for risk, each model keeps one colour, and other charts use neutral greys. All charts are 300 px high.
- **Money is shown in rupees at a fixed ₹88 = $1** (user request). The form takes rupees and converts to dollars before calling the model; the conversion lives in `frontend/src/lib/fraudApi.ts` (`INR_PER_USD`). The rate only changes how numbers are displayed, not the model: the data is still US card payments, and the screen says so.

## 2026-10-21: synthetic dataset as the main training data (user decision)
- The user asked for a dataset where one cut-off reaches 90-92% precision AND recall. Real IEEE-CIS cannot do that with merchant-visible fields (best: 22% / 60% at a cost cut-off, or 89% Block precision / 88% Block+Check recall with three zones).
- `backend/ml/make_synthetic_ieee.py` simulates 593,794 payments over 183 days in the IEEE-CIS column layout, 3.4% fraud. Amounts, products, cards, email domains and device strings are sampled from the real rows. Fraud comes from 5 named patterns (account takeover, card testing, mule ring, repeat offender, friendly fraud), and genuine customers include honest look-alikes (new phones, travel, night shopping, shared family devices), so the data is not trivially separable.
- Generator knobs (pattern shares, burst/device probabilities) were tuned until a quick XGBoost check reached about 92% precision and 90% recall on the test months. Because those numbers come from how the data was generated, they are labelled SYNTHETIC everywhere and never presented as real-world accuracy.
- Models (user choice): logistic regression, random forest, XGBoost, and a PyTorch neural network (256-128-64, batch norm, dropout, class-weighted loss, early stopping on the last 10% of training rows, quantile-scaled inputs). LightGBM and the rule baseline were dropped.
- On synthetic data the single cut-off is the best F1 on validation (not the $25 cost rule), so precision and recall can both be read from one setting.
- The last real-data run is frozen in `docs/ml/fraud_results_real.json` and shown on the page as "Real-data check". `python ml/train_fraud.py --data real` still reproduces the real run.

## 2026-10-21: Fraud check page v3 (user feedback)
- The page treats the derived dataset as the project's dataset: no synthetic/real labels and no real-data check section (user decision). How the data was made stays documented here and in `ml/make_synthetic_ieee.py`.
- Page = Check a payment -> Result -> Model comparison -> "Why people commit fraud" (collapsed). Removed: example buttons, model agreement, data exploration, key-number tiles, alert level, cost/calibration/month charts, reviewer charts, What drives fraud.
- Result shows a verdict banner, a 100-dot "fraud chance" grid, the risk bar, up to 3 reasons and numbered steps. Zone words are Genuine / Check / Fraud.
- Each model card opens a pop-up with all metrics, a 2x2 confusion matrix (Fraud / Genuine) and its own ROC and PR curves.
- The theme picker and Appearance page were removed; the app uses the default theme only.

## 2026-10-21: Fraud check page, second redesign (user feedback)
- Three numbered sections, no tabs or pop-ups: 1 Check a payment, 2 Which model is best?, 3 How fraud shows up.
- Result appears only after Check payment: one word (Safe / Check first / Likely fraud), fraud chance vs a normal payment, models that agree, up to 3 reasons, what to do. The 100-dot grid and the zone bar were removed (`RiskBar.tsx` deleted) because users found them confusing.
- Model comparison is four stacked sections, one per model (Logistic regression first, XGBoost last, "In use" tag): precision, recall, F1, the coloured 2x2 confusion matrix and that model's own ROC and PR curves. The wide table was removed at the user's request (too broad, hard to read). Training and test sizes live on a separate page (to do).
- "Accounts on this phone" moved under "More details"; three example buttons (Safe / Check first / Likely fraud) show how to use the form.

## 2026-10-21: Page 0 Shell
- Menu is now the 9 + 2 items from the page plan. Old pages (Safety, Number, Handle, Report, Why) stay routable but are not in the menu; they are deleted in step 9. `/models` and `/message` redirect to `/messages` (currently the old message checker, replaced in Page 9).
- The blue Fraud check palette is now app-wide (`:root` in `index.css`); the amber themes are gone.
- Top bar chip "Sample data · N payments" replaces the ledger-freshness chip. The on-device reader is no longer pre-loaded.
- Phone bar: Dashboard, Payments, Fraud check (centre), Risk alerts, More (sheet with the other pages).
- Shared parts live in `frontend/src/components/shell.tsx`: `KpiCard`, `ChartCard`, `Tip`, `StatusChip`, `PageHeader`, `EmptyState`, `Money`, `AX`, `TT`. FraudPage keeps its own copies so it is unchanged.

## 2026-10-21: Page 1 Dashboard
- One endpoint, `GET /api/merchant/{ds}/dashboard` (`backend/app/merchant/dashboard.py`), returns every number and chart for one set of slicers. Default range = last 30 days of the data ("This month").
- Definitions: Sales = orders; In your bank = settlements (a branch view uses payments marked successful, since settlements have no branch); Refunded = refunds; Not received = amount of "pending payment", "order with no payment" and "settlement lower" findings; Looks risky = payments the existing risk model puts in Check or Fraud (to be switched to the Fraud check model on the Risk alerts page). The waterfall adds an "Other" step so it always sums to money in the bank.
- Chart clicks are slicers (day, status, branch, risk zone, hour x weekday). A chart ignores its own slicer, so a click highlights a bar instead of hiding the rest. Status, zone and heatmap clicks change the payment charts only; sales, bank and refund figures follow date, branch and day.
- KPI cards open `/transactions?tab=<all|received|refunded|not_received|risky>&date_from&date_to&branch`. The Payments page reads these when it is rebuilt (Page 4).
- The old Overview page was deleted.

## 2026-10-21: Dashboard data switched to the synthetic IEEE-layout data (user decision)
- The old `upi_fraud_gh` sample and the old `txn_risk` model no longer feed the Dashboard. `ml/make_merchant_sample.py` takes the TEST period (days 150-182, never seen by the four fraud models) of `data/raw/ieee_synth`, keeps 1 payment in 10 (seeded), converts to rupees at the fixed 88 per dollar, scores every payment with the shipped XGBoost model and the Fraud check cut-offs, and writes `data/merchant_sample/transactions.csv`.
- Branches are 12 groups made from the billing region. Status is simulated: most succeed, a few fail or stay pending, ~70% of fraud ends as a reversal. Orders, refunds and settlements are still generated from the payments with planted problems.
- Risk zones come from the stored model scores (`risk.assess_scored`); reasons are the plain-word warning signs (new phone, burst, amount spike...). Uploads still use the old path.
- "vs last period" is hidden when the data starts inside the previous period.
- If the CSV is missing (fresh clone), the built-in generator is used so the app and tests still run. Rebuild with `cd backend && python ml/make_merchant_sample.py`.

## 2026-10-21: Pages 2-10 and clean-up (page plan steps 2-9)
- Built Payments, Check a payment, Bank record, Missing money, Risk alerts, Action center, My data, Scam messages and How it works, all on the Dashboard's synthetic data and the shared parts in `components/shell.tsx`.
- Every payment opens Fraud check pre-filled (`/?amount=&time=&burst=&prior=&lastPaid=&usual=&auto=1`). The inputs are worked out server-side from the payer's own earlier payments (`analytics.fraud_inputs`).
- Risk alerts: Fraud / Fine marks are written to `backend/data/review_labels/<dataset>.json` (git-ignored) for the next retrain. Bank record additions and imports, recent checks and "done" actions stay in the browser.
- Payments filters are server-side (`tab`, `branch`, dates, search) with a CSV export that uses the same filters. New endpoints: `/dashboard`, `/transactions.csv`, `/risk` (zones, reasons, fraud inputs), `/labels`, `/explore/table`, `/explore/eda`.
- Scam messages: the comparison shows, per model, precision / recall / F1, the confusion matrix, the words it leans on most, and its own score for the message pasted above. ROC/PR curves were dropped from this page (user request).
- Removed: Fraud models, Risk "Why", Safety hub, Number, Handle, Report, Statement, the scan / OCR / screenshot code (frontend and `app/services/extract.py`), Themes, `fraud_lab.py`, `models_lab.py`, `/api/triage`, `/api/extract`, `/api/numbers`, `/api/reference`, the consumer seed data, and the tesseract / pdf.js / idb-keyval dependencies. Old URLs redirect (`/models`, `/message` to `/messages`; `/why` to `/risk`; `/safety`, `/number`, `/handle`, `/report` to `/`).
- Uploaded datasets are scored by the older `txn_risk` model, not the four fraud models, until their columns are mapped onto the fraud model inputs.

## 2026-10-21: No login, no Hindi, cached sample (user decision)
- Removed accounts completely: the login page, `lib/auth`, the `/api/auth/*` endpoints, the users table (`app/auth.py`, `app/db.py`) and their tests. The app opens straight on the sample business.
- Removed the Hindi toggle and `lib/ctx.tsx`; all text is English.
- The analysed sample is cached in `backend/data/merchant_sample/_analyzed.pkl`, keyed on the CSV and the modules that shape it, so a restart no longer makes the first Dashboard request wait about 37 seconds.

## 2026-10-21: Clean-up for publishing (user decision)
- The repository keeps only what runs the site. Everything else (real IEEE-CIS / ULB / old UPI datasets, notebooks, original idea documents, generated test files, screenshots, logs, old reports) was moved out of the project folder to a sibling `ml-upi-archive/`.
- The synthetic data folder `ieee_synth` is now plain `backend/data/`. The sample (`data/merchant_sample/`) and the trained models (`models/*.joblib`) are committed because the app needs them; real datasets, the optional Shade63 message set (no licence), caches and review marks are git-ignored, as are `CLAUDE.md`, `.claude/` and `.mcp.json`.
- `ml/train_txn_risk.py` and `ml/fetch_datasets.py` were archived: the older risk model (`models/txn_risk.joblib`) ships as a file, its training data is gone.
