"""Resident-facing overview: monthly summary, trends and where the money goes."""
import pandas as pd
import streamlit as st

from condo import categories, charts, loader, metrics
from condo.data import (
    ACCOUNT_LABELS,
    brl,
    brl_compact,
    brl_signed,
    get_category_map,
    get_dataset,
    month_label,
    month_short,
    pct,
    theme_mode,
)

ALL = "todas"
ACCOUNT_OPTIONS = {
    ALL: "Todas as contas",
    "PRI": "Principal",
    "FO": "Fundo de obras",
    "FR": "Fundo de reserva",
}
MISSING = "sem extrato"

st.title("Visão geral")

data = get_dataset()
if not data.months:
    st.info("Ainda não há extratos carregados.")
    st.stop()

st.caption(f"Extratos disponíveis: {month_label(data.months[0])} a {month_label(data.months[-1])}.")
gaps = loader.missing_months(data.months)
if gaps:
    runs: list[list[pd.Period]] = []
    for m in gaps:
        if runs and m == runs[-1][-1] + 1:
            runs[-1].append(m)
        else:
            runs.append([m])
    text = ", ".join(
        month_label(r[0]) if len(r) == 1 else f"{month_label(r[0])} a {month_label(r[-1])}" for r in runs
    )
    st.caption(
        f"Sem extrato: {text}. Esses meses aparecem vazios nos gráficos, "
        "o que não significa que o valor foi zero."
    )

# --- Filters: one row, scoping everything below -----------------------------
col_conta, col_mes = st.columns([3, 2], vertical_alignment="bottom")
with col_conta:
    conta = st.segmented_control(
        "Conta",
        options=list(ACCOUNT_OPTIONS),
        format_func=ACCOUNT_OPTIONS.get,
        default=ALL,
        required=True,
        help="A conta principal paga o dia a dia. Os fundos de obras e de reserva "
        "guardam dinheiro para reformas e emergências.",
    )
with col_mes:
    mes = st.selectbox(
        "Mês",
        options=[*data.months[::-1], None],
        format_func=lambda m: "Todos os meses" if m is None else month_label(m),
    )
contas = list(ACCOUNT_LABELS) if conta == ALL else [conta]
mode = theme_mode()

summary = metrics.monthly_summary(data, contas)
by_month = summary.set_index("mes")

# --- Headline numbers -------------------------------------------------------
ACCOUNT_HELP = {
    "PRI": "Recebe as taxas de condomínio e paga as despesas do dia a dia.",
    "FO": "Dinheiro guardado para obras e reformas do prédio.",
    "FR": "Reserva para emergências e despesas imprevistas.",
}
NO_PREVIOUS = "Não há extrato do mês anterior para comparar."


def _tiles(items: list[tuple], compare_note: str | None, help_by_label: dict | None = None) -> None:
    """items: (label, value, delta or None/NaN, delta_color)."""
    help_by_label = help_by_label or {}
    for col, (label, value, delta, color) in zip(st.columns(len(items)), items):
        has_delta = delta is not None and not pd.isna(delta)
        hint = help_by_label.get(label)
        if compare_note is None and mes is not None:
            hint = f"{hint} {NO_PREVIOUS}" if hint else NO_PREVIOUS
        with col:
            st.metric(
                label,
                brl(value),
                delta=brl_signed(delta) if has_delta else None,
                delta_color=color,
                delta_description=compare_note if has_delta else None,
                border=True,
                help=hint,
            )


# Balances use the selected month, or the latest one when showing all months.
ref = data.months[-1] if mes is None else mes
prev = ref - 1
has_prev = prev in data.months
compare_note = f"vs {month_label(prev)}" if has_prev else None

st.subheader(f"Saldo das contas no fim de {month_label(ref)}")
balance_tiles = []
for acc, label in ACCOUNT_LABELS.items():
    row = metrics.monthly_summary(data, [acc]).set_index("mes").loc[ref]
    balance_tiles.append((label, row["saldo_final"], row["var_saldo_final"], "normal"))
_tiles(
    balance_tiles,
    compare_note,
    {ACCOUNT_LABELS[a]: h for a, h in ACCOUNT_HELP.items()},
)

scope = "" if conta == ALL else f" · {ACCOUNT_OPTIONS[conta]}"
result_help = (
    "Receitas menos despesas. Positivo: entrou mais dinheiro do que saiu. "
    "Negativo: gastou-se mais do que entrou."
)
if mes is None:
    present = summary[summary["tem_extrato"]]
    st.subheader(f"Entradas e saídas em todos os meses com extrato{scope}")
    _tiles(
        [
            ("Receitas", present["receitas"].sum(), None, "normal"),
            ("Despesas", present["despesas"].sum(), None, "inverse"),
            ("Saldo do período", present["resultado"].sum(), None, "normal"),
        ],
        None,
        {"Saldo do período": result_help},
    )
else:
    row = by_month.loc[mes]
    st.subheader(f"Entradas e saídas de {month_label(mes)}{scope}")
    _tiles(
        [
            ("Receitas", row["receitas"], row["var_receitas"], "normal"),
            ("Despesas", row["despesas"], row["var_despesas"], "inverse"),  # spending more is bad
            ("Saldo do mês", row["resultado"], row["var_resultado"], "normal"),
        ],
        compare_note,
        {"Saldo do mês": result_help},
    )

