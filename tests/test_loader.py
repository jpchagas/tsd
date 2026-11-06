from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from condo import loader, storage

DOCS = Path(__file__).resolve().parent.parent / "docs"
FILES = sorted(DOCS.glob("extrato_01487_*.xlsx"))


@pytest.fixture(scope="module")
def dataset():
    return loader.load_all(FILES)


def test_month_comes_from_content_and_matches_filename():
    for path in FILES:
        stmt = loader.load_statement(path)
        assert storage.filename_for(stmt.month) == path.name


def test_opening_and_closing_rows_are_not_transactions(dataset):
    descs = set(dataset.transactions["descricao"])
    assert loader.OPENING not in descs
    assert loader.CLOSING not in descs
    assert dataset.transactions["data"].notna().all()  # no blank spacer rows


def test_balances_chain_between_consecutive_months(dataset):
    b = dataset.balances.set_index(["mes", "conta"])
    for prev, cur in zip(dataset.months, dataset.months[1:]):
        if cur != prev + 1:
            continue
        for conta in b.loc[cur].index:
            assert b.loc[(cur, conta), "saldo_inicial"] == pytest.approx(
                b.loc[(prev, conta), "saldo_final"], abs=0.005
            )


def test_april_2025_quirks():
    stmt = loader.load_statement(DOCS / "extrato_01487_2025-04-01_2025-05-01.xlsx")
    bal = stmt.balances.set_index("conta")
    assert "FO" not in bal.index  # works fund did not exist yet
    assert bal.loc["PRI", "saldo_inicial"] == pytest.approx(-784.89)  # opening is a debit
    assert bal.loc["FR", "saldo_inicial"] == 0  # no opening row
    assert bal.loc["PRI", "saldo_final"] == pytest.approx(11909.39)


def test_known_october_2026_values():
    stmt = loader.load_statement(DOCS / "extrato_01487_2026-10-01_2026-11-01.xlsx")
    bal = stmt.balances.set_index("conta")["saldo_final"]
    assert bal.to_dict() == pytest.approx({"PRI": 22078.22, "FO": 64361.32, "FR": 65548.33})
    first = stmt.transactions.iloc[0]
    assert first["data"] == pd.Timestamp("2026-10-01")
    assert first["taxa"] == "988"
    assert first["valor"] == pytest.approx(1810.42)


def test_future_entries_exclude_total_and_summary_rows(dataset):
    fut = dataset.future
    assert len(fut) == 21
    assert set(fut["conta"]) == {"PRI"}
    assert fut["valor"].sum() == pytest.approx(-34521.3)


def test_missing_months(dataset):
    gaps = loader.missing_months(dataset.months)
    assert pd.Period("2025-05", "M") in gaps
    assert pd.Period("2025-12", "M") in gaps
    assert pd.Period("2026-01", "M") not in gaps


def test_loads_from_uploaded_bytes():
    data = FILES[-1].read_bytes()
    assert loader.load_statement(BytesIO(data)).month == pd.Period("2026-10", "M")


def test_rejects_non_statement_workbook(tmp_path):
    path = tmp_path / "x.xlsx"
    pd.DataFrame({"a": [1]}).to_excel(path, index=False)
    with pytest.raises(loader.StatementError):
        loader.load_statement(path)


def test_rejects_statement_that_does_not_reconcile(tmp_path):
    path = tmp_path / "bad.xlsx"
    rows = [
        [46296, "620", "Saldo Mes Anterior", None, 100.0],
        [46297, "988", "Condominio Ap 1 (principal)-10/2026", None, 50.0],
        [None, None, "Saldo Final", None, 999.0],
    ]
    pd.DataFrame(rows, columns=loader.ACCOUNT_COLUMNS).to_excel(
        path, sheet_name="Conta PRI", index=False
    )
    with pytest.raises(loader.StatementError, match="não bate"):
        loader.load_statement(path)


def test_duplicate_month_rejected():
    with pytest.raises(loader.StatementError):
        loader.load_all([FILES[-1], FILES[-1]])
