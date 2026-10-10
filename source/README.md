# Utility Bill Decoder — WTQ 2026 Build Track

Reads K-Electric, LESCO and IESCO electricity bill images, extracts the billing details
(Level 1 JSON) and answers customer questions in plain English (Level 2).

**Runtime:** Python 3.14 (tested on Windows with Python 3.14 and Linux with Python 3.13; requires 3.11+)

## Setup

```bash
cd source
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
# edit .env: set API_KEY (and MODEL_PROVIDER / MODEL_NAME if not using Gemini)
```

## Run

Generate both CSV files for a folder of bills (paths relative to `source/`):

```bash
python -m billdecoder.main run --bills ../test/bills --level1 ../test/csv/level1.csv --level2 ../test/csv/level2.csv --out ../output
```

Outputs `../output/level1.csv` (one compact JSON per bill) and `../output/level2.csv`
(one answer per question). Row order, column names, `bill_id`, `question_id` and `question`
are preserved from the templates.

Decode a single bill and ask questions (used for the demo):

```bash
python -m billdecoder.main demo --bill ../train/bills/KESC_0008.png --question "How much of my bill is taxes?"
```

Offline unit tests (no API key needed):

```bash
python -m unittest discover tests
```

## How it works

```
bill image ──► [1] Vision extraction (LLM, provider-specific prompt)
                     │  rich facts: Level 1 fields + line labels, usage history, late amounts
                     ▼
               [2] Normalisation (code): numbers, CR→negative, ISO dates, type enums,
                     drop 0-lines, highest late amount, provider from file name
                     ▼
               [3] Cross-checks (code): Σcharges vs total, Σtaxes vs total, readings vs units,
                     dates order  ──mismatch──► one focused re-read by the LLM
                     ▼
                level1.csv           facts cached in .cache/ (each bill read once)
                     ▼
               [4] PLAN (LLM, text-only): arithmetic each question needs
               [5] COMPUTE (code): safe AST evaluator + pre-computed bill statistics
               [6] WRITE (LLM + image): plain-English answers using only bill data and
                     code-verified numbers; estimates labelled, missing info stated
                     ▼
                level2.csv
```

Design choices:

- **LLM where it adds value:** reading varied, tilted, partly-Urdu layouts and writing explanations.
- **Code where it is more reliable:** format rules, arithmetic, validation. The model never does
  arithmetic in its answers; it plans expressions that code evaluates (no `eval` of arbitrary code).
- **Extract as printed:** cross-checks only trigger a re-read; they never overwrite printed values.
- **Robustness:** retries with backoff, client-side rate limiting (Gemini free tier), per-bill error
  isolation, and no empty CSV cells (failed bills get null JSON / an explicit fallback answer).
- **Cost:** about 2–3 LLM calls per bill (extraction, optional verify, plan + answer for all 12 questions).
- **Privacy:** prompts forbid personal identifiers; the Level 1 schema has no identifier fields.

## Project layout

```
billdecoder/
  config.py     env settings + allowed-model whitelist
  llm.py        provider wrapper (Gemini / Claude / OpenAI), retries, JSON parsing, image prep
  prompts.py    all prompts and per-provider layout hints
  extract.py    Level 1 pipeline with cache and verify pass
  normalize.py  schema enforcement and consistency checks
  calc.py       safe arithmetic evaluator and bill statistics
  answer.py     Level 2 plan → compute → write
  main.py       CLI (run / demo)
tests/          offline unit tests
sample/         CSV templates for the 5 training bills
```

## AI usage

- **Models used by the solution:** Gemini 3.5 Flash-Lite (`gemini-3.5-flash-lite`) via Google AI Studio
  — the model named in `.env.example`. The code also supports the other allowed models
  (`gemini-3.1-flash-lite`, `claude-haiku-4-5`, `gpt-4.1-mini`, `gpt-5-mini`) by changing `.env`; only
  allowed model IDs are accepted (see `config.py`).
- **APIs:** Google Gen AI API (`google-genai` SDK). Anthropic and OpenAI SDKs are included only for
  the optional provider switch.
- **Services:** none (no OCR services, no invoice/receipt extraction agents, no Azure services).
- **Local OCR libraries:** none.
- **AI tools used to write the code:** Claude (Anthropic) chat assistant, used to help write and
  review the code, prompts and README.
