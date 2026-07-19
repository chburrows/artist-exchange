"""I15: `effective_anchor_uc`'s continuous glide.

Must be monotone in `now`, exactly `anchor_uc` at/before the window
start, exactly `target_uc` at/after the window end, and collapse to
`target_uc` immediately for a degenerate (empty or inverted) window.
"""

from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from ax.core.amm import effective_anchor_uc

uc_value = st.integers(min_value=0, max_value=10**9)


@st.composite
def glide_window(draw: st.DrawFn) -> tuple[datetime, timedelta, int, int]:
    """`(glide_start, duration, elapsed1, elapsed2)` with
    `0 <= elapsed1 <= elapsed2 <= duration_us` and `duration > 0` --
    a well-formed glide window plus two in-window sample points."""
    start = draw(
        st.datetimes(
            min_value=datetime(2020, 1, 1),
            max_value=datetime(2035, 1, 1),
            timezones=st.just(UTC),
        )
    )
    duration_us = draw(st.integers(min_value=1, max_value=30 * 86_400 * 1_000_000))
    e1 = draw(st.integers(min_value=0, max_value=duration_us))
    e2 = draw(st.integers(min_value=e1, max_value=duration_us))
    return start, timedelta(microseconds=duration_us), e1, e2


@given(anchor_uc=uc_value, target_uc=uc_value, window=glide_window())
def test_glide_is_exact_at_start_and_end(
    anchor_uc: int, target_uc: int, window: tuple[datetime, timedelta, int, int]
) -> None:
    start, duration, _, _ = window
    end = start + duration

    assert effective_anchor_uc(anchor_uc, target_uc, start, end, start) == anchor_uc
    assert effective_anchor_uc(anchor_uc, target_uc, start, end, end) == target_uc


@given(anchor_uc=uc_value, target_uc=uc_value, window=glide_window())
def test_glide_before_start_and_after_end(
    anchor_uc: int, target_uc: int, window: tuple[datetime, timedelta, int, int]
) -> None:
    start, duration, _, _ = window
    end = start + duration

    assert effective_anchor_uc(anchor_uc, target_uc, start, end, start - timedelta(seconds=1)) == (
        anchor_uc
    )
    assert effective_anchor_uc(anchor_uc, target_uc, start, end, end + timedelta(seconds=1)) == (
        target_uc
    )


@given(anchor_uc=uc_value, target_uc=uc_value, window=glide_window())
def test_glide_is_monotone_toward_target(
    anchor_uc: int, target_uc: int, window: tuple[datetime, timedelta, int, int]
) -> None:
    start, duration, e1, e2 = window
    end = start + duration
    now1 = start + timedelta(microseconds=e1)
    now2 = start + timedelta(microseconds=e2)

    v1 = effective_anchor_uc(anchor_uc, target_uc, start, end, now1)
    v2 = effective_anchor_uc(anchor_uc, target_uc, start, end, now2)

    if target_uc >= anchor_uc:
        assert v1 <= v2
    else:
        assert v1 >= v2


@given(
    anchor_uc=uc_value,
    target_uc=uc_value,
    start=st.datetimes(
        min_value=datetime(2020, 1, 1), max_value=datetime(2035, 1, 1), timezones=st.just(UTC)
    ),
    now_offset_seconds=st.integers(min_value=-1_000_000, max_value=1_000_000),
)
def test_degenerate_window_always_returns_target(
    anchor_uc: int, target_uc: int, start: datetime, now_offset_seconds: int
) -> None:
    now = start + timedelta(seconds=now_offset_seconds)

    # end == start: an instantaneous window.
    assert effective_anchor_uc(anchor_uc, target_uc, start, start, now) == target_uc
    # end < start: an inverted window.
    assert (
        effective_anchor_uc(anchor_uc, target_uc, start, start - timedelta(seconds=1), now)
        == target_uc
    )
