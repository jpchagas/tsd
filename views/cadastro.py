import streamlit as st

from condo import accounts
from condo.data import get_account_store, known_units

st.title("Criar conta")
st.write(
    "Cada unidade tem um acesso. Depois de enviar, o síndico vai confirmar com você "
    "pelo telefone informado e liberar o acesso."
)

units = known_units()
with st.form("cadastro", clear_on_submit=False):
    unit = st.selectbox(
        "Unidade", options=units, index=None, placeholder="Escolha sua unidade",
        format_func=accounts.display_name,
    )
    name = st.text_input("Seu nome")
    phone = st.text_input("Telefone / WhatsApp", placeholder="(51) 99999-9999")
    password = st.text_input("Crie uma senha", type="password",
                             help=f"Pelo menos {accounts.MIN_PASSWORD} caracteres.")
    confirm = st.text_input("Repita a senha", type="password")
    submitted = st.form_submit_button("Enviar cadastro", type="primary")

if submitted:
    try:
        login = get_account_store().update(
            lambda doc: accounts.signup(doc, unit or "", name, phone, password, confirm, units),
            message=f"Novo cadastro: {accounts.display_name(unit or '')}",
        )
    except accounts.AccountError as exc:
        st.error(str(exc))
    else:
        st.success(
            f"Cadastro enviado! Assim que o síndico aprovar, entre com o login **{login}** "
            "e a senha que você criou."
        )
