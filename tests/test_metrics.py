from io import BytesIO

import pandas as pd
import pytest

from condo import loader, metrics, storage


@pytest.fixture(scope="module")
def data():
    store = storage.from_config(None)
    return loader.load_all(BytesIO(store.read(n)) for n in store.names())


def _row(summary, month):
    return summary.set_index("mes").loc[pd.Period(month, "M")]


def test_primary_account_october(data):
    s = metrics.monthly_summary(data, ["PRI"])
    oct_ = _row(s, "2026-10")
    assert oct_["receitas"] == pytest.approx(49865.15)
    assert oct_["despesas"] == pytest.approx(40575.95)
    assert oct_["resultado"] == pytest.approx(9289.20)
    assert oct_["saldo_final"] == pytest.approx(22078.22)
    assert oct_["var_saldo_final"] == pytest.approx(22078.22 - 12789.02)


def test_all_accounts_balance_is_the_sum(data):
    s = metrics.monthly_summary(data, ["PRI", "FO", "FR"])
    assert _row(s, "2026-10")["saldo_final"] == pytest.approx(22078.22 + 64361.32 + 65548.33)


def test_gap_months_are_nan_not_zero(data):
    s = metrics.monthly_summary(data, ["PRI"])
    assert len(s) == 19  # abr/2025 .. out/2026
    gap = _row(s, "2025-08")
    assert not gap["tem_extrato"]
    assert pd.isna(gap["receitas"]) and pd.isna(gap["saldo_final"])
    # The first month after the gap has no previous month to compare with.
    assert pd.isna(_row(s, "2026-01")["var_receitas"])


def test_transfer_from_previous_administrator_is_not_income(data):
    apr = _row(metrics.monthly_summary(data, ["PRI"]), "2025-04")
    assert apr["receitas"] == pytest.approx(47916.91 - 8806.57)
    assert apr["saldo_final"] == pytest.approx(11909.39)  # but it is in the balance


def test_account_absent_in_a_month_with_statement_is_zero(data):
    # The works fund (FO) did not exist yet in abr/2025.
    apr = _row(metrics.monthly_summary(data, ["FO"]), "2025-04")
    assert apr["tem_extrato"] and apr["receitas"] == 0 and apr["saldo_final"] == 0


def test_categories_add_up_to_expenses(data):
    oct_ = pd.Period("2026-10", "M")
    cats = metrics.expenses_by_category(data, ["PRI"], [oct_])
    assert cats["valor"].sum() == pytest.approx(40575.95)
    assert cats["share"].sum() == pytest.approx(1.0)
    assert cats["valor"].is_monotonic_decreasing
    assert cats.iloc[0]["categoria"] == "Portaria e serviços gerais"


def test_expenses_by_category_uses_given_mapping(data):
    oct_ = pd.Period("2026-10", "M")
    everything_is_works = {code: "Obras e reformas" for code in data.transactions["taxa"]}
    cats = metrics.expenses_by_category(data, ["PRI"], [oct_], everything_is_works)
    assert cats["categoria"].tolist() == ["Obras e reformas"]
    assert cats["valor"].sum() == pytest.approx(40575.95)
