"""Tests for Agent 4: Demand forecasting, and the history store behind it.

Prophet is stubbed throughout. It is a heavy dependency with a compiled
backend, and the counting, gap filling and trend classification logic is worth
testing without paying for a model fit on every run.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from agents.extraction import Confidence, ExtractedSkill, Relevance, Requirements
from agents.forecasting import (
    MIN_TOTAL_MENTIONS,
    MIN_WEEKS_FOR_FORECAST,
    DemandReport,
    SkillDemand,
    Trend,
    bootstrap_series_from_posting_dates,
    build_bootstrap_report,
    build_report_from_series,
    classify_share_trend,
    classify_trend,
    count_weekly_mentions,
    fill_missing_weeks,
    forecast_skill,
    week_starting,
)
from db import history

# Pinned so tests using fixed calendar dates do not start failing as real time
# moves past the reconstruction window. Individual tests may override it.
FIXED_TODAY = date(2026, 9, 21)


@pytest.fixture(autouse=True)
def _pin_today(monkeypatch):
    monkeypatch.setattr("agents.forecasting.today", lambda: FIXED_TODAY)

MONDAY = date(2026, 9, 7)


def _requirements(skills: list[str], posting_id: str = "1") -> Requirements:
    return Requirements(
        posting_id=posting_id,
        source="reed",
        confidence=Confidence.FULL,
        relevance=Relevance.IN_DOMAIN,
        skills=[ExtractedSkill(name=s, evidence=s) for s in skills],
    )


def _weekly(values: list[int], start: date = MONDAY) -> dict[date, int]:
    return {start + timedelta(weeks=i): v for i, v in enumerate(values)}


class StubProphet:
    """Returns a fixed final prediction, so trend logic can be tested exactly."""

    def __init__(self, predicted: float = 10.0, **kwargs):
        self.predicted = predicted
        self.kwargs = kwargs

    def fit(self, frame):
        self.rows = len(frame)
        return self

    def make_future_dataframe(self, periods: int, freq: str):
        import pandas as pd

        self.freq = freq
        return pd.DataFrame({"ds": range(self.rows + periods)})

    def predict(self, future):
        import pandas as pd

        return pd.DataFrame({"yhat": [self.predicted] * len(future)})


def _prophet_returning(value: float):
    return lambda **kwargs: StubProphet(predicted=value, **kwargs)


# ---------------------------------------------------------------------------
# Week bucketing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "day, expected",
    [
        (date(2026, 9, 7), date(2026, 9, 7)),
        (date(2026, 9, 10), date(2026, 9, 7)),
        (date(2026, 9, 13), date(2026, 9, 7)),
        (date(2026, 9, 14), date(2026, 9, 14)),
    ],
)
def test_dates_bucket_to_the_monday_of_their_week(day, expected):
    assert week_starting(day) == expected


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def test_counts_postings_not_mentions():
    """A verbose posting repeating a skill must not distort the week."""
    verbose = _requirements(["Python", "Python", "Python"], posting_id="a")
    terse = _requirements(["Python"], posting_id="b")

    counts = count_weekly_mentions([(MONDAY, [verbose, terse])])

    assert counts["Python"][MONDAY] == 2


def test_runs_in_the_same_week_are_combined():
    counts = count_weekly_mentions([
        (MONDAY, [_requirements(["SQL"])]),
        (MONDAY + timedelta(days=3), [_requirements(["SQL"])]),
    ])

    assert counts["SQL"] == {MONDAY: 2}


def test_separate_weeks_stay_separate():
    counts = count_weekly_mentions([
        (MONDAY, [_requirements(["SQL"])]),
        (MONDAY + timedelta(weeks=1), [_requirements(["SQL"])]),
    ])

    assert len(counts["SQL"]) == 2


# ---------------------------------------------------------------------------
# Gap filling
# ---------------------------------------------------------------------------


def test_missing_weeks_are_filled_with_zeros():
    """A skill that disappears has genuinely fallen. Leaving the gap absent
    would let the model interpolate straight through the decline."""
    sparse = {MONDAY: 5, MONDAY + timedelta(weeks=3): 1}

    filled = fill_missing_weeks(sparse)

    assert len(filled) == 4
    assert filled[MONDAY + timedelta(weeks=1)] == 0
    assert filled[MONDAY + timedelta(weeks=2)] == 0


def test_filling_an_empty_series_is_safe():
    assert fill_missing_weeks({}) == {}


# ---------------------------------------------------------------------------
# Trend classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "current, predicted, expected",
    [
        (10, 15, Trend.RISING),
        (10, 5, Trend.FALLING),
        (10, 10.5, Trend.STABLE),
        (10, 9.5, Trend.STABLE),
        (0, 3, Trend.RISING),
        (0, 0, Trend.STABLE),
    ],
)
def test_trend_classification(current, predicted, expected):
    trend, _ = classify_trend(current, predicted)
    assert trend is expected


def test_small_moves_are_treated_as_noise():
    """Four to five mentions a week is not a market signal."""
    trend, _ = classify_trend(4, 5)
    assert trend is Trend.RISING  # 25 percent clears the threshold
    trend, _ = classify_trend(20, 21)
    assert trend is Trend.STABLE  # 5 percent does not


# ---------------------------------------------------------------------------
# Forecast guard rails
# ---------------------------------------------------------------------------


def test_too_few_mentions_reports_insufficient_history():
    result = forecast_skill("Python", _weekly([1, 1]), prophet_cls=_prophet_returning(50))

    assert result.trend is Trend.INSUFFICIENT_HISTORY
    assert result.is_forecast is False
    assert "too few" in result.note


def test_too_few_weeks_reports_insufficient_history():
    """Enough mentions but not enough weeks. Fitting here would be noise."""
    series = _weekly([20, 20, 20])

    result = forecast_skill("Python", series, prophet_cls=_prophet_returning(50))

    assert result.trend is Trend.INSUFFICIENT_HISTORY
    assert result.is_forecast is False
    assert str(MIN_WEEKS_FOR_FORECAST) in result.note


def test_sufficient_history_produces_a_forecast():
    series = _weekly([10] * MIN_WEEKS_FOR_FORECAST)

    result = forecast_skill("Python", series, prophet_cls=_prophet_returning(15.0))

    assert result.is_forecast is True
    assert result.trend is Trend.RISING
    assert result.forecast_weekly_rate == 15.0
    assert result.change_pct == 50.0


def test_yearly_seasonality_is_never_requested():
    """The failure that ruined the previous project's occupancy forecasts was
    asking for an annual cycle the data could not support."""
    captured = {}

    def capture(**kwargs):
        captured.update(kwargs)
        return StubProphet(predicted=10.0)

    forecast_skill("Python", _weekly([10] * MIN_WEEKS_FOR_FORECAST), prophet_cls=capture)

    assert captured["yearly_seasonality"] is False
    assert captured["weekly_seasonality"] is False


def test_model_failure_degrades_to_no_forecast():
    """Losing a forecast is acceptable. Losing the report is not."""

    def exploding(**kwargs):
        class Boom:
            def fit(self, frame):
                raise RuntimeError("solver did not converge")

        return Boom()

    result = forecast_skill("Python", _weekly([10] * MIN_WEEKS_FOR_FORECAST), prophet_cls=exploding)

    assert result.is_forecast is False
    assert result.trend is Trend.INSUFFICIENT_HISTORY
    assert "model fitting failed" in result.note


def test_negative_predictions_are_floored_at_zero():
    """A skill cannot be asked for a negative number of times."""
    result = forecast_skill(
        "Python", _weekly([10] * MIN_WEEKS_FOR_FORECAST), prophet_cls=_prophet_returning(-5.0)
    )

    assert result.forecast_weekly_rate == 0.0


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def test_report_separates_rising_from_falling():
    series = {
        "Python": _weekly([10] * MIN_WEEKS_FOR_FORECAST),
        "Hadoop": _weekly([10] * MIN_WEEKS_FOR_FORECAST),
    }

    rising = build_report_from_series(series, prophet_cls=_prophet_returning(20.0))
    falling = build_report_from_series(series, prophet_cls=_prophet_returning(2.0))

    assert {s.skill for s in rising.rising()} == {"Python", "Hadoop"}
    assert {s.skill for s in falling.falling()} == {"Python", "Hadoop"}


def test_most_demanded_ranks_by_total_mentions():
    report = DemandReport(
        generated_for_week=MONDAY,
        skills=[
            SkillDemand("SQL", 40, 8, 5.0, Trend.STABLE),
            SkillDemand("Python", 100, 8, 12.0, Trend.STABLE),
            SkillDemand("Go", 5, 8, 1.0, Trend.STABLE),
        ],
    )

    assert [s.skill for s in report.most_demanded()] == ["Python", "SQL", "Go"]


# ---------------------------------------------------------------------------
# History store
# ---------------------------------------------------------------------------


def test_snapshot_counts_postings_per_skill():
    snapshot = history.summarise(
        [_requirements(["Python", "SQL"], "a"), _requirements(["Python"], "b")],
        run_date=MONDAY,
    )

    assert snapshot.postings_seen == 2
    assert snapshot.skill_counts == {"Python": 2, "SQL": 1}


def test_history_round_trips_through_disk(tmp_path):
    path = tmp_path / "history.json"
    snapshot = history.summarise([_requirements(["Python"])], run_date=MONDAY)

    history.append(snapshot, path)
    loaded = history.load(path)

    assert len(loaded) == 1
    assert loaded[0].run_date == MONDAY
    assert loaded[0].skill_counts == {"Python": 1}


def test_rerunning_on_the_same_day_replaces_rather_than_doubles(tmp_path):
    """Testing the pipeline repeatedly must not inflate that day's demand."""
    path = tmp_path / "history.json"

    history.append(history.summarise([_requirements(["Python"])], run_date=MONDAY), path)
    history.append(history.summarise([_requirements(["Python"])], run_date=MONDAY), path)

    loaded = history.load(path)
    assert len(loaded) == 1
    assert loaded[0].skill_counts == {"Python": 1}


