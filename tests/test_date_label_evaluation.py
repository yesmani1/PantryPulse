"""Provider-neutral regression evaluation for date-label safety decisions.

These deterministic cases are intentionally offline: they protect the safety
contract on every test run and do not spend provider tokens.
"""

import pytest

from pantrypulse.schemas import Category, DateType
from pantrypulse.tools.domain import classify_date_label


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("USE BY 10 Sep", DateType.USE_BY),
        ("Use By: 10/09", DateType.USE_BY),
        ("use-by 2026-09-10", DateType.USE_BY),
        ("USE BY", DateType.USE_BY),
        ("BEST BEFORE 10 Sep", DateType.BEST_BY),
        ("Best Before: 10/09", DateType.BEST_BY),
        ("BEST BY 2026-09-10", DateType.BEST_BY),
        ("best by", DateType.BEST_BY),
        ("SELL BY 10 Sep", DateType.SELL_BY),
        ("Sell By: 10/09", DateType.SELL_BY),
        ("sell-by 2026-09-10", DateType.SELL_BY),
        ("SELL BY", DateType.SELL_BY),
        ("10/09/2026", DateType.ESTIMATED),
        ("EXP 10 Sep", DateType.ESTIMATED),
        ("Date: 2026-09-10", DateType.ESTIMATED),
        ("Packed 10 Sep", DateType.ESTIMATED),
        ("Fresh until 10 Sep", DateType.ESTIMATED),
        ("", DateType.ESTIMATED),
        ("batch L123", DateType.ESTIMATED),
        ("10 SEPT", DateType.ESTIMATED),
    ],
)
def test_date_label_evaluation_cases(label: str, expected: DateType):
    assert classify_date_label(label, Category.DAIRY).date_type is expected
