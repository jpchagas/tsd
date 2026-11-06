# Finanças do Condomínio

A Streamlit dashboard that shows residents where the condo's money comes from and where it goes, built from the administrator's monthly statements (`.xlsx`). Each apartment has its own login. The building manager (síndico) also gets a page for uploading new monthly statements.

## Running locally

```bash
poetry install                                    # creates .venv/ in the project
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then edit it, see below
poetry run streamlit run app.py
poetry run pytest
```

All data is kept as `.xlsx` files: the monthly statements (`extrato_01487_*.xlsx`), the accounts (`usuarios.xlsx`) and, once the síndico edits them on **Categorias**, the expense categories (`categorias.xlsx`). Locally they live in `docs/` (gitignored, so they never go to GitHub; override with `CONDO_DATA_DIR`). When hosted, they are stored in a Supabase table instead (see below).

## Accounts

- **Building manager (síndico):** configured in the secrets with role `admin`. Generate the password hash with `poetry run python -m condo.passwords`. The síndico sees the **Aprovações** and **Enviar extratos** pages.
- **Residents:** sign up on **Criar conta**, with one account per unit. The login is derived from the unit (`ap102`, `ap01`, `loja174`). The account works only after the síndico approves it on **Aprovações**, after confirming with the person by phone.
- **Forgot password:** the resident picks a new password on **Esqueci minha senha** and gets a 6-digit code. The síndico calls or messages the phone number *from the signup*, asks for the code, and approves the request if it matches. Until then, the old password keeps working.
- **Moving out:** **Aprovações → Remover acesso** frees the unit for a new signup.

Accounts are stored in `usuarios.xlsx` (sheets `usuarios` and `pedidos_senha`) with salted password hashes.

## Hosting: Render (free) + Supabase (free)

Render runs the app; its disk is wiped on every restart, so the `.xlsx` files are stored as rows of a table in a Supabase database (not in Supabase Storage buckets, whose free CDN can serve a stale copy after a file is replaced).

**1. Supabase**
1. Create a project at [supabase.com](https://supabase.com) in region **East US (North Virginia)**, next to the Render server.
2. In **SQL Editor**, run:
   ```sql
   create table public.arquivos (
     nome text primary key,                    -- e.g. extrato_01487_2026-10-01_2026-11-01.xlsx
     conteudo text not null,                   -- the .xlsx file, base64
     versao integer not null default 1,        -- bumped on every save (conflict detection)
     atualizado_em timestamptz not null default now(),
     atualizado_por text
   );
   alter table public.arquivos enable row level security;  -- no policies: only the secret key can access it
   grant select, insert, update, delete on public.arquivos to service_role;
   ```
3. In **Project Settings → API Keys**, copy the project URL and create a **secret key** (`sb_secret_...`).
4. Locally, put a `[storage]` table with `backend = "supabase"`, the URL and the key in `.streamlit/secrets.toml` (see the example file), then copy the current data up once:
   ```bash
   poetry run python -m condo.migrate
   ```

**2. Render**
1. Push this code to a GitHub or GitLab repository (`docs/` and `secrets.toml` are gitignored and stay out).
2. In Render, **New → Blueprint** and pick the repository; it reads `render.yaml`.
3. In the service's **Environment → Secret Files**, add a file named `secrets.toml` with the same content as your local `.streamlit/secrets.toml` (storage + síndico login).

**Limits of the free plans.** The Render app sleeps after 15 minutes without visitors; the next visit takes about a minute to wake it. Supabase pauses a free project after a week of inactivity; the data is kept and the project is resumed from the Supabase dashboard (if the app shows a connection error after a quiet week, that is the cause).

**Backups.** In Supabase's free plan there are no downloadable backups; the síndico still has every statement as sent by the administrator, and `python -m condo.migrate` can rebuild from a `docs/` copy.