def test_history_is_kept_in_date_order(tmp_path):
    path = tmp_path / "history.json"
    later = MONDAY + timedelta(weeks=1)

    history.append(history.summarise([_requirements(["SQL"])], run_date=later), path)
    history.append(history.summarise([_requirements(["SQL"])], run_date=MONDAY), path)

    assert [s.run_date for s in history.load(path)] == [MONDAY, later]


def test_corrupt_history_is_ignored_rather_than_fatal(tmp_path):
    """Losing trend data is recoverable. Losing the run is not."""
    path = tmp_path / "history.json"
    path.write_text("{not valid json", encoding="utf-8")

    assert history.load(path) == []


def test_missing_history_file_is_not_an_error(tmp_path):
    assert history.load(tmp_path / "nothing.json") == []


def test_series_reshapes_history_for_the_forecaster(tmp_path):
    path = tmp_path / "history.json"
    history.append(history.summarise([_requirements(["Python"])], run_date=MONDAY), path)
    history.append(
        history.summarise([_requirements(["Python"]), _requirements(["Python"], "c")],
                          run_date=MONDAY + timedelta(weeks=1)),
        path,
    )

    series = history.as_series(history.load(path))

    assert series["Python"] == {MONDAY: 1, MONDAY + timedelta(weeks=1): 2}


