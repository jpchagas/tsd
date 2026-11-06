from io import BytesIO

import pandas as pd

from condo import categories, loader, storage


def _dataset():
    store = storage.from_config(None)
    return loader.load_all(BytesIO(store.read(n)) for n in store.names())


def test_every_expense_code_in_the_data_is_mapped():
    # Fails when a new statement brings an expense code nobody has categorized yet:
    # add it to categories.EXPENSE_CODES instead of letting it fall into "Outros".
    assert categories.unmapped_expense_codes(_dataset().transactions) == set()


def test_codes_belong_to_one_category_and_every_category_is_described():
    all_codes = [c for codes in categories.EXPENSE_CODES.values() for c in codes]
    assert len(all_codes) == len(set(all_codes))
    assert set(categories.EXPENSE_CODES) == set(categories.CATEGORY_DESCRIPTIONS)
    assert len(categories.EXPENSE_CODES) <= 8  # chart readability


def test_unknown_code_falls_into_outros():
    assert categories.expense_category(pd.Series(["682", "99999"])).tolist() == [
        categories.PORTARIA,
        categories.OUTROS,
    ]


def test_saved_mapping_overrides_defaults_and_roundtrips():
    saved = {"682": categories.OUTROS, "99999": categories.OBRAS, "007": categories.SEGURO}
    assert categories.mapping_from_xlsx(categories.mapping_to_xlsx(saved)) == saved  # codes stay text
    merged = categories.merged(saved)
    assert categories.expense_category(pd.Series(["682", "99999", "121"]), merged).tolist() == [
        categories.OUTROS,
        categories.OBRAS,
        categories.AGUA_LUZ,
    ]


def test_unknown_category_in_file_is_ignored():
    data = categories.mapping_to_xlsx({"682": categories.OBRAS})
    frame = pd.read_excel(BytesIO(data), dtype=str)
    frame.loc[len(frame)] = ["121", "Categoria inventada"]
    out = BytesIO()
    frame.to_excel(out, index=False)
    assert categories.mapping_from_xlsx(out.getvalue()) == {"682": categories.OBRAS}


def test_code_table_lists_debit_codes_new_first():
    tx = pd.DataFrame(
        {
            "data": pd.to_datetime(["2026-10-01", "2026-10-05", "2026-10-02", "2026-10-03"]),
            "taxa": ["682", "682", "99999", "121"],
            "descricao": ["Portaria set", "Portaria out", "Algo novo", "Acerto agua"],
            "valor": [-100.0, -150.0, -10.0, 50.0],  # 121 here is a credit: not listed
        }
    )
    table = categories.code_table(tx, categories.CODE_TO_CATEGORY)
    assert table["codigo"].tolist() == ["99999", "682"]
    assert table["novo"].tolist() == [True, False]
    first, second = table.iloc[0], table.iloc[1]
    assert first["categoria"] is None
    assert (second["exemplo"], second["lancamentos"], second["total"]) == ("Portaria out", 2, 250.0)
