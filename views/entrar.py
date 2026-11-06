import streamlit as st

from condo import auth

st.title("Finanças do Condomínio")
st.write("Entre com o login da sua unidade, por exemplo **ap102** ou **loja174**.")

with st.form("login"):
    username = st.text_input("Login")
    password = st.text_input("Senha", type="password")
    submitted = st.form_submit_button("Entrar", type="primary")

if submitted:
    user, message = auth.authenticate(username, password)
    if user is None:
        st.error(message)
    else:
        auth.sign_in(user)
        st.rerun()

st.caption("Ainda não tem acesso? Use **Criar conta** no menu. Esqueceu a senha? Use **Esqueci minha senha**.")