def test_min_total_mentions_is_respected_end_to_end():
    """Enough weeks of history, but too few mentions in total to mean anything.

    A skill seen twice across two months is not a trend, however many weeks
    the series happens to span.
    """
    sparse = [1, 0, 1, 0, 0, 0, 0, 0][:MIN_WEEKS_FOR_FORECAST]
    series = {"Rare": _weekly(sparse)}

    report = build_report_from_series(series, prophet_cls=_prophet_returning(10.0))

    assert sum(sparse) < MIN_TOTAL_MENTIONS  # guards the fixture
    assert len(sparse) >= MIN_WEEKS_FOR_FORECAST  # weeks are not the problem
    assert report.skills[0].trend is Trend.INSUFFICIENT_HISTORY
    assert report.skills[0].total_mentions == sum(sparse)


# ---------------------------------------------------------------------------
# Bootstrapping from posting dates
# ---------------------------------------------------------------------------


def _req(posting_id: str, skills: list[str]) -> Requirements:
    return Requirements(
        posting_id=posting_id,
        source="reed",
        confidence=Confidence.FULL,
        skills=[ExtractedSkill(name=s, evidence=s) for s in skills],
    )


def _dated_batch(week: date, python_count: int, other_count: int, offset: int = 0):
    """Build postings for one week, some mentioning Python and some not."""
    requirements, dates = [], {}
    index = offset
    for _ in range(python_count):
        pid = f"p{index}"
        requirements.append(_req(pid, ["Python"]))
        dates[pid] = week
        index += 1
    for _ in range(other_count):
        pid = f"p{index}"
        requirements.append(_req(pid, ["Excel"]))
        dates[pid] = week
        index += 1
    return requirements, dates, index


