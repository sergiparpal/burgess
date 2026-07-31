"""Pluggable text embeddings + near-duplicate suppression.

Three providers, selected by the ``KG_DIVERGE_EMBEDDER`` environment variable:

* ``static`` — model2vec ``minishlab/potion-multilingual-128M`` (256-dim, **101
  languages**, distilled from ``BAAI/bge-m3``, MIT). Static embeddings, so
  **inference needs only numpy — no torch**, and the weights are ~120 MB (vs.
  ~2 GB for the torch stack). A **different model family** from the agent →
  satisfies the lineage hedge. This is the **default** for real runs; lazily
  downloaded on first use.
* ``local`` — sentence-transformers ``BAAI/bge-small-en-v1.5`` (CPU, ~33M params,
  384-dim, **English-only**). The opt-in **high-fidelity** option; needs the
  torch stack (``pip install -r requirements-local.txt``). Lazily downloaded.
* ``hash``  — deterministic char-n-gram hashing vectorizer (no downloads). Used
  by the test suite and non-live ``selftest``. Lexically similar text → similar
  vectors, so dedup is meaningful.

(``api`` is a reserved name for a hosted provider: selecting it raises a clear
ConfigError until a real backend lands — review-r5 removed the hollow stub class.)

All embedders return an ``(n, d)`` float32 array of **L2-normalized** rows, so
cosine similarity is a plain dot product.

Note: ``static`` (256-dim) and ``local`` (384-dim) produce different-width,
incompatible geometries; ``pipeline._guard_embedding_dim`` refuses to mix them
within one project, so switching the default is breaking for projects persisted
under the old default (re-embed, or pin ``KG_DIVERGE_EMBEDDER=local``).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from .config import ConfigError, require_sklearn

ENV_VAR = "KG_DIVERGE_EMBEDDER"
DEFAULT_PROVIDER = "static"
DEFAULT_STATIC_MODEL = "minishlab/potion-multilingual-128M"
DEFAULT_LOCAL_MODEL = "BAAI/bge-small-en-v1.5"
HASH_DIM = 512

# Per-embedder near-duplicate cosine thresholds. Cosine scale is family-specific:
# "the same idea, reworded" sits at different similarities under a char-n-gram
# hashing vectorizer vs. a sentence model, so one global tau misfires when the
# embedder changes. Keyed by ``Embedder.name``; unknown families fall back to the
# default.
DEFAULT_DEDUP_TAU = 0.92
DEDUP_TAU_BY_EMBEDDER = {
    "hash": 0.92,    # char-n-gram cosines: near-dupes cluster ~0.92+
    "static": 0.93,  # potion (model2vec): trivial restatements ~0.96-0.99 EN/ES,
                     # genuine synonym variations ~0.86, distinct ideas <=0.43 —
                     # 0.93 drops the former, keeps the latter (calibrated on a
                     # near-dup/distinct EN+ES sample).
    "local": 0.94,   # sentence-transformer cosines run higher; raise the bar
    "api": 0.92,     # unknown backend: conservative default
}


def default_dedup_tau(embedder_name: str) -> float:
    """Near-duplicate cosine threshold calibrated to the embedder family."""
    return DEDUP_TAU_BY_EMBEDDER.get(embedder_name, DEFAULT_DEDUP_TAU)


def l2_normalize(mat: np.ndarray) -> np.ndarray:
    mat = np.asarray(mat, dtype=np.float32)
    if mat.ndim == 1:
        mat = mat.reshape(1, -1)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return (mat / norms).astype(np.float32)


class Embedder:
    """Interface: turn texts into an ``(n, d)`` array of normalized rows.

    ``embed`` is a **template method** — it coerces the inputs to ``str``, short-
    circuits the empty case, calls the subclass hook :meth:`_embed_raw`, and then
    L2-normalizes. Centralizing the normalization here means a new provider only
    implements ``_embed_raw`` and *cannot forget* to return unit rows, which the
    rest of the math relies on (cosine == dot product).
    """

    name: str = "base"
    dim: int = 0

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        texts = [t if isinstance(t, str) else str(t) for t in texts]
        if not texts:
            return np.zeros((0, self._dim_for_empty()), dtype=np.float32)
        return l2_normalize(self._embed_raw(texts))

    def _dim_for_empty(self) -> int:
        """Width of the empty-input result. Defaults to ``self.dim``; embedders whose
        ``dim`` is resolved LAZILY (model loaded on first real embed) override this to
        resolve it, so an accidental ``embed([])`` before the first real call can't
        return a 0-width array that would later trip ``_guard_embedding_dim``. Eager-dim
        providers (hash / api / tests) keep the default and load nothing."""
        return self.dim

    def _embed_raw(self, texts: list[str]) -> np.ndarray:  # pragma: no cover
        """Return UNnormalized ``(n, d)`` rows; the base class normalizes them."""
        raise NotImplementedError


class HashingEmbedder(Embedder):
    """Deterministic, dependency-light embedder over character n-grams."""

    name = "hash"

    def __init__(self, dim: int = HASH_DIM):
        require_sklearn("hash embedder")  # actionable ConfigError instead of a raw ModuleNotFoundError
        from sklearn.feature_extraction.text import HashingVectorizer

        self.dim = dim
        self._vec = HashingVectorizer(
            n_features=dim,
            analyzer="char_wb",
            ngram_range=(2, 4),
            alternate_sign=True,
            norm=None,  # we normalize ourselves so zero rows are handled
        )

    def _embed_raw(self, texts: list[str]) -> np.ndarray:
        return self._vec.transform(texts).toarray()


class LazyModelEmbedder(Embedder):
    """Base for embedders that download/load a model on FIRST USE (review-r5: StaticEmbedder and
    LocalEmbedder copy-pasted the whole lazy-load scaffold, and a third provider would have cloned
    it again). A subclass supplies ``_load() -> (model, dim)``; this base owns the lazy `_ensure`
    (guard clause, not a 30-line nest), the model/dim caching, and the lazy `_dim_for_empty` — so a
    new provider cannot forget the empty-input dim contract."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None
        self.dim = 0

    def _load(self):  # pragma: no cover - abstract
        """Import the backend, load the model, and return ``(model, dim)``."""
        raise NotImplementedError

    def _ensure(self):
        if self._model is not None:
            return self._model
        self._model, self.dim = self._load()
        return self._model

    def _dim_for_empty(self) -> int:
        self._ensure()  # dim is unknown until the model loads
        return self.dim


