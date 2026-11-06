import streamlit as st

from condo import auth, categories
from condo.data import get_account_store, get_category_map, get_dataset

st.set_page_config(page_title="Finanças do Condomínio", page_icon="🏢", layout="wide")

user = auth.current_user()
if user is None:
    st.navigation(
        [
            st.Page("views/entrar.py", title="Entrar", icon="🔑", default=True),
            st.Page("views/cadastro.py", title="Criar conta", icon="📝"),
            st.Page("views/esqueci_senha.py", title="Esqueci minha senha", icon="❓"),
        ]
    ).run()
    st.stop()

pages = [st.Page("views/visao_geral.py", title="Visão geral", icon="📊", default=True)]
if user.is_admin:
    doc, _ = get_account_store().load()
    waiting = sum(u["status"] == "pending" for u in doc["users"].values()) + len(doc["resets"])
    pages.append(
        st.Page("views/aprovacoes.py", title=f"Aprovações ({waiting})" if waiting else "Aprovações", icon="✅")
    )
    pages.append(st.Page("views/enviar_extratos.py", title="Enviar extratos", icon="📤"))
    new_codes = len(categories.unmapped_expense_codes(get_dataset().transactions, get_category_map()))
    pages.append(
        st.Page("views/categorias.py", title=f"Categorias ({new_codes})" if new_codes else "Categorias", icon="🏷️")
    )

with st.sidebar:
    st.write(f"Olá, **{user.name}**" + (f" · {user.unidade.replace('Lj Loja', 'Loja')}" if user.unidade else ""))
    st.button("Sair", on_click=auth.logout)

st.navigation(pages).run()
