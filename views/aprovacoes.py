"""Admin page: approve signups and password resets, manage who has access."""
import pandas as pd
import streamlit as st

from condo import accounts, auth
from condo.data import get_account_store

user = auth.require_admin()
st.title("Aprovações")
store = get_account_store()


def act(change, message: str, success: str) -> None:
    try:
        store.update(change, message=f"{message} (por {user.name})")
    except accounts.AccountError as exc:
        st.session_state["aprovacoes_msg"] = ("error", str(exc))
    else:
        st.session_state["aprovacoes_msg"] = ("success", success)


if msg := st.session_state.pop("aprovacoes_msg", None):
    (st.success if msg[0] == "success" else st.error)(msg[1])

doc, _ = store.load()
users = doc["users"]
pending = {k: u for k, u in users.items() if u["status"] == accounts.PENDING}
resets = {k: r for k, r in doc["resets"].items() if k in users}

# --- Signups ---------------------------------------------------------------
st.subheader(f"Cadastros aguardando aprovação ({len(pending)})")
if not pending:
    st.caption("Nenhum cadastro pendente.")
else:
    st.caption(
        "Confirme com a pessoa pelo telefone informado antes de aprovar. "
        "Se a unidade for de outra pessoa, recuse."
    )
for login, u in sorted(pending.items(), key=lambda kv: kv[1]["created_at"]):
    with st.container(border=True):
        info, buttons = st.columns([3, 1], vertical_alignment="center")
        info.markdown(
            f"**{accounts.display_name(u['unidade'])}** · {u['name']}  \n"
            f"Telefone: {accounts.format_phone(u['phone'])} · pedido em {u['created_at'][:16].replace('T', ' ')}"
        )
        with buttons:
            st.button(
                "Aprovar", key=f"ok-{login}", type="primary", width="stretch",
                on_click=act,
                args=(lambda d, l=login: accounts.approve_signup(d, l, user.name),
                      f"Cadastro aprovado: {login}", f"Acesso de {login} liberado."),
            )
            st.button(
                "Recusar", key=f"no-{login}", width="stretch",
                on_click=act,
                args=(lambda d, l=login: accounts.reject_signup(d, l),
                      f"Cadastro recusado: {login}", f"Cadastro de {login} recusado."),
            )

# --- Password resets --------------------------------------------------------
st.subheader(f"Pedidos de nova senha ({len(resets)})")
if not resets:
    st.caption("Nenhum pedido pendente.")
else:
    st.caption(
        "Ligue ou mande mensagem para o telefone do cadastro (não para outro número) e "
        "peça o código que a pessoa recebeu. Aprove só se o código conferir."
    )
for login, r in sorted(resets.items(), key=lambda kv: kv[1]["requested_at"]):
    u = users[login]
    with st.container(border=True):
        info, buttons = st.columns([3, 1], vertical_alignment="center")
        info.markdown(
            f"**{accounts.display_name(u['unidade'])}** · {u['name']}  \n"
            f"Telefone do cadastro: {accounts.format_phone(u['phone'])} · "
            f"pedido em {r['requested_at'][:16].replace('T', ' ')}  \n"
            f"Código esperado: **{r['code']}**"
        )
        with buttons:
            st.button(
                "Aprovar", key=f"rok-{login}", type="primary", width="stretch",
                on_click=act,
                args=(lambda d, l=login: accounts.approve_reset(d, l, user.name),
                      f"Nova senha aprovada: {login}", f"Nova senha de {login} liberada."),
            )
            st.button(
                "Recusar", key=f"rno-{login}", width="stretch",
                on_click=act,
                args=(lambda d, l=login: accounts.reject_reset(d, l),
                      f"Pedido de senha recusado: {login}", f"Pedido de {login} recusado."),
            )

# --- Residents with access --------------------------------------------------
active = {k: u for k, u in users.items() if u["status"] == accounts.ACTIVE}
st.subheader(f"Moradores com acesso ({len(active)})")
if active:
    order = accounts.sort_units(u["unidade"] for u in active.values())
    by_unit = {u["unidade"]: (k, u) for k, u in active.items()}
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Unidade": accounts.display_name(unit),
                    "Login": by_unit[unit][0],
                    "Nome": by_unit[unit][1]["name"],
                    "Telefone": accounts.format_phone(by_unit[unit][1]["phone"]),
                    "Aprovado em": by_unit[unit][1].get("approved_at", "")[:10],
                }
                for unit in order
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    with st.expander("Remover acesso (por exemplo, quando o morador se muda)"):
        target = st.selectbox(
            "Unidade", options=[by_unit[u][0] for u in order], index=None,
            format_func=lambda l: f"{accounts.display_name(active[l]['unidade'])} · {active[l]['name']}",
        )
        sure = st.checkbox("Confirmo que esta pessoa não deve mais ter acesso.")
        st.button(
            "Remover acesso", disabled=not (target and sure),
            on_click=act,
            args=(lambda d, l=target: accounts.remove_access(d, l),
                  f"Acesso removido: {target}", f"Acesso de {target} removido. A unidade pode se cadastrar de novo."),
        )
else:
    st.caption("Nenhum morador cadastrado ainda.")
