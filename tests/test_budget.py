from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import Mock
import pytest
from automation_pipeline.budget import LocalBudget, GitHubBudget, month, estimate, money
from automation_pipeline.integrations.github import Conflict


def test_concurrent_reservations(tmp_path):
    ledger = LocalBudget(tmp_path / "budget.sqlite")
    ledger.initialize(month(), "0")

    def reserve(_):
        try:
            ledger.reserve(Decimal("0.6"), Decimal("1.0"))
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(8))) == 1


def test_missing_month_and_no_reinitialization(tmp_path):
    ledger = LocalBudget(tmp_path / "budget.sqlite")
    with pytest.raises(ValueError, match="Initialize"):
        ledger.reserve("0.1", "1")
    ledger.initialize(month(), "0.5")
    with pytest.raises(Exception):
        ledger.initialize(month(), "0")
    with pytest.raises(ValueError, match="exhausted"):
        ledger.reserve("0.6", "1")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "invalid"])
def test_invalid_money(value):
    with pytest.raises(ValueError):
        money(value)


def test_github_conflict_reloads():
    store = Mock()
    store.get.side_effect = [
        ({"reserved_usd": "0", "reservations": []}, "a"),
        ({"reserved_usd": "0.6", "reservations": []}, "b"),
    ]
    store.put.side_effect = Conflict("race")
    with pytest.raises(ValueError, match="exhausted"):
        GitHubBudget(store).reserve("0.6", "1")
    assert store.get.call_count == 2


def test_explicit_profile_required():
    with pytest.raises(ValueError, match="disabled"):
        estimate({"model": "model"}, {})
