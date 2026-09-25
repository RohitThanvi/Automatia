"""
Spec section 26 lists core/router.py as its own module. The actual
model-selection logic lives in Planner._choose_model (core/planner.py)
since it needs the same client/config the planner already holds —
duplicating it here would risk the two drifting apart. This module
re-exports a stable, testable entry point for it.
"""

from __future__ import annotations

from core.planner import Planner

_planner_singleton: Planner | None = None


def choose_model_for(user_text: str, history_len: int) -> str:
    global _planner_singleton
    if _planner_singleton is None:
        _planner_singleton = Planner()
    return _planner_singleton._choose_model(user_text, history_len)  # noqa: SLF001
