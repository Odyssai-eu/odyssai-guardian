# Odyssai Guardian

Confidential-content detection sidecar for the odyssai.eu stack. A small HTTP
service that a client (Nemo's **guardian**, or the CoeOS box) calls before
a user message leaves for a provider, to detect personal / confidential data
and keep it on a local engine instead of the cloud.

**Detection only.** Policy — warn / force-local / block — lives in the caller.
Guardian returns *what* was found; the caller decides *what to do*.

## Two stages

| Stage | What | Model | Latency | Always on? |
|---|---|---|---|---|
| **1 — PII / RGPD** | identifiers + GDPR-identification (an attribute tied to an identity) | GLiNER2 (`fastino/gliner2-privacy-filter-PII-multi`) | ~40 ms | yes |
| **2 — contextual** | business secret, health narrative, HR, legal, strategy — what NER misses | a direct YES/NO prompt to a small instruct LLM | ~200-400 ms | opt-in per request |

Stage 2 runs only when the caller passes `contextual: true` **and** stage 1 is
clean (no point paying the LLM latency once the PII pass already flagged it).

### The RGPD-identification model (stage 1)

A quasi-identifier **attribute** alone (a salary figure, a medical term) is
**not** confidential — "how do I negotiate my salary" is a generic topic. It
becomes personal data only when tied to an **identity** (name / email / phone):
"Marie's salary is 85k" identifies a person. **Hard identifiers** (IBAN, SSN,
card, passport) and **secrets** (API key, password) are sensitive on their own.

```
sensitive = hard_identifier  OR  secret  OR  (identity AND attribute)
```

## API

- `GET /health` → `{status, service, model, loaded, contextual_available}`
- `POST /guard`
  ```json
  { "text": "...", "threshold": 0.5,
    "contextual": true, "llm_base": "http://<engine>:8000/v1", "llm_model": "<model alias served there>" }
  ```
  → `{ "sensitive": bool, "max_severity": "none|high", "findings": [{category, severity, spans}], "latency_ms": float }`

**No hardcoded endpoint.** The stage-2 `llm_base` + `llm_model` are supplied by
the caller in each request — the client's add-on config is the single source of
truth. Empty `llm_base` ⇒ stage 2 skipped. Fail-open: a stage-2 error never
blocks a verdict.

## Install

**Docker (recommended — and required on macOS when stage 2 calls a remote engine):**

```bash
docker compose up -d          # port 8084; the image bakes the GLiNER model, nothing to configure
curl -s http://localhost:8084/health
```

The first `/guard` request lazy-loads GLiNER (~5 s); subsequent calls take
~40 ms. Guardian is stateless apart from the models it loads: it never stores
messages and never decides policy.

> ⚠️ On macOS, do **not** run stage 2 under launchd/nohup: those processes are
> blocked from outbound LAN (Local Network privacy) and the call to a remote LLM
> fails silently. A Docker container is not affected. If you must run natively
> (`com.odyssai.guardian.plist` is provided, with `__INSTALL_DIR__` placeholders
> to substitute), pre-download the GLiNER model once — the service runs with
> `HF_HUB_OFFLINE=1` — and keep stage 2 off or pointed at `localhost`.

## Wire the client (Nemo's guardian, or the CoeOS box)

1. **Guard service URL** = `http://<guardian-host>:8084/guard` (required). From
   another container on the same compose network: `http://guardian:8084/guard`.
2. **Policy** = `warn` (tell the user) or `force-local` (route the message to a
   local model instead of the cloud). Policy is the caller's; Guardian only
   reports what it found.
3. Stage 2 is optional and configured **in the caller**: it passes `llm_base`
   (any OpenAI-compatible endpoint — an OdyssAI-X engine, typically) and
   `llm_model` (an alias that engine serves) in each request. No endpoint is
   ever hardcoded in Guardian.

## OdyssAI — two components

OdyssAI is two pieces: **OdyssAI-X**, the engine, and **CoeOS**, the client — shipped as **Nemo**, the app, and the **CoeOS box**, the smart router behind it.

| Component | Repo | Role |
|---|---|---|
| **OdyssAI-X** (engine) | [Odyssai-eu/OdyssAI-X](https://github.com/Odyssai-eu/OdyssAI-X) | distributed / replica / VLM MLX inference on Apple Silicon; OpenAI + Anthropic API; dashboard. AGPL-3.0 |
| **Nemo** (the CoeOS client) | [Odyssai-eu/coeos](https://github.com/Odyssai-eu/coeos) | a desktop AI operating system for one person: chat with visible reasoning and personal memory, cowork on documents, code with a panel of agents; every turn shows which model served it. Signed, notarized macOS app ([releases](https://github.com/Odyssai-eu/coeos/releases)). MIT |
| **CoeOS box** (the smart router) | [Odyssai-eu/coeos-box](https://github.com/Odyssai-eu/coeos-box) | every request goes to the model proven best at that skill — local on the engine, or cloud with your own keys. Users, tokens, quotas, the *Theseus* console. MIT |

Guardian (this repo) is the confidential-content detection sidecar the client's guardian (Nemo) and the CoeOS box call before anything leaves for a cloud provider. Also in the organisation: [odyssai-services](https://github.com/Odyssai-eu/odyssai-services), [mlx-swift-lm](https://github.com/Odyssai-eu/mlx-swift-lm).

## Tuning stage 2

Stage 2 is a single short prompt (`_SYSTEM` in `contextual.py`) — no training,
no dataset, no artifact. Edit the prompt and re-measure against
`data/contextual_seed.jsonl` (the held-out test set).

Held-out metrics on the 24-example seed (deployed in Docker), by stage-2 model:
- a small instruct model with thinking off (Qwen3-30B-class, ~400 ms): **precision 1.0, recall 1.0, F1 1.0**;
- a Qwen3-8B-class draft model (~110 ms): precision 1.0, recall 0.92, F1 0.96.

`llm_model` defaults to `tele-fast` in the code — an alias from our own cluster;
pass the alias **your** engine serves.

Next iteration: a **LoRA** fine-tune, if the direct prompt plateaus.
