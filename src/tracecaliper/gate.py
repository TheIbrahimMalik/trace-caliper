"""Release-gate decision logic for TraceCaliper.

:func:`decide` derives a :class:`~tracecaliper.models.GateDecision` from a
:class:`~tracecaliper.models.Comparison` using the rule table documented in
``library/architecture.md``.

Rules (evaluated in priority order):

1. ``SECURITY_FLAG`` in ``introduced`` → **HOLD** (new critical security issue).
2. ``SECURITY_FLAG`` in ``persistent`` → **INVESTIGATE** (existing security issue unresolved).
3. Zero delta AND no introduced AND no resolved (identical / no-op comparison) → **PASS**.
4. ``introduced`` empty AND ``resolved`` non-empty AND ``aggregate_delta >= 0`` → **PASS**
   (pure improvement).
5. ``introduced`` non-empty AND ``resolved`` non-empty (no security flag) → **INVESTIGATE**
   (mixed signals).
6. ``introduced`` non-empty AND ``resolved`` empty (no security flag) → **HOLD**
   (pure regression).
7. ``aggregate_delta < 0`` (no introduced, no resolved) → **HOLD** (score regression only).
8. Default → **PASS** (positive or zero delta, no new failures).

The ``rationale`` list is always non-empty and cites concrete signals
(failure-mode codes, the sign / value of the aggregate delta, or dimension
names) so that the output is self-explanatory to a human reviewer.

All computations are pure and deterministic.  :func:`decide` never mutates
its input and produces byte-identical output across repeated invocations.
"""

from __future__ import annotations

from tracecaliper.models import Comparison, GateDecision


