import numpy as np

from core.config import Settings
from core.schemas import Interval, Probability


def simulate(
    anchor: float,
    years: float,
    settings: Settings,
    shift: float = 0.0,
    proxy: bool = True,
    extra_log_sigma: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    if (
        anchor <= 0
        or years < 0
        or extra_log_sigma < 0
        or not np.isfinite([anchor, years, shift, extra_log_sigma]).all()
    ):
        raise ValueError("Invalid anchor, horizon or adjustment")
    rng = np.random.default_rng(settings.seed)
    sigma = np.sqrt(
        settings.annual_log_volatility**2 * years
        + (settings.proxy_extra_log_sigma**2 if proxy else 0)
        + extra_log_sigma**2
    )
    noise = rng.standard_normal(settings.samples)
    baseline = anchor * np.exp(settings.annual_log_drift * years + sigma * noise)
    posterior = baseline * np.exp(
        np.clip(shift, -settings.max_total_log_shift, settings.max_total_log_shift)
    )
    return baseline, posterior


def interval_probabilities(samples: np.ndarray, intervals: list[Interval]) -> list[Probability]:
    if len(samples) == 0 or not np.isfinite(samples).all() or (samples < 0).any():
        raise ValueError("Samples must be nonempty finite nonnegative values")
    rows = [
        Probability(
            interval=i.label,
            probability=float(
                np.mean(
                    (samples >= i.lower) & (samples < (i.upper if i.upper is not None else np.inf))
                )
            ),
        )
        for i in intervals
    ]
    if abs(sum(p.probability for p in rows) - 1) > 1e-8:
        raise ValueError("Intervals do not partition samples")
    return rows
