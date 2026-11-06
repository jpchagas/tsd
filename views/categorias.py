"""Admin page: choose the category of each expense code."""
import pandas as pd
import streamlit as st

from condo import auth, categories
from condo.data import brl, get_category_map, get_dataset, save_category_map

user = auth.require_admin()
st.title("Categorias de despesa")
st.write(
    "Cada despesa do extrato vem com um código da administradora (a coluna “Taxa”). "
    "Escolha em qual categoria cada código aparece para os moradores. A mudança vale "
    "para todos os meses, inclusive os que já foram enviados."
)

if msg := st.session_state.pop("categorias_msg", None):
    st.success(msg)

data = get_dataset()
if not data.months:
    st.info("Nenhum extrato enviado ainda.")
    st.stop()

mapping = get_category_map()
table = categories.code_table(data.transactions, mapping)
new = int(table["novo"].sum())
if new:
    st.warning(
        f"{new} código(s) novo(s) sem categoria, no topo da tabela. "
        "Até você escolher, essas despesas aparecem em “Outros”."
    )

with st.form("categorias", border=False):
    edited = st.data_editor(
        pd.DataFrame(
            {
                "Novo": table["novo"],
                "Código": table["codigo"],
                "Exemplo de descrição": table["exemplo"],
                "Lançamentos": table["lancamentos"],
                "Total pago": table["total"].map(brl),
                "Categoria": table["categoria"],
            }
        ),
        column_config={
            "Novo": st.column_config.CheckboxColumn(width="small", help="Código ainda sem categoria."),
            "Categoria": st.column_config.SelectboxColumn(
                options=categories.CATEGORIES, width="large", help="Clique para escolher a categoria."
            ),
        },
        column_order=None if new else ["Código", "Exemplo de descrição", "Lançamentos", "Total pago", "Categoria"],
        height=min(36 * (len(table) + 1) + 3, 600),
        disabled=["Novo", "Código", "Exemplo de descrição", "Lançamentos", "Total pago"],
        hide_index=True,
        width="stretch",
        key="categorias_editor",
    )
    submitted = st.form_submit_button("Salvar alterações", type="primary")

if submitted:
    chosen = {code: cat for code, cat in zip(edited["Código"], edited["Categoria"]) if isinstance(cat, str)}
    changed = {code: cat for code, cat in chosen.items() if mapping.get(code) != cat}
    if not changed:
        st.info("Nenhuma alteração para salvar.")
    else:
        try:
            save_category_map({**mapping, **changed}, author=user.name)
        except OSError as exc:
            st.error(f"Não foi possível salvar. Tente novamente. ({exc})")
        else:
            st.session_state["categorias_msg"] = f"{len(changed)} código(s) atualizado(s)."
            st.rerun()  # refreshes the page and the count in the menu

with st.expander("O que cada categoria deve incluir"):
    for name in categories.CATEGORIES:
        st.markdown(f"**{name}:** {categories.CATEGORY_DESCRIPTIONS[name]}")
