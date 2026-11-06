"""Altair chart builders. Inputs are plain DataFrames from condo.metrics.

Visual rules (see the dataviz guidance this follows): one y-axis per chart (the
balance gets its own chart instead of a second axis), thin bars with 4px rounded
ends, 2px lines, >= 8px points with a ring in the surface color, hairline grid,
text in ink colors (never the series color), missing months shown as empty slots.
Colors were validated (CVD + contrast) against Streamlit's light and dark surfaces.
"""
from __future__ import annotations

import altair as alt
import pandas as pd

PALETTES = {
    "light": {
        "receitas": "#2a78d6",
        "despesas": "#eb6834",
        "surface": "#ffffff",
        "ink": "#31333f",
        "muted": "#898781",
        "baseline": "#c3c2b7",
    },
    "dark": {
        "receitas": "#3987e5",
        "despesas": "#d95926",
        "surface": "#0e1117",
        "ink": "#fafafa",
        "muted": "#898781",
        "baseline": "#383835",
    },
}
SERIES = ["Receitas", "Despesas"]

# Axis ticks as "R$ 40 mil" (Brazilian residents read thousands this way).
_THOUSANDS = (
    "datum.value == 0 ? '0' : "
    "(datum.value < 0 ? '-' : '') + 'R$ ' + format(abs(datum.value) / 1000, ',.0f') + ' mil'"
)


def _x_months(labels: list[str]) -> alt.X:
    return alt.X(
        "rotulo:N",
        sort=labels,
        scale=alt.Scale(domain=labels),  # keeps months without a statement as empty slots
        axis=alt.Axis(title=None, labelAngle=0, ticks=False, domain=False),
    )


def _y_money() -> alt.Y:
    return alt.Y("valor:Q", axis=alt.Axis(title=None, labelExpr=_THOUSANDS, tickCount=5))


def income_expenses(rows: pd.DataFrame, labels: list[str], mode: str = "light") -> alt.Chart:
    """Grouped columns per month. `rows`: rotulo, serie, valor, plus tooltip text
    columns mes_nome, receitas_txt, despesas_txt, resultado_txt, var_txt."""
    p = PALETTES[mode]
    return (
        alt.Chart(rows)
        .mark_bar(size=12, cornerRadiusEnd=4)
        .encode(
            x=_x_months(labels),
            xOffset=alt.XOffset("serie:N", sort=SERIES),
            y=_y_money(),
            color=alt.Color(
                "serie:N",
                scale=alt.Scale(domain=SERIES, range=[p["receitas"], p["despesas"]]),
                legend=alt.Legend(title=None, orient="top", direction="horizontal", symbolType="square"),
            ),
            tooltip=[
                alt.Tooltip("mes_nome:N", title="Mês"),
                alt.Tooltip("receitas_txt:N", title="Receitas"),
                alt.Tooltip("despesas_txt:N", title="Despesas"),
                alt.Tooltip("resultado_txt:N", title="Resultado"),
                alt.Tooltip("var_txt:N", title="Variação vs mês anterior"),
            ],
        )
        .properties(height=300)
    )


def balance_line(rows: pd.DataFrame, labels: list[str], mode: str = "light") -> alt.LayerChart:
    """Closing balance per month. `rows`: rotulo, valor, trecho (consecutive-month run,
    so the line breaks at gaps), valor_txt, var_txt, mes_nome. Only months with data."""
    p = PALETTES[mode]
    base = alt.Chart(rows).encode(x=_x_months(labels), y=_y_money())
    tooltip = [
        alt.Tooltip("mes_nome:N", title="Mês"),
        alt.Tooltip("valor_txt:N", title="Saldo no fim do mês"),
        alt.Tooltip("var_txt:N", title="Variação vs mês anterior"),
    ]
    line = base.mark_line(strokeWidth=2, strokeCap="round", strokeJoin="round", color=p["receitas"]).encode(
        detail="trecho:N"
    )
    points = base.mark_point(
        filled=True, size=64, opacity=1, color=p["receitas"], stroke=p["surface"], strokeWidth=2
    ).encode(tooltip=tooltip)
    # Bigger invisible targets so hovering doesn't require hitting an 8px dot.
    hits = base.mark_point(size=600, opacity=0).encode(tooltip=tooltip)
    # End label sits above-left of the last point so it never runs off the right edge.
    last = base.transform_filter(alt.datum.ultimo).mark_text(
        align="right", dx=-4, dy=-14, fontWeight="bold", color=p["ink"]
    ).encode(text="valor_txt:N")
    layers = [line, points, hits, last]
    if (rows["valor"] < 0).any():
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=p["baseline"], strokeWidth=1).encode(y="y:Q")
        layers.insert(0, zero)
    return alt.layer(*layers).properties(height=260)


def categories_bars(rows: pd.DataFrame, mode: str = "light") -> alt.LayerChart:
    """Ranked horizontal bars, one hue. `rows`: categoria, valor, rotulo_valor, share_txt, descricao."""
    p = PALETTES[mode]
    order = rows["categoria"].tolist()
    x_max = float(rows["valor"].max()) * 1.35 if len(rows) else 1.0  # room for tip labels
    base = alt.Chart(rows).encode(
        y=alt.Y(
            "categoria:N",
            sort=order,
            axis=alt.Axis(title=None, labelLimit=280, ticks=False, domain=False, labelPadding=8),
        ),
        x=alt.X("valor:Q", axis=None, scale=alt.Scale(domain=[0, x_max])),
        tooltip=[
            alt.Tooltip("categoria:N", title="Categoria"),
            alt.Tooltip("rotulo_valor:N", title="Total"),
            alt.Tooltip("share_txt:N", title="Parte das despesas"),
            alt.Tooltip("descricao:N", title="Inclui"),
        ],
    )
    bars = base.mark_bar(size=20, cornerRadiusEnd=4, color=p["receitas"])
    labels = base.mark_text(align="left", dx=6, color=p["ink"]).encode(text="rotulo_tip:N")
    return alt.layer(bars, labels).properties(height=max(44 * len(rows), 120))