# --- Month over month -------------------------------------------------------
st.subheader("Mês a mês")
labels = [month_short(m) for m in summary["mes"]]


def _money_or_missing(value) -> str:
    return MISSING if pd.isna(value) else brl(value)


def _change(value) -> str:
    return "mês anterior sem extrato" if pd.isna(value) else brl_signed(value)


flows = []
for r in summary.itertuples():
    for serie, valor, var in [
        ("Receitas", r.receitas, r.var_receitas),
        ("Despesas", r.despesas, r.var_despesas),
    ]:
        flows.append(
            {
                "rotulo": month_short(r.mes),
                "mes_nome": month_label(r.mes),
                "serie": serie,
                "valor": valor,
                "receitas_txt": _money_or_missing(r.receitas),
                "despesas_txt": _money_or_missing(r.despesas),
                "resultado_txt": _money_or_missing(r.resultado),
                "var_txt": f"{serie}: {_change(var)}",
            }
        )
st.markdown("**Receitas e despesas**")
st.altair_chart(charts.income_expenses(pd.DataFrame(flows), labels, mode), width="stretch")

bal = summary.assign(trecho=(~summary["tem_extrato"]).cumsum())
bal = bal[bal["tem_extrato"]]
bal_rows = pd.DataFrame(
    {
        "rotulo": [month_short(m) for m in bal["mes"]],
        "mes_nome": [month_label(m) for m in bal["mes"]],
        "valor": bal["saldo_final"].to_numpy(),
        "trecho": bal["trecho"].to_numpy(),
        "valor_txt": [brl(v) for v in bal["saldo_final"]],
        "var_txt": [_change(v) for v in bal["var_saldo_final"]],
        "ultimo": [False] * (len(bal) - 1) + [True],
    }
)
st.markdown("**Saldo no fim de cada mês**")
st.altair_chart(charts.balance_line(bal_rows, labels, mode), width="stretch")

with st.expander("Ver os números em tabela"):
    st.dataframe(
        pd.DataFrame(
            {
                "Mês": [month_label(m) for m in summary["mes"]],
                "Receitas": summary["receitas"].map(_money_or_missing),
                "Despesas": summary["despesas"].map(_money_or_missing),
                "Resultado": summary["resultado"].map(_money_or_missing),
                "Saldo no fim do mês": summary["saldo_final"].map(_money_or_missing),
            }
        ).iloc[::-1],
        hide_index=True,
        width="stretch",
    )
    if conta in (ALL, "PRI") and "913" in set(data.transactions["taxa"]):
        st.caption(
            "O repasse do saldo da administradora anterior (abr/2025) não é contado "
            "como receita, pois é dinheiro que já era do condomínio. Ele aparece no saldo."
        )

# --- Where the money goes ---------------------------------------------------
periodo = data.months if mes is None else [mes]
st.subheader(
    "Para onde vai o dinheiro"
    + (" (todos os meses com extrato)" if mes is None else f" em {month_label(mes)}")
)
category_map = get_category_map()
cats = metrics.expenses_by_category(data, contas, periodo, category_map)
if cats.empty:
    st.info("Não houve despesas nesta conta no período.")
else:
    cat_rows = cats.assign(
        rotulo_valor=cats["valor"].map(brl),
        share_txt=cats["share"].map(pct),
        rotulo_tip=[f"{brl_compact(v)} · {pct(s)}" for v, s in zip(cats["valor"], cats["share"])],
        descricao=cats["categoria"].map(categories.CATEGORY_DESCRIPTIONS),
    )
    st.altair_chart(charts.categories_bars(cat_rows, mode), width="stretch")
    with st.expander("O que entra em cada categoria"):
        st.dataframe(
            pd.DataFrame(
                {
                    "Categoria": cat_rows["categoria"],
                    "Total": cat_rows["rotulo_valor"],
                    "Parte": cat_rows["share_txt"],
                    "Inclui": cat_rows["descricao"],
                }
            ),
            hide_index=True,
            width="stretch",
        )

# --- Entries ----------------------------------------------------------------
st.subheader("Lançamentos" + ("" if mes is None else f" de {month_label(mes)}"))
tx = data.transactions[data.transactions["conta"].isin(contas) & data.transactions["mes"].isin(periodo)]
tx = tx.sort_values("data", ascending=False, kind="stable")
st.dataframe(
    pd.DataFrame(
        {
            "Data": tx["data"].dt.strftime("%d/%m/%Y"),
            "Conta": tx["conta"].map(ACCOUNT_LABELS),
            "Categoria": categories.expense_category(tx["taxa"], category_map)
            .where(tx["valor"] < 0, "Receita")
            .mask(tx["taxa"].isin(categories.TRANSFER_CODES), "Transferência"),
            "Descrição": tx["descricao"],
            "Valor": tx["valor"].map(brl),
        }
    ),
    hide_index=True,
    width="stretch",
)
