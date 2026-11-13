"""Anniversary math without a database or external services."""
from datetime import datetime, timedelta

import pytest

from app import membership, payments


@pytest.mark.parametrize('day', [28, 29, 30, 31])
def test_short_month_clamps_without_drifting(day):
    # UTC 16:30 on Jan (day - 1) is Beijing Jan (day), 00:30.
    anchor = datetime(2026, 1, day - 1, 16, 30, 0, 123456)
    february = datetime(2026, 2, 27, 16, 30, 0, 123456)
    march = datetime(2026, 3, day - 1, 16, 30, 0, 123456)
    _, start, end = membership.period(anchor, february)
    assert start == february and end == march
    assert membership.period(anchor, march)[1] == march
    assert membership.period(anchor, february - timedelta(microseconds=1))[1] == anchor


def test_leap_year_and_fixed_time():
    anchor = datetime(2028, 1, 31, 6, 45)
    assert membership.period(anchor, datetime(2028, 2, 29, 6, 44, 59))[1] == anchor
    assert membership.period(anchor, datetime(2028, 2, 29, 6, 45))[1:] == (
        datetime(2028, 2, 29, 6, 45), datetime(2028, 3, 31, 6, 45))
    leap_day = datetime(2028, 2, 29, 4)
    assert membership.period(leap_day, datetime(2029, 2, 28, 4))[1:] == (
        datetime(2029, 2, 28, 4), datetime(2029, 3, 29, 4))


def test_beijing_year_boundary():
    anchor = datetime(2026, 12, 31, 16)  # Beijing Jan 1, not Dec 31.
    assert membership.period(anchor, datetime(2027, 1, 31, 16))[1:] == (
        datetime(2027, 1, 31, 16), datetime(2027, 2, 28, 16))


def test_month_end_renewal_retains_original_anniversary():
    start = datetime(2026, 1, 31, 4)
    active = dict(plan_code='monthly', starts_at=start, expires_at=datetime(2026, 2, 28, 4))
    kind, expiry = payments.outcome(active, 'monthly', 1, datetime(2026, 2, 10))
    assert kind == 'renew' and expiry == datetime(2026, 3, 31, 4)
    active['expires_at'] = expiry
    assert payments.outcome(active, 'monthly', 1, datetime(2026, 2, 10))[1] == datetime(2026, 4, 30, 4)


def test_renewal_preserves_upgrade_remainder():
    start, expiry = datetime(2026, 11, 20, 4), datetime(2028, 1, 7, 5)
    assert membership.renewal_expiry(start, expiry, 12) == membership.months_after(expiry, 12)
