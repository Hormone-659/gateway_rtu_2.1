"""Threshold engine wrapper around existing threshold_analyzer logic.

This module provides a simple, UI-independent API that other parts of the
system (UIs, background services) can use to compute 0/1/2/3 fault levels
from vibration speed values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

# The existing implementation lives under gateway.sensor.threshold_analyzer.
# We import and adapt it instead of reimplementing the logic.
try:
    from gateway.sensor.threshold_analyzer import (  # type: ignore
        ThresholdConfig,
        MultiChannelThresholdAnalyzer,
    )
except Exception:  # pragma: no cover - allows import in environments without full package setup
    ThresholdConfig = None  # type: ignore
    MultiChannelThresholdAnalyzer = None  # type: ignore


@dataclass
class SimpleThresholdConfig:
    level1: float
    level2: float
    level3: float


class SpeedThresholdEngine:
    """Convenience wrapper for per-channel threshold evaluation.

    The engine is intentionally stateless per call so that services can call
    it with the latest value and immediately get a fault level 0/1/2/3.
    If the project later requires more advanced logic (e.g. hysteresis,
    time windows), that should be delegated to the underlying
    MultiChannelThresholdAnalyzer implementation.
    """

    def __init__(self, cfg: SimpleThresholdConfig) -> None:
        if ThresholdConfig is None or MultiChannelThresholdAnalyzer is None:
            raise RuntimeError(
                "gateway.sensor.threshold_analyzer is not available. "
                "Ensure it is importable in the deployment environment."
            )
        self._cfg = cfg
        self._analyzer = MultiChannelThresholdAnalyzer(
            ThresholdConfig(cfg.level1, cfg.level2, cfg.level3)
        )

    def evaluate_single(self, value: float) -> int:
        """Return fault level (0~3) for a single vibration speed value."""

        levels = self._analyzer.update({"v": value})  # type: ignore[call-arg]
        # We expect 'v' to be the single channel; analyzer should return a dict
        # mapping channel -> level. Fallback to 0 if not present.
        return int(levels.get("v", 0))  # type: ignore[union-attr]

    def evaluate_multi(self, values: Dict[str, float]) -> Dict[str, int]:
        """Evaluate multiple named channels at once.

        Parameters
        ----------
        values:
            Mapping from channel name to vibration speed value.
        """

        levels = self._analyzer.update(values)  # type: ignore[call-arg]
        return {name: int(level) for name, level in levels.items()}  # type: ignore[union-attr]


__all__ = ["SimpleThresholdConfig", "SpeedThresholdEngine"]