def decide(comparison: Comparison) -> GateDecision:
    """Derive a release-gate :class:`GateDecision` from a *comparison*.

    Args:
        comparison: The pairwise comparison to evaluate.

    Returns:
        :class:`~tracecaliper.models.GateDecision` with a ``decision``
        (``PASS``, ``HOLD``, or ``INVESTIGATE``) and a non-empty
        ``rationale`` list citing the concrete signals that drove the
        outcome.
    """
    introduced = set(comparison.introduced)
    resolved = set(comparison.resolved)
    persistent = set(comparison.persistent)
    delta = comparison.aggregate_delta

    rationale: list[str] = []

    # ------------------------------------------------------------------
    # Rule 1: SECURITY_FLAG newly introduced → HOLD
    # ------------------------------------------------------------------
    if "SECURITY_FLAG" in introduced:
        rationale.append(
            "SECURITY_FLAG was introduced in the candidate — "
            "a new critical security issue requires immediate attention."
        )
        other_intro = sorted(introduced - {"SECURITY_FLAG"})
        if other_intro:
            rationale.append(
                f"Additional failure mode(s) also introduced: "
                f"{', '.join(other_intro)}."
            )
        if resolved:
            rationale.append(
                f"Failure mode(s) resolved in candidate: "
                f"{', '.join(sorted(resolved))}; "
                "but the new SECURITY_FLAG still blocks PASS."
            )
        if persistent:
            rationale.append(
                f"Persistent failure mode(s) (unchanged from baseline): "
                f"{', '.join(sorted(persistent))}."
            )
        _append_delta_note(rationale, delta)
        return GateDecision(decision="HOLD", rationale=rationale)

    # ------------------------------------------------------------------
    # Rule 2: SECURITY_FLAG persistent (unresolved) → INVESTIGATE
    # ------------------------------------------------------------------
    if "SECURITY_FLAG" in persistent:
        rationale.append(
            "SECURITY_FLAG persists unresolved from the baseline — "
            "the existing security issue has not been addressed."
        )
        other_persistent = sorted(persistent - {"SECURITY_FLAG"})
        if other_persistent:
            rationale.append(
                f"Other persistent failure mode(s) also remain unresolved: "
                f"{', '.join(other_persistent)}."
            )
        if resolved:
            rationale.append(
                f"Other failure mode(s) were resolved: {', '.join(sorted(resolved))}."
            )
        if introduced:
            rationale.append(
                f"Additional failure mode(s) introduced: {', '.join(sorted(introduced))}."
            )
        _append_delta_note(rationale, delta)
        return GateDecision(decision="INVESTIGATE", rationale=rationale)

    # ------------------------------------------------------------------
    # Rule 3: No-op / identical comparison → PASS
    # Fires only when ALL per-dimension deltas are exactly 0, aggregate
    # delta is 0, and all three diff sets are empty.  Comparisons where
    # per-dimension changes offset each other (aggregate==0 but individual
    # dimensions moved) fall through to the regular rules below.
    # ------------------------------------------------------------------
    all_dim_deltas_zero = all(v == 0.0 for v in comparison.dimension_deltas.values())
    if not introduced and not resolved and not persistent and delta == 0.0 and all_dim_deltas_zero:
        rationale.append(
            "Identical comparison: aggregate delta is 0.0, all per-dimension "
            "deltas are 0.0, and no failure modes were introduced, resolved, "
            "or persistent."
        )
        return GateDecision(decision="PASS", rationale=rationale)

    # ------------------------------------------------------------------
    # Rule 4: Pure improvement — resolved non-empty, nothing introduced,
    #         aggregate delta non-negative → PASS
    # ------------------------------------------------------------------
    if resolved and not introduced and delta >= 0.0:
        rationale.append(
            f"{len(resolved)} failure mode(s) resolved "
            f"({', '.join(sorted(resolved))}) and none introduced."
        )
        if delta > 0.0:
            rationale.append(
                f"Aggregate delta is {delta:+.6f}, indicating overall score improvement."
            )
        else:
            rationale.append(
                "Aggregate delta is 0.0; scores unchanged but failure modes improved."
            )
        if persistent:
            rationale.append(
                f"Persistent failure mode(s) remain: {', '.join(sorted(persistent))}."
            )
        return GateDecision(decision="PASS", rationale=rationale)

    # ------------------------------------------------------------------
    # Rule 5: Mixed signals — both introduced and resolved → INVESTIGATE
    # ------------------------------------------------------------------
    if introduced and resolved:
        rationale.append(
            f"Mixed signals: failure mode(s) introduced "
            f"({', '.join(sorted(introduced))}) and resolved "
            f"({', '.join(sorted(resolved))}) simultaneously."
        )
        _append_delta_note(rationale, delta)
        if persistent:
            rationale.append(
                f"Persistent failure mode(s): {', '.join(sorted(persistent))}."
            )
        return GateDecision(decision="INVESTIGATE", rationale=rationale)

    # ------------------------------------------------------------------
    # Rule 6: Pure regression — introductions only, nothing resolved → HOLD
    # ------------------------------------------------------------------
    if introduced and not resolved:
        rationale.append(
            f"Pure regression: failure mode(s) introduced "
            f"({', '.join(sorted(introduced))}) with none resolved."
        )
        _append_delta_note(rationale, delta)
        if persistent:
            rationale.append(
                f"Persistent failure mode(s): {', '.join(sorted(persistent))}."
            )
        return GateDecision(decision="HOLD", rationale=rationale)

    # ------------------------------------------------------------------
    # Rule 7: Negative aggregate delta (no introduced modes) → HOLD
    # At this point introduced is always empty (Rules 5 and 6 handled
    # non-empty introduced).  resolved may be non-empty when Rule 4 was
    # skipped due to a negative delta.  Rationale always cites concrete
    # resolved codes when present rather than claiming no changes occurred.
    # ------------------------------------------------------------------
    if delta < 0.0:
        rationale.append(
            f"Aggregate delta is strictly negative ({delta:+.6f}), "
            "reflecting an overall score regression."
        )
        if resolved:
            rationale.append(
                f"Failure mode(s) resolved in candidate: "
                f"{', '.join(sorted(resolved))}; "
                "but the negative aggregate delta still blocks PASS."
            )
        else:
            rationale.append("No failure modes were introduced or resolved.")
        if persistent:
            rationale.append(
                f"Persistent failure mode(s): {', '.join(sorted(persistent))}."
            )
        return GateDecision(decision="HOLD", rationale=rationale)

    # ------------------------------------------------------------------
    # Rule 8: Default — non-negative delta, no introductions, no resolutions → PASS
    # ------------------------------------------------------------------
    rationale.append(
        f"No failure modes introduced; aggregate delta is {delta:+.6f}."
    )
    if persistent:
        rationale.append(
            f"Persistent failure mode(s) unchanged: {', '.join(sorted(persistent))}."
        )
    return GateDecision(decision="PASS", rationale=rationale)


def _append_delta_note(rationale: list[str], delta: float) -> None:
    """Append a concrete delta note to *rationale* when the delta is non-zero."""
    if delta < 0.0:
        rationale.append(
            f"Aggregate delta is negative ({delta:+.6f}), "
            "reflecting an overall score regression."
        )
    elif delta > 0.0:
        rationale.append(
            f"Aggregate delta is positive ({delta:+.6f}), "
            "reflecting partial score improvement."
        )


__all__ = ["decide"]