class StaticEmbedder(LazyModelEmbedder):
    """model2vec static embedder (lazy model load).

    Static token embeddings averaged per text, so **inference needs only numpy**
    (no torch). The default real-run embedder: multilingual and ~120 MB on disk.
    """

    name = "static"

    def __init__(self, model_name: str = DEFAULT_STATIC_MODEL):
        super().__init__(model_name)

    def _load(self):
        # I9 (graceful degradation): the divergence layer must fail with a
        # clear, actionable message when its deps/weights are unavailable —
        # and NOTHING in the convergence (kg_*) path is affected, because
        # this import happens only when an embedding is actually requested.
        # Cache the model artifact in the plugin's persistent data dir when
        # one is configured, so plugin updates don't re-download weights.
        data_dir = os.environ.get("KG_DATA")
        if data_dir and not os.environ.get("HF_HOME"):
            os.environ["HF_HOME"] = str(Path(data_dir) / "models")
        try:
            from model2vec import StaticModel
        except ImportError as exc:
            raise ConfigError(
                "divergence embedder unavailable: the 'model2vec' package is "
                "not installed in the engine venv. Re-run provisioning (the "
                "SessionStart hook, or `python scripts/bootstrap.py`), or set "
                "KG_DIVERGE_EMBEDDER=hash for the deterministic offline "
                "embedder. Convergence (kg_*) tools are unaffected."
            ) from exc
        try:
            model = StaticModel.from_pretrained(self.model_name)
        except Exception as exc:
            raise ConfigError(
                f"divergence embedder unavailable: could not load model "
                f"{self.model_name!r} ({exc}). If you are offline, retry once "
                f"the model has been downloaded (it is cached under "
                f"$HF_HOME after the first use), or set "
                f"KG_DIVERGE_EMBEDDER=hash for the deterministic offline "
                f"embedder. Convergence (kg_*) tools are unaffected."
            ) from exc
        return model, int(model.dim)

    def _embed_raw(self, texts: list[str]) -> np.ndarray:
        model = self._ensure()
        # StaticModel.encode already returns a float32 ndarray; the base class
        # L2-normalizes, so we only need the raw rows here.
        return np.asarray(model.encode(list(texts)), dtype=np.float32)


