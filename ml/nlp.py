"""Financial text sentiment. Uses FinBERT (ProsusAI/finbert) when `transformers` is installed,
otherwise a finance-specific lexicon in the spirit of Loughran-McDonald."""
from __future__ import annotations

import re
from functools import lru_cache

POS = {"beat", "beats", "exceeded", "record", "growth", "upgrade", "upgraded", "strong", "outperform", "raised",
       "raise", "profitable", "expansion", "surge", "gain", "gains", "improved", "accretive", "buyback", "approval"}
NEG = {"miss", "missed", "decline", "declined", "downgrade", "downgraded", "weak", "loss", "losses", "lawsuit",
       "investigation", "recall", "impairment", "default", "bankruptcy", "layoffs", "cut", "warning", "restatement",
       "delisting", "fraud", "subpoena", "going concern", "material weakness"}
RISK_TERMS = {"going concern", "material weakness", "restatement", "subpoena", "investigation", "default", "covenant"}


@lru_cache(maxsize=1)
def _finbert():
    try:
        from transformers import pipeline
        return pipeline("sentiment-analysis", model="ProsusAI/finbert")
    except Exception:
        return None


def sentiment(text: str) -> dict:
    fb = _finbert()
    if fb is not None:
        r = fb(text[:2000])[0]
        sign = {"positive": 1, "negative": -1}.get(r["label"].lower(), 0)
        return {"score": sign * r["score"], "label": r["label"].lower(), "model": "finbert"}
    low = text.lower()
    words = re.findall(r"[a-z]+", low)
    p = sum(w in POS for w in words)
    n = sum(w in NEG for w in words) + sum(low.count(t) for t in NEG if " " in t)
    score = (p - n) / max(1, p + n)
    risks = sorted(t for t in RISK_TERMS if t in low)
    return {"score": round(score, 3), "label": "positive" if score > 0.15 else "negative" if score < -0.15 else "neutral",
            "emerging_risks": risks, "model": "lexicon"}


def sentiment_change(texts_by_period: list[str]) -> list[float]:
    s = [sentiment(t)["score"] for t in texts_by_period]
    return [round(b - a, 3) for a, b in zip(s, s[1:])]
