"""Parse the administrator's monthly statement workbooks into DataFrames.

Pure pandas, no Streamlit, so it can be tested and reused by the upload flow.
Amounts are signed: credits (money in) are positive, debits (money out) negative.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterable, Union

import pandas as pd

ACCOUNT_SHEETS = {"Conta PRI": "PRI", "Conta FO": "FO", "Conta FR": "FR"}
FUTURE_SHEET = "Lancamentos futuros"
ACCOUNT_COLUMNS = ["Dia", "Taxa", "Descrição", "Débito", "Crédito"]
OPENING = "Saldo Mes Anterior"
CLOSING = "Saldo Final"
EXCEL_EPOCH = pd.Timestamp("1899-12-30")
TOLERANCE = 0.005

Source = Union[str, Path, IO[bytes]]


class StatementError(ValueError):
    """The workbook does not look like a valid statement."""


@dataclass
class Statement:
    month: pd.Period
    transactions: pd.DataFrame  # conta, data, taxa, descricao, valor
    balances: pd.DataFrame  # conta, saldo_inicial, saldo_final
    future: pd.DataFrame  # conta, vencimento, descricao, valor


@dataclass
class Dataset:
    transactions: pd.DataFrame  # + mes
    balances: pd.DataFrame  # + mes
    future: pd.DataFrame  # from the most recent statement only
    months: list[pd.Period]


def _with_header(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.iloc[1:].dropna(how="all").copy()  # sheets contain blank spacer rows
    df.columns = [str(c).strip() for c in raw.iloc[0]]
    return df


def _excel_date(value) -> pd.Timestamp:
    # openpyxl returns datetimes for date-formatted cells, plain serials otherwise.
    if pd.isna(value):
        return pd.NaT
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return EXCEL_EPOCH + pd.Timedelta(days=float(value))
    return pd.Timestamp(value)


def _excel_dates(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values.map(_excel_date))


def _signed_amount(df: pd.DataFrame) -> pd.Series:
    credit = pd.to_numeric(df["Crédito"], errors="coerce").fillna(0.0)
    debit = pd.to_numeric(df["Débito"], errors="coerce").fillna(0.0)
    return (credit - debit).round(2)


def _parse_account(raw: pd.DataFrame, conta: str) -> tuple[pd.DataFrame, float, float]:
    df = raw
    missing = [c for c in ACCOUNT_COLUMNS if c not in df.columns]
    if missing:
        raise StatementError(f"Aba da conta {conta} sem as colunas: {', '.join(missing)}")

    desc = df["Descrição"].astype(str).str.strip()
    valor = _signed_amount(df)

    is_close = desc == CLOSING
    if is_close.sum() != 1 or not is_close.iloc[-1]:
        raise StatementError(f"Conta {conta}: a última linha deveria ser '{CLOSING}'.")
    is_open = desc == OPENING
    # Opening row can be missing (e.g. the first month of a fund) and can be a debit
    # when the balance is negative, hence the signed amount.
    opening = float(valor[is_open].sum())
    closing = float(valor[is_close].iloc[0])

    body = df[~is_open & ~is_close]
    tx = pd.DataFrame(
        {
            "conta": conta,
            "data": _excel_dates(body["Dia"]),
            "taxa": body["Taxa"].astype(str).str.strip(),
            "descricao": body["Descrição"].astype(str).str.strip(),
            "valor": valor[body.index],
        }
    ).reset_index(drop=True)

    diff = opening + tx["valor"].sum() - closing
    if abs(diff) > TOLERANCE:
        raise StatementError(
            f"Conta {conta}: saldo inicial + lançamentos não bate com o saldo final "
            f"(diferença de {diff:.2f})."
        )
    return tx, opening, closing


def _parse_future(raw: pd.DataFrame) -> pd.DataFrame:
    """The sheet has title rows, a header starting with 'Conta', the entries,
    then a total row and a summary block. Keep only the entry rows."""
    header_rows = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "Conta"] if raw.shape[1] else []
    if len(header_rows) == 0:
        return pd.DataFrame(columns=["conta", "vencimento", "descricao", "valor"])
    start = header_rows[0]
    body = raw.loc[start + 1 :].copy()
    body.columns = [str(c).strip() for c in raw.loc[start]]
    conta = body["Conta"].astype(str).str.strip()
    body = body[conta.isin(ACCOUNT_SHEETS.values())]
    return pd.DataFrame(
        {
            "conta": body["Conta"].astype(str).str.strip(),
            "vencimento": _excel_dates(body["Data vencimento"]),
            "descricao": body["Descrição"].astype(str).str.strip(),
            "valor": _signed_amount(body),
        }
    ).reset_index(drop=True)


def load_statement(source: Source) -> Statement:
    try:
        raw_sheets = pd.read_excel(source, sheet_name=None, header=None, engine="openpyxl")
    except Exception as exc:  # openpyxl raises several unrelated types
        raise StatementError(f"Não foi possível ler a planilha: {exc}") from exc
    # Some sheet names have trailing spaces.
    raw_sheets = {name.strip(): df for name, df in raw_sheets.items()}
    sheets = {name: _with_header(df) for name, df in raw_sheets.items() if name in ACCOUNT_SHEETS}

    if "Conta PRI" not in sheets:
        raise StatementError("A planilha não tem a aba 'Conta PRI'.")

    txs, balances = [], []
    for sheet, conta in ACCOUNT_SHEETS.items():
        if sheet not in sheets:
            continue  # FO is absent in older statements
        tx, opening, closing = _parse_account(sheets[sheet], conta)
        txs.append(tx)
        balances.append({"conta": conta, "saldo_inicial": opening, "saldo_final": closing})

    # The PRI opening row is dated the 1st of the statement month.
    pri_dates = _excel_dates(sheets["Conta PRI"]["Dia"].dropna())
    if pri_dates.empty:
        raise StatementError("A aba 'Conta PRI' não tem datas.")
    month = pri_dates.min().to_period("M")

    future = _parse_future(raw_sheets.get(FUTURE_SHEET, pd.DataFrame()))

    return Statement(
        month=month,
        transactions=pd.concat(txs, ignore_index=True),
        balances=pd.DataFrame(balances),
        future=future,
    )


def load_all(sources: Iterable[Source]) -> Dataset:
    statements = [load_statement(s) for s in sources]
    if not statements:
        empty = pd.DataFrame()
        return Dataset(empty, empty, empty, [])

    by_month: dict[pd.Period, Statement] = {}
    for s in statements:
        if s.month in by_month:
            raise StatementError(f"Há mais de um extrato para {s.month}.")
        by_month[s.month] = s
    months = sorted(by_month)

    return Dataset(
        transactions=pd.concat(
            [by_month[m].transactions.assign(mes=m) for m in months], ignore_index=True
        ),
        balances=pd.concat(
            [by_month[m].balances.assign(mes=m) for m in months], ignore_index=True
        ),
        # Every export repeats the same "future entries" snapshot taken at download
        # time, so only the latest one is meaningful.
        future=by_month[months[-1]].future,
        months=months,
    )


def missing_months(months: list[pd.Period]) -> list[pd.Period]:
    if not months:
        return []
    present = set(months)
    full = pd.period_range(min(months), max(months), freq="M")
    return [m for m in full if m not in present]