class LocalEmbedder(LazyModelEmbedder):
    """sentence-transformers embedder (lazy model load)."""

    name = "local"

    def __init__(self, model_name: str = DEFAULT_LOCAL_MODEL):
        super().__init__(model_name)

    def _load(self):
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(self.model_name)
        # method was renamed across sentence-transformers versions
        get_dim = getattr(model, "get_embedding_dimension", None) or getattr(
            model, "get_sentence_embedding_dimension"
        )
        return model, int(get_dim())

    def _embed_raw(self, texts: list[str]) -> np.ndarray:
        model = self._ensure()
        return model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )


_CACHE: "dict[str, Embedder]" = {}


def get_embedder(provider: str | None = None) -> Embedder:
    """Return the embedder selected by ``provider`` or ``$KG_DIVERGE_EMBEDDER``.

    Cached per-provider so repeated calls reuse the (lazily loaded) model.
    """
    provider = (provider or os.environ.get(ENV_VAR) or DEFAULT_PROVIDER).strip().lower()
    if provider in _CACHE:
        return _CACHE[provider]
    if provider == "static":
        emb: Embedder = StaticEmbedder()
    elif provider == "hash":
        emb = HashingEmbedder()
    elif provider == "local":
        emb = LocalEmbedder()
    elif provider == "api":
        # A named-but-unwired provider (review-r5: the old APIEmbedder class was 19 hollow lines +
        # two env-var contracts existing solely to phrase this error at first USE; failing at
        # SELECTION is clearer). Reintroduce a real class when a hosted backend lands.
        raise ConfigError(
            f"embedder provider 'api' has no wired backend; set {ENV_VAR}=static, =hash or =local"
        )
    else:
        raise ValueError(
            f"unknown embedder provider {provider!r}; expected static|hash|local"
        )
    _CACHE[provider] = emb
    return emb


def reset_cache() -> None:
    """Clear the embedder cache (tests switching providers)."""
    _CACHE.clear()


# --------------------------------------------------------------------------- #
# Near-duplicate suppression
# --------------------------------------------------------------------------- #
def dedupe(
    vecs: np.ndarray,
    tau: float = DEFAULT_DEDUP_TAU,
    existing: np.ndarray | None = None,
) -> tuple[list[int], list[int]]:
    """Greedy near-duplicate removal over normalized rows.

    Keeps a row unless its cosine similarity to an already-kept row (or to any
    ``existing`` row) exceeds ``tau``.

    Returns ``(keep_indices, drop_indices)`` into ``vecs`` (row order preserved).
    """
    vecs = np.asarray(vecs, dtype=np.float32)
    n = vecs.shape[0]
    if n == 0:
        return [], []
    dim = vecs.shape[1]
    # Running buffer of kept rows (existing seeds first, then survivors) so we
    # never re-vstack the whole set on each step — one preallocated matrix.
    n_existing = 0 if existing is None else len(existing)
    kept = np.empty((n_existing + n, dim), dtype=np.float32)
    count = 0
    if n_existing:
        kept[:n_existing] = np.asarray(existing, dtype=np.float32)
        count = n_existing
    keep: list[int] = []
    drop: list[int] = []
    for i in range(n):
        v = vecs[i]
        if count and float(np.max(kept[:count] @ v)) > tau:
            drop.append(i)
            continue
        keep.append(i)
        kept[count] = v
        count += 1
    return keep, drop
