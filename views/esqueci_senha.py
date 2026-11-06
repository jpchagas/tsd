import streamlit as st

from condo import accounts
from condo.data import get_account_store, known_units

st.title("Esqueci minha senha")
st.write(
    "Escolha uma nova senha. Por segurança, ela só passa a valer depois que o síndico "
    "confirmar o pedido com você, pelo telefone do seu cadastro."
)

with st.form("reset"):
    unit = st.selectbox(
        "Unidade", options=known_units(), index=None, placeholder="Escolha sua unidade",
        format_func=accounts.display_name,
    )
    password = st.text_input("Nova senha", type="password",
                             help=f"Pelo menos {accounts.MIN_PASSWORD} caracteres.")
    confirm = st.text_input("Repita a nova senha", type="password")
    submitted = st.form_submit_button("Pedir nova senha", type="primary")

if submitted:
    if not unit:
        st.error("Escolha sua unidade.")
        st.stop()
    try:
        code = get_account_store().update(
            lambda doc: accounts.request_reset(doc, accounts.username_for(unit), password, confirm),
            message=f"Pedido de nova senha: {accounts.display_name(unit)}",
        )
    except accounts.AccountError as exc:
        st.error(str(exc))
    else:
        st.success("Pedido enviado!")
        st.markdown(f"Seu código de confirmação é **{code}**. Anote esse número.")
        st.info(
            "O síndico vai entrar em contato pelo telefone do seu cadastro e pedir esse "
            "código. Depois da confirmação, entre com a nova senha. Se você não fez este "
            "pedido, ignore: sua senha atual continua valendo."
        )
