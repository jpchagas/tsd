"""Group the administrator's expense codes (`Taxa`) into categories residents understand.

Only debits are categorized: some codes (e.g. 121 water) also appear as *credits*
when a resident pays an installment settlement, and those are income.
EXPENSE_CODES below is the default mapping. The síndico can change any code's
category on the "Categorias" page; the full mapping is then saved to
categorias.xlsx (through the storage backend) and takes precedence (see `merged`). A code with no category
falls into OUTROS and is flagged as new on that page.
"""
from __future__ import annotations

from io import BytesIO

import pandas as pd

PORTARIA = "Portaria e serviços gerais"
IMPOSTOS = "Impostos retidos de fornecedores"
AGUA_LUZ = "Água e luz"
OBRAS = "Obras e reformas"
MANUTENCAO = "Manutenção e conservação"
SEGURO = "Seguro e prevenção de incêndio"
ADMIN = "Administração e síndico"
OUTROS = "Outros"

CATEGORY_DESCRIPTIONS = {
    PORTARIA: "Empresa de portaria e o contrato de serviços gerais (limpeza e zeladoria).",
    IMPOSTOS: "INSS, ISS e outros tributos que a lei manda o condomínio reter da nota "
    "do fornecedor e pagar diretamente ao governo. Fazem parte do custo dos serviços "
    "contratados, principalmente da portaria.",
    AGUA_LUZ: "Contas de água (DMAE) e energia elétrica das áreas comuns.",
    OBRAS: "Reformas, alvenaria, impermeabilização e honorários de engenharia.",
    MANUTENCAO: "Elevadores, hidráulica, elétrica, serralheria, câmeras, "
    "material de limpeza e pequenos reparos.",
    SEGURO: "Seguro do prédio, laudos e taxas do PPCI e recarga de extintores.",
    ADMIN: "Síndico profissional, taxa da administradora, obrigações fiscais "
    "mensais, correspondências e tarifas bancárias.",
    OUTROS: "Despesas eventuais, como custas judiciais e homenagens.",
}

EXPENSE_CODES = {
    PORTARIA: ["682", "2634", "681"],
    IMPOSTOS: ["655", "162", "163", "664", "2624"],
    AGUA_LUZ: ["121", "233"],
    OBRAS: ["2456", "2426", "2556", "2173", "2614", "2133"],
    MANUTENCAO: [
        "127", "679", "503", "129", "2141", "2527", "2594", "5", "75",
        "674", "2070", "285", "35", "150", "2373", "2151",
    ],
    SEGURO: ["366", "757", "2608", "740", "2607"],
    ADMIN: [
        "2035", "618", "619", "2665", "2800", "2123", "2566", "2083", "2125",
        "2535", "2554", "2593", "2176", "2777", "2648",
    ],
    OUTROS: ["48", "2639", "54", "2706", "2463"],
}
CATEGORIES = list(EXPENSE_CODES)  # fixed order; at most 8 for chart readability
CODE_TO_CATEGORY = {code: cat for cat, codes in EXPENSE_CODES.items() for code in codes}

# Money moved in from elsewhere, not earned: excluded from income totals but
# still part of the balance. 913 = balance handed over by the previous administrator.
TRANSFER_CODES = {"913"}


DOC_NAME = "categorias.xlsx"


def expense_category(taxa: pd.Series, mapping: dict[str, str] | None = None) -> pd.Series:
    return taxa.map(mapping or CODE_TO_CATEGORY).fillna(OUTROS)


def unmapped_expense_codes(transactions: pd.DataFrame, mapping: dict[str, str] | None = None) -> set[str]:
    debits = transactions[transactions["valor"] < 0]
    return set(debits["taxa"]) - set(mapping or CODE_TO_CATEGORY)


# --- Síndico's edits ---------------------------------------------------------
def merged(saved: dict[str, str]) -> dict[str, str]:
    """Defaults, overridden by the saved mapping."""
    return {**CODE_TO_CATEGORY, **saved}


def mapping_to_xlsx(mapping: dict[str, str]) -> bytes:
    out = BytesIO()
    rows = sorted(mapping.items(), key=lambda kv: (CATEGORIES.index(kv[1]), int(kv[0]) if kv[0].isdigit() else 0))
    pd.DataFrame(rows, columns=["codigo", "categoria"]).to_excel(out, sheet_name="categorias", index=False)
    return out.getvalue()


def mapping_from_xlsx(data: bytes) -> dict[str, str]:
    frame = pd.read_excel(BytesIO(data), dtype=str).dropna()
    # A category typed by hand that doesn't exist is ignored (the default applies).
    return {r.codigo.strip(): r.categoria.strip() for r in frame.itertuples() if r.categoria.strip() in CATEGORIES}


def code_table(transactions: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """One row per expense code in the data: codigo, exemplo (latest description),
    lancamentos, total (positive), categoria (None if unmapped), novo. New codes
    first, then by total."""
    debits = transactions[transactions["valor"] < 0].sort_values("data", kind="stable")
    groups = debits.groupby("taxa")
    out = pd.DataFrame(
        {
            "exemplo": groups["descricao"].last(),
            "lancamentos": groups.size(),
            "total": -groups["valor"].sum(),
        }
    ).rename_axis("codigo").reset_index()
    out["categoria"] = [mapping.get(code) for code in out["codigo"]]
    out["novo"] = out["categoria"].isna()
    return out.sort_values(["novo", "total"], ascending=[False, False], ignore_index=True)
