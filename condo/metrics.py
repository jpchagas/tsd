"""Monthly figures for the dashboard. Pure pandas, so it is testable.

Months without a statement are kept as rows with NaN, never zero: the charts
show them as gaps and the changes next to them are left undefined.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from condo import categories
from condo.loader import Dataset


def monthly_summary(data: Dataset, contas: Iterable[str]) -> pd.DataFrame:
    """One row per month from first to last statement:
    mes, tem_extrato, receitas, despesas, resultado, saldo_final
    plus var_<col> (change vs the previous month; NaN if either month is missing).
    `despesas` is positive (an amount spent)."""
    contas = list(contas)
    full = pd.period_range(min(data.months), max(data.months), freq="M")

    tx = data.transactions[data.transactions["conta"].isin(contas)]
    tx = tx[~tx["taxa"].isin(categories.TRANSFER_CODES)]
    flows = tx.groupby("mes")["valor"].agg(
        receitas=lambda v: v[v > 0].sum(),
        despesas=lambda v: -v[v < 0].sum(),
    )
    bal = data.balances[data.balances["conta"].isin(contas)]
    saldo = bal.groupby("mes")["saldo_final"].sum()

    out = pd.DataFrame(index=pd.Index(full, name="mes"))
    out["tem_extrato"] = out.index.isin(data.months)
    out = out.join(flows).join(saldo)
    present = out["tem_extrato"]
    # A month with a statement but no movement in these accounts is a real zero.
    out.loc[present, ["receitas", "despesas"]] = out.loc[present, ["receitas", "despesas"]].fillna(0.0)
    out.loc[present, "saldo_final"] = out.loc[present, "saldo_final"].fillna(0.0)
    out["resultado"] = out["receitas"] - out["despesas"]
    for col in ["receitas", "despesas", "resultado", "saldo_final"]:
        out[f"var_{col}"] = out[col] - out[col].shift(1)  # NaN propagates across gaps
    return out.reset_index()


def expenses_by_category(
    data: Dataset, contas: Iterable[str], meses: Iterable[pd.Period], mapping: dict[str, str] | None = None
) -> pd.DataFrame:
    """categoria, valor (positive), share; largest first. `mapping` is code -> category
    (default: categories.CODE_TO_CATEGORY)."""
    tx = data.transactions
    tx = tx[tx["conta"].isin(list(contas)) & tx["mes"].isin(list(meses)) & (tx["valor"] < 0)]
    out = (
        tx.assign(categoria=categories.expense_category(tx["taxa"], mapping), valor=-tx["valor"])
        .groupby("categoria", as_index=False)["valor"]
        .sum()
        .sort_values("valor", ascending=False, ignore_index=True)
    )
    total = out["valor"].sum()
    out["share"] = out["valor"] / total if total else 0.0
    return out