def test_bootstrap_uses_share_so_survivorship_does_not_invent_a_trend():
    """Older postings get delisted, so raw counts always slope upward toward
    the present. Share must stay flat when the underlying proportion does."""
    weeks = [date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 17), date(2026, 8, 24)]
    # Half the postings mention Python every week, but the surviving volume
    # doubles each week as we approach the present.
    volumes = [10, 20, 40, 80]

    requirements, dates, index = [], {}, 0
    for week, volume in zip(weeks, volumes, strict=True):
        batch, batch_dates, index = _dated_batch(week, volume // 2, volume // 2, index)
        requirements.extend(batch)
        dates.update(batch_dates)

    series = bootstrap_series_from_posting_dates(requirements, dates)

    # Raw counts would be 5, 10, 20, 40 and look like explosive growth.
    assert sorted(series["Python"].values()) == [50, 50, 50, 50]


def test_bootstrap_detects_a_genuine_change_in_share():
    weeks = [date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 17), date(2026, 8, 24)]
    shares = [(2, 18), (5, 15), (10, 10), (16, 4)]

    requirements, dates, index = [], {}, 0
    for week, (with_python, without) in zip(weeks, shares, strict=True):
        batch, batch_dates, index = _dated_batch(week, with_python, without, index)
        requirements.extend(batch)
        dates.update(batch_dates)

    series = bootstrap_series_from_posting_dates(requirements, dates)
    ordered = [series["Python"][w] for w in sorted(series["Python"])]

    assert ordered == [10, 25, 50, 80]


def test_bootstrap_drops_weeks_with_too_few_postings():
    """Two postings in a week makes every skill either 0 or 50 percent."""
    requirements, dates, index = _dated_batch(date(2026, 8, 3), 1, 1, 0)
    batch, batch_dates, _ = _dated_batch(date(2026, 8, 10), 10, 10, index)
    requirements.extend(batch)
    dates.update(batch_dates)

    series = bootstrap_series_from_posting_dates(requirements, dates)

    assert date(2026, 8, 3) not in series.get("Python", {})
    assert date(2026, 8, 10) in series["Python"]


def test_bootstrap_ignores_postings_with_no_date():
    requirements = [_req("a", ["Python"]), _req("b", ["Python"])]
    dates = {"a": None, "b": None}

    assert bootstrap_series_from_posting_dates(requirements, dates) == {}


def test_bootstrap_report_runs_without_snapshots():
    weeks = [date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 17), date(2026, 8, 24)]
    requirements, dates, index = [], {}, 0
    for week in weeks:
        batch, batch_dates, index = _dated_batch(week, 8, 8, index)
        requirements.extend(batch)
        dates.update(batch_dates)

    report = build_bootstrap_report(requirements, dates)

    assert report.skills
    assert any(s.skill == "Python" for s in report.skills)


# ---------------------------------------------------------------------------
# Degrading without Prophet
# ---------------------------------------------------------------------------


def test_missing_prophet_falls_back_to_a_linear_trend(monkeypatch):
    """Prophet has a compiled backend and does not install cleanly everywhere.
    That must not mean the agent stops producing forecasts."""
    monkeypatch.setattr("agents.forecasting._load_prophet", lambda: None)

    rising = _weekly([2, 3, 4, 5, 6, 7, 8, 9])
    result = forecast_skill("Python", rising)

    assert result.trend is Trend.RISING
    assert result.method == "linear"
    assert result.forecast_weekly_rate is not None
    assert "prophet not installed" in result.note


def test_linear_fallback_detects_a_decline(monkeypatch):
    monkeypatch.setattr("agents.forecasting._load_prophet", lambda: None)

    falling = _weekly([12, 11, 9, 8, 6, 5, 3, 2])
    result = forecast_skill("Hadoop", falling)

    assert result.trend is Trend.FALLING
    assert result.forecast_weekly_rate < result.current_weekly_rate


