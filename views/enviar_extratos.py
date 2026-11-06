"""Admin page: upload monthly statements. Each file is validated before saving."""
from io import BytesIO

import streamlit as st

from condo import auth, loader
from condo.data import ACCOUNT_LABELS, brl, get_dataset, month_label, save_statements

user = auth.require_admin()
st.title("Enviar extratos")
st.write(
    "Envie o extrato mensal em Excel (.xlsx) exportado da administradora. "
    "Cada arquivo é conferido antes de ser salvo. Enviar um mês que já existe substitui o anterior."
)

uploads = st.file_uploader("Extratos", type=["xlsx"], accept_multiple_files=True)

existing = get_dataset()
closing_by_month = {
    (row.mes, row.conta): row.saldo_final for row in existing.balances.itertuples()
}

valid: list[tuple[bytes, loader.Statement]] = []
for upload in uploads or []:
    data = upload.getvalue()
    try:
        stmt = loader.load_statement(BytesIO(data))
    except loader.StatementError as exc:
        st.error(f"**{upload.name}**: {exc}")
        continue

    replaces = stmt.month in existing.months
    with st.container(border=True):
        st.markdown(
            f"**{upload.name}** → extrato de **{month_label(stmt.month)}**"
            + (" (substitui o arquivo atual)" if replaces else "")
        )
        for row in stmt.balances.itertuples():
            st.write(f"{ACCOUNT_LABELS[row.conta]}: saldo final {brl(row.saldo_final)}")
            previous = closing_by_month.get((stmt.month - 1, row.conta))
            if previous is not None and abs(previous - row.saldo_inicial) > loader.TOLERANCE:
                st.warning(
                    f"{ACCOUNT_LABELS[row.conta]}: o saldo inicial ({brl(row.saldo_inicial)}) "
                    f"difere do saldo final do mês anterior ({brl(previous)})."
                )
    valid.append((data, stmt))

months = [stmt.month for _, stmt in valid]
if len(months) != len(set(months)):
    st.error("Há mais de um arquivo para o mesmo mês. Envie apenas um por mês.")
elif valid and st.button(f"Salvar {len(valid)} extrato(s)", type="primary"):
    try:
        save_statements(valid, author=user.name)
    except OSError as exc:
        st.error(f"Não foi possível salvar os extratos. Tente novamente mais tarde. ({exc})")
    else:
        st.success("Extratos salvos. O painel já mostra os dados novos.")

st.divider()
st.subheader("Extratos salvos")
st.write(", ".join(month_label(m) for m in get_dataset().months) or "Nenhum.")  # fresh after a save
