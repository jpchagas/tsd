# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Goal (from README): a **Python Streamlit dashboard** that analyzes the condo's account balance. It will be hosted so that every resident can open it and understand where the condo's money comes from and where it goes. Treat residents (non-technical, Portuguese-speaking) as the audience for any UI text.

Built: login, resident signup/password reset with síndico approval, the overview (balance and month metrics, income/expense and balance charts, expenses by category, entries table), statement upload, and per-code category editing. Code is on GitHub (`jpchagas/tsd`); data (`docs/`), `credenciais/` and `.streamlit/secrets.toml` are gitignored and must never be committed.

## Commands

Dependencies are managed with Poetry (`pyproject.toml` + `poetry.lock`, `package-mode = false`). `poetry.toml` keeps the virtualenv in `.venv/`. There is no `requirements.txt`.

```bash
poetry install
poetry add <pkg>            # or: poetry add --group dev <pkg>
poetry run pytest                                   # all tests
poetry run pytest tests/test_loader.py::test_april_2025_quirks
poetry run streamlit run app.py
poetry run python -m condo.passwords                # password_hash for the síndico in secrets.toml
```

Configuration lives in `.streamlit/secrets.toml` (gitignored; see `.streamlit/secrets.toml.example`): `[storage]` (backend `supabase` + url + key; omit for local `docs/`), `[auth.users.<login>]` (síndico/admin only) and optional `[condo] extra_units`. Without users the login page shows a configuration error.

## Architecture

- `app.py`: login gate, then `st.navigation`. The upload page is only registered for `role = "admin"`, and it also calls `auth.require_admin()`. Pages live in `views/`, not `pages/`, to avoid Streamlit's automatic multipage discovery.
- `condo/loader.py`: pure pandas parser (no Streamlit). `load_statement()` returns a `Statement`, and `load_all()` returns a `Dataset`. Amounts are **signed** (`Crédito − Débito`). Each account is checked to reconcile (opening + transactions = closing), otherwise `StatementError` is raised. The statement month comes from the earliest PRI date, not from the filename.
- `condo/storage.py`: all data is `.xlsx` files, saved under canonical names (re-uploading a month replaces it). Two backends with the same interface: `LocalStorage` (`docs/`, gitignored, or `CONDO_DATA_DIR`; development) and `SupabaseStorage` (rows of table `arquivos` via PostgREST: `nome`, base64 `conteudo`, `versao`; writes are conditional on `versao` → `ConflictError`). A table, not Storage buckets, because buckets lack conditional writes and the free CDN can serve stale copies. Chosen by `from_config(st.secrets["storage"])`. `python -m condo.migrate` copies `docs/` into the configured backend.
- `condo/data.py`: `get_dataset()` is cached and keyed on the storage signature (mtimes, or row versions on Supabase). The signature itself is cached for 60s to limit API calls, and saving clears the caches.
- `condo/categories.py`: maps expense `Taxa` codes into at most 8 resident-facing categories (`CATEGORIES`). Only debits are categorized. `TRANSFER_CODES` (`913`) are excluded from income but stay in the balance. `EXPENSE_CODES` is the default mapping; the síndico edits it per code on `views/categorias.py` (`st.data_editor`), saved as `categorias.xlsx` (columns `codigo`, `categoria`) and merged over the defaults by `data.get_category_map()`, which is what views and `metrics.expenses_by_category(..., mapping)` must use. Codes with no category fall into Outros and are flagged as new (count shown in the menu). `tests/test_categories.py` fails when the bundled data has a code missing from the defaults: add new codes there.
- `condo/metrics.py`: `monthly_summary()` (income, expenses, result, closing balance and month-over-month `var_*`) and `expenses_by_category()`. Months without a statement are NaN rows, never zero, so changes next to a gap are NaN.
- `condo/charts.py`: Altair builders following the dataviz rules. There is one y-axis per chart (balance gets its own chart, never a dual axis), and colors are validated for both Streamlit themes (`theme_mode()` reads `st.context.theme`). Missing months stay on the x axis as empty slots.
- `condo/accounts.py`: resident accounts (signup, reset requests, approvals) as pure functions on a dict. There is one account per unit, with the login derived from the unit (`ap102`, `loja174`), and status is `pending` until the síndico approves. A password reset stores the new hash plus a 6-digit code until the síndico approves; the síndico verifies via the phone number on file. `AccountStore` persists it as `usuarios.xlsx` (sheets `usuarios` and `pedidos_senha`, read with `dtype=str`; see `to_xlsx`/`from_xlsx`) through `read_doc`/`write_doc` (optimistic concurrency: `ConflictError` triggers a re-read and re-apply).
- `condo/auth.py` + `condo/passwords.py`: session-state login with stdlib PBKDF2 hashes. Users from secrets (the síndico, role `admin`) are checked first, then the account store (role `morador`). Logged-out users get the pages `entrar`, `cadastro` and `esqueci_senha`; the admin also gets `aprovacoes` (title shows the pending count), `enviar_extratos` and `categorias` (title shows the count of new codes).

