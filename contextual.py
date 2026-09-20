"""Stage 2 — contextual confidential classifier.

Catches CONTEXTUAL confidential content that the stage-1 NER (GLiNER) misses:
business secrets, health narrative, HR, legal, strategy — none of which is a
named entity. A single short prompt to a small instruct LLM (any
OpenAI-compatible endpoint) returns a YES/NO verdict + a category word.

Why not DSPy: the structured-output machinery was ~13 s/call and collapsed to
0 recall on out-of-distribution inputs (measured 2026-07-14). A direct YES/NO
prompt with max_tokens tiny is ~100-200 ms and generalises (F1 1.0 with
tele-fast, 0.96 with dsparkqwen on the held-out seed). Simpler and faster wins.

No hardcoded endpoint: the LLM base + model are passed per /guard request by
the caller (the CoeOS add-on's config). Fail-open: any error → classify()
returns None and the caller keeps the stage-1 verdict.
"""
import re
import threading

from openai import OpenAI

_VALID_CATS = {
    "business_secret",
    "health_narrative",
    "hr_personal",
    "legal_confidential",
    "strategy_internal",
}

_SYSTEM = (
    "Tu es un détecteur de confidentialité. Détermine si le MESSAGE de "
    "l'utilisateur contient de l'information CONFIDENTIELLE d'entreprise ou "
    "personnelle sensible : secret d'affaires, chiffres/résultats non publics, "
    "RH nominatif non annoncé, juridique confidentiel, stratégie interne non "
    "annoncée, ou santé d'une personne identifiable. Un sujet traité de façon "
    "GÉNÉRALE ou informative (question, définition, conseil générique) n'est "
    "PAS confidentiel.\n"
    "Réponds en UN SEUL mot :\n"
    "- 'NON' si le message n'est pas confidentiel.\n"
    "- sinon la catégorie exacte : business_secret, health_narrative, "
    "hr_personal, legal_confidential, ou strategy_internal."
)

_clients = {}
_lock = threading.Lock()
_TOKEN_RE = re.compile(r"[a-z_]+")


def dspy_available() -> bool:
    """Kept for the /health contract. Stage 2 is now a direct HTTP call with no
    artifact or heavy deps — it's available whenever an endpoint is supplied."""
    return True


def _client(base: str):
    with _lock:
        c = _clients.get(base)
        if c is None:
            c = OpenAI(base_url=base, api_key="x")
            _clients[base] = c
        return c


def classify(text: str, llm_base: str, llm_model: str = "tele-fast"):
    """Return {sensitive, category, spans} or None.

    None when stage 2 is off (no llm_base) OR on any error — fail-open by
    contract. The endpoint is caller-supplied (no hardcoded URL)."""
    if not llm_base:
        return None
    try:
        resp = _client(llm_base).chat.completions.create(
            model=llm_model or "tele-fast",
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": text},
            ],
            temperature=0.0,
            max_tokens=8,
            # Qwen3-family models think by default; a tiny budget + thinking off
            # keeps the call ~100-200 ms instead of seconds.
            extra_body={"enable_thinking": False},
        )
        out = (resp.choices[0].message.content or "").strip().lower()
        # First alphabetic token decides. "non" → clean; a category → sensitive.
        m = _TOKEN_RE.search(out)
        tok = m.group(0) if m else ""
        if not tok or tok.startswith("non"):
            return {"sensitive": False, "category": "none", "spans": []}
        category = tok if tok in _VALID_CATS else "business_secret"
        return {"sensitive": True, "category": category, "spans": []}
    except Exception:  # noqa: BLE001 — fail-open
        return None