def test_linear_fallback_never_projects_below_zero(monkeypatch):
    monkeypatch.setattr("agents.forecasting._load_prophet", lambda: None)

    steep = _weekly([20, 16, 12, 9, 6, 4, 2, 1])
    result = forecast_skill("Luigi", steep)

    assert result.forecast_weekly_rate >= 0


def test_prophet_results_are_labelled_as_such():
    result = forecast_skill(
        "Python", _weekly([2, 3, 4, 5, 6, 7, 8, 9]), prophet_cls=_prophet_returning(12.0)
    )

    assert result.method == "prophet"
    assert "prophet not installed" not in result.note


# ---------------------------------------------------------------------------
# Regressions from the first live bootstrap run
# ---------------------------------------------------------------------------


def test_reconstructed_history_is_not_zero_filled(monkeypatch):
    """The first live run dropped sixteen thin weeks, then zero filling put
    them back as zeros, turning ten real measurements into thirty five weeks
    of mostly invented zeros. A missing reconstructed week is unmeasured, not
    evidence of no demand."""
    monkeypatch.setattr("agents.forecasting._load_prophet", lambda: None)

    # Ten measured weeks spread across a long span with gaps between them.
    measured = {MONDAY + timedelta(weeks=i * 3): 40 for i in range(10)}

    report = build_report_from_series(
        {"Python": measured}, zero_fill=False, rate_unit="% of postings"
    )
    python = report.skills[0]

    assert python.weeks_observed == 10
    assert python.trend is Trend.STABLE


def test_zero_filling_is_still_applied_to_recorded_snapshots(monkeypatch):
    """For real weekly runs a skill that vanished genuinely had no demand, so
    the gap must be filled or a decline would be interpolated away."""
    monkeypatch.setattr("agents.forecasting._load_prophet", lambda: None)

    sparse = {MONDAY: 10, MONDAY + timedelta(weeks=9): 10}
    result = forecast_skill("Hadoop", sparse)

    assert result.weeks_observed == 10


def test_the_week_in_progress_is_excluded_from_reconstruction(monkeypatch):
    """A Monday run sees only a day of postings for the current week, so most
    skills look as though they have collapsed. That week must be left out."""
    this_week = week_starting(date(2026, 9, 21))
    monkeypatch.setattr("agents.forecasting.today", lambda: date(2026, 9, 21))

    requirements, dates, index = [], {}, 0
    for offset in range(1, 5):
        batch, batch_dates, index = _dated_batch(
            this_week - timedelta(weeks=offset), 10, 10, index
        )
        requirements.extend(batch)
        dates.update(batch_dates)
    # A full sized but in progress week that would otherwise dominate.
    batch, batch_dates, index = _dated_batch(this_week, 0, 20, index)
    requirements.extend(batch)
    dates.update(batch_dates)

    series = bootstrap_series_from_posting_dates(requirements, dates)

    assert this_week not in series["Python"]


def test_growth_from_a_zero_baseline_is_not_reported_as_a_percentage():
    """The first live run listed eight skills as '+100%, now 0.0 per week'. A
    skill at zero cannot rise by a hundred percent in any meaningful sense."""
    trend, change = classify_trend(0, 5)

    assert change == 0.0
    assert trend is Trend.RISING


def test_negligible_projection_from_zero_is_stable_not_rising():
    trend, _ = classify_trend(0, 0.5)
    assert trend is Trend.STABLE


def test_baseline_uses_a_trailing_mean_not_a_single_week(monkeypatch):
    """One quiet week at the end must not decide the trend on its own."""
    monkeypatch.setattr("agents.forecasting._load_prophet", lambda: None)

    steady_then_dip = _weekly([10, 10, 10, 10, 10, 10, 10, 1])
    result = forecast_skill("SQL", steady_then_dip)

    # The single latest week is 1, but the baseline averages the last three.
    assert result.current_weekly_rate == pytest.approx(7.0)


def test_bootstrap_report_is_labelled_as_a_share():
    """A share of twelve percent must not read as twelve postings a week."""
    weeks = [date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 17), date(2026, 8, 24)]
    requirements, dates, index = [], {}, 0
    for week in weeks:
        batch, batch_dates, index = _dated_batch(week, 8, 8, index)
        requirements.extend(batch)
        dates.update(batch_dates)

    report = build_bootstrap_report(requirements, dates)

    assert report.rate_unit == "% of postings"


