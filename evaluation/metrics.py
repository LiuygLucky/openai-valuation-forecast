import numpy as np


def brier_score(probabilities, realized_index):
    """Multiclass Brier score, used ONLY after an outcome is actually resolved."""
    p = np.asarray(probabilities, dtype=float)
    if p.ndim != 1 or not np.isfinite(p).all() or (p < 0).any() or not np.isclose(p.sum(), 1):
        raise ValueError("Invalid probability distribution")
    if not 0 <= realized_index < len(p):
        raise ValueError("Invalid resolved outcome index")
    actual = np.zeros_like(p)
    actual[realized_index] = 1
    return float(np.sum((p - actual) ** 2))