Hosting: Render free (`render.yaml`; `secrets.toml` is a Render Secret File copied into `.streamlit/` at start) with data in Supabase. See README.

## Source data: `docs/extrato_01487_<start>_<end>.xlsx`

Monthly bank/administrator statements for condo account `01487`. Each filename covers one month (`start` is the 1st of the month, `end` is the 1st of the next month). Coverage has gaps: there is `2025-04`, then `2026-01` through `2026-10`. Missing months should not be assumed to be zero. Units seen: Ap 01, Ap x1–x3 for floors 1–12 except Ap 22 (never appears), and Lj Loja 174.

Sheets (order varies between files, and some names have **trailing spaces**, so match on stripped names):

| Sheet | Meaning |
|---|---|
| `Conta PRI` | Main operating account: dues income and operating expenses |
| `Conta FO ` | Works fund (`fundo Obras`). Absent in the 2025-04 file. Mostly income, but can pay works (e.g. `2173`) |
| `Conta FR ` | Reserve fund (`fundo De Reserva`), with per-unit contributions |
| `Lancamentos futuros` | Scheduled future entries, **not** included in the final balance. It is the same snapshot in every file (taken at export time), so only the latest file's copy is meaningful |

Account sheets (PRI/FO/FR) use the columns `Dia | Taxa | Descrição | Débito | Crédito`:
- `Dia` is stored as an Excel serial date, but openpyxl returns it as a `datetime` because the cells are date-formatted. The loader handles both.
- `Taxa` is a numeric category code stored as text, for example `620` = opening balance, `988` = condo dues, `989` = fund contribution, `612` = late fee, `618` = administration fee, `2648` = bank fees, `366` = insurance, `2035` = professional building manager, `913` = one-off transfer from the previous administrator (2025-04). **A code does not fix the direction**: installment settlements (`acerto:1/5`…) come in as credits under expense-like codes (`121`, `103`, `695`, `120`, `532`, `881`).
- The first data row is usually `Saldo Mes Anterior` (opening balance). It can be in `Débito` (a negative balance) or be missing (FR in 2025-04). The last row is `Saldo Final`. Both are excluded from transactions.
- Sheets contain fully blank spacer rows.
- Each row has a value in either `Débito` or `Crédito`, never both.
- `Descrição` contains parseable structure. Dues lines look like `Condominio Ap 102 (principal)-10/2026`, and units can also be shops (`Lj Loja 174`). Expense lines often include the supplier name and an `Nf.:` invoice number. The month in the description is the reference period, which can differ from the payment month.

`Lancamentos futuros` starts with two title/notice rows, then the header `Conta | Data vencimento | Descrição | Débito | Crédito`, the entries, a `Total de lançamentos futuros` row, and a `Resumo` block. Only rows whose `Conta` is `PRI`/`FO`/`FR` are entries.