# ---------------------------------------------------------------------------
# Regressions from the second live bootstrap run
# ---------------------------------------------------------------------------


def test_share_mode_noise_guard_counts_postings_not_percentages(monkeypatch):
    """Kubernetes appeared as '+155%, now 3% of postings'. Eight weeks at three
    percent sums to twenty four, which passed a five mention guard while
    resting on roughly one real posting a week."""
    monkeypatch.setattr("agents.forecasting._load_prophet", lambda: None)

    shares = _weekly([2, 2, 3, 3, 3, 4, 5, 6])
    result = forecast_skill("Kubernetes", shares, raw_total=9, share_mode=True)

    assert result.trend is Trend.INSUFFICIENT_HISTORY
    assert result.total_mentions == 9
    assert "postings mention it" in result.note


def test_share_mode_accepts_a_skill_with_enough_real_postings(monkeypatch):
    monkeypatch.setattr("agents.forecasting._load_prophet", lambda: None)

    shares = _weekly([20, 22, 24, 26, 28, 30, 32, 34])
    result = forecast_skill("Python", shares, raw_total=200, share_mode=True)

    assert result.trend is Trend.RISING


def test_share_trends_are_classified_by_points_not_relative_change():
    """Three percent to five percent is a sixty seven percent relative rise but
    only two points, which is one listing's worth of movement."""
    trend, points = classify_share_trend(3.0, 5.0)

    assert trend is Trend.STABLE
    assert points == 2.0


def test_a_genuine_share_shift_is_still_detected():
    trend, points = classify_share_trend(20.0, 26.0)
    assert trend is Trend.RISING
    assert points == 6.0


def test_change_points_is_reported_alongside_the_percentage(monkeypatch):
    monkeypatch.setattr("agents.forecasting._load_prophet", lambda: None)

    result = forecast_skill(
        "Python", _weekly([20, 22, 24, 26, 28, 30, 32, 34]), raw_total=200, share_mode=True
    )

    assert result.change_points is not None
    assert result.change_points > 0


# ---------------------------------------------------------------------------
# Regressions from the third live bootstrap run
# ---------------------------------------------------------------------------


def test_weeks_older_than_the_window_are_ignored():
    """A January week survived into a September run and dragged every trend
    toward its unrepresentative skill mix. Long surviving postings are the
    roles nobody could fill, not a random sample of their week."""
    requirements, dates, index = [], {}, 0
    stale_week = date(2026, 1, 26)
    batch, batch_dates, index = _dated_batch(stale_week, 18, 2, index)
    requirements.extend(batch)
    dates.update(batch_dates)
    for offset in range(1, 9):
        batch, batch_dates, index = _dated_batch(
            FIXED_TODAY - timedelta(weeks=offset), 8, 12, index
        )
        requirements.extend(batch)
        dates.update(batch_dates)

    series = bootstrap_series_from_posting_dates(requirements, dates)

    assert week_starting(stale_week) not in series["Python"]
    assert len(series["Python"]) == 8


def test_linear_projection_uses_elapsed_time_not_list_position(monkeypatch):
    """Two points eight weeks apart must not be treated as neighbours. A share
    that moved four points over eight weeks is half a point a week, not four."""
    monkeypatch.setattr("agents.forecasting._load_prophet", lambda: None)

    spaced = {MONDAY: 30, MONDAY + timedelta(weeks=8): 34}
    projected = forecast_skill("Python", spaced, zero_fill=False, share_mode=True, raw_total=100)

    # Half a point a week over a four week horizon lands near 36, not near 50.
    assert projected.forecast_weekly_rate is None or projected.forecast_weekly_rate < 40


def test_a_stable_recent_window_is_not_reported_as_collapsing(monkeypatch):
    """The third live run showed Python falling twenty points in a month. With
    the stale week removed a steady recent share must read as stable."""
    monkeypatch.setattr("agents.forecasting._load_prophet", lambda: None)

    requirements, dates, index = [], {}, 0
    for offset in range(1, 9):
        batch, batch_dates, index = _dated_batch(
            FIXED_TODAY - timedelta(weeks=offset), 8, 12, index
        )
        requirements.extend(batch)
        dates.update(batch_dates)
    # The stale week that caused the false collapse.
    batch, batch_dates, index = _dated_batch(date(2026, 1, 26), 18, 2, index)
    requirements.extend(batch)
    dates.update(batch_dates)

    report = build_bootstrap_report(requirements, dates)
    python = next(s for s in report.skills if s.skill == "Python")

    assert python.trend is Trend.STABLE


