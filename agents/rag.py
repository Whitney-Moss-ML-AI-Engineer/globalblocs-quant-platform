"""Retrieval for research agents. Default: local TF-IDF index over agents/knowledge (methodology docs,
filings text, past research). For production, swap in pgvector embeddings (schema in data_pipelines/schema.sql)."""
from __future__ import annotations

from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class Retriever:
    def __init__(self, folder: str | None = None, chunk: int = 1200):
        folder = folder or str(Path(__file__).parent / "knowledge")
        self.docs = []
        for p in sorted(Path(folder).glob("**/*")):
            if p.suffix.lower() in {".md", ".txt"}:
                t = p.read_text(errors="ignore")
                self.docs += [{"source": str(p), "text": t[i:i + chunk]} for i in range(0, len(t), chunk)]
        self.vec = TfidfVectorizer(stop_words="english") if self.docs else None
        self.m = self.vec.fit_transform([d["text"] for d in self.docs]) if self.docs else None

    def search(self, query: str, k: int = 5) -> list[dict]:
        if not self.docs:
            return []
        sims = cosine_similarity(self.vec.transform([query]), self.m)[0]
        return [{**self.docs[i], "score": float(sims[i])} for i in sims.argsort()[::-1][:k]]