# ---------------------------------------------------------------------------
# Regressions from the fourth live bootstrap run
# ---------------------------------------------------------------------------


def _mixed_req(pid: str, skills: list[str], confidence: Confidence) -> Requirements:
    return Requirements(
        posting_id=pid,
        source="reed" if confidence is Confidence.FULL else "adzuna",
        confidence=confidence,
        skills=[ExtractedSkill(name=s, evidence=s) for s in skills],
    )


def test_excerpt_postings_are_excluded_from_the_share():
    """Excerpts yield one or two skills where a full description yields many.
    A week heavy with excerpts would show every skill falling together."""
    week = FIXED_TODAY - timedelta(weeks=2)
    requirements, dates = [], {}
    for i in range(10):
        requirements.append(_mixed_req(f"f{i}", ["Python", "SQL"], Confidence.FULL))
        dates[f"f{i}"] = week
    for i in range(30):
        requirements.append(_mixed_req(f"a{i}", ["Excel"], Confidence.PARTIAL))
        dates[f"a{i}"] = week

    series = bootstrap_series_from_posting_dates(requirements, dates)

    # Computed over the ten full postings only, not all forty.
    assert series["Python"][week_starting(week)] == 100
    assert "Excel" not in series


def test_a_shifting_mix_of_excerpts_does_not_move_every_skill(monkeypatch):
    """The fourth run showed every skill rising by ten to eighteen points. The
    skill mix of the full postings was steady; only the excerpt share changed."""
    monkeypatch.setattr("agents.forecasting._load_prophet", lambda: None)

    requirements, dates, index = [], {}, 0
    for offset in range(8, 0, -1):
        week = FIXED_TODAY - timedelta(weeks=offset)
        for i in range(12):
            pid = f"f{index}"; index += 1
            skills = ["Python", "SQL"] if i < 6 else ["Excel"]
            requirements.append(_mixed_req(pid, skills, Confidence.FULL))
            dates[pid] = week
        # Excerpt volume falls away toward the present.
        for _ in range(offset * 4):
            pid = f"a{index}"; index += 1
            requirements.append(_mixed_req(pid, [], Confidence.PARTIAL))
            dates[pid] = week

    report = build_bootstrap_report(requirements, dates)
    python = next(s for s in report.skills if s.skill == "Python")

    assert python.trend is Trend.STABLE


def test_uniform_movement_is_flagged_as_a_likely_artefact():
    skills = [
        SkillDemand(skill=f"S{i}", total_mentions=100, weeks_observed=8,
                    current_weekly_rate=10.0, trend=Trend.RISING)
        for i in range(9)
    ] + [
        SkillDemand(skill="Z", total_mentions=100, weeks_observed=8,
                    current_weekly_rate=10.0, trend=Trend.FALLING)
    ]

    report = DemandReport(generated_for_week=FIXED_TODAY, skills=skills)

    assert report.uniform_movement is Trend.RISING


def test_mixed_movement_is_not_flagged():
    skills = [
        SkillDemand(skill=f"R{i}", total_mentions=100, weeks_observed=8,
                    current_weekly_rate=10.0, trend=Trend.RISING)
        for i in range(4)
    ] + [
        SkillDemand(skill=f"F{i}", total_mentions=100, weeks_observed=8,
                    current_weekly_rate=10.0, trend=Trend.FALLING)
        for i in range(4)
    ]

    report = DemandReport(generated_for_week=FIXED_TODAY, skills=skills)

    assert report.uniform_movement is None


def test_too_few_trends_to_judge_uniformity():
    skills = [
        SkillDemand(skill="A", total_mentions=100, weeks_observed=8,
                    current_weekly_rate=10.0, trend=Trend.RISING),
        SkillDemand(skill="B", total_mentions=100, weeks_observed=8,
                    current_weekly_rate=10.0, trend=Trend.RISING),
    ]
    assert DemandReport(generated_for_week=FIXED_TODAY, skills=skills).uniform_movement is None
