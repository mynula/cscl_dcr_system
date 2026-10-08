# CSCL DCR (Daily Call Report) System

Pharmaceutical and sales force automation platform for Concord Stem Cell & Pharmaceuticals Ltd. Designed to track field sales representatives, territory mappings, doctor interactions, sample distributions, and executive analytics.

## Tech Stack
- **Backend:** FastAPI, Python 3.14, Pydantic v2
- **ORM & Database:** SQLAlchemy 2.0, PostgreSQL (`cscl_dcr_db`) with resilient SQLite fallback
- **Frontend:** Jinja2 SSR, Tailwind CSS, HTMX 1.9
- **Security:** Native Bcrypt password hashing, PyJWT authentication tokens with HTTP-only cookies

---

## Quick Start Guide

### 1. Activate Environment
The virtual environment is pre-configured with Python 3.14 dependencies:
```powershell
.\venv\Scripts\activate
```

### 2. Configure Database (`.env`)
By default, the application connects to PostgreSQL:
```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/cscl_dcr_db
```
*Note: If your local PostgreSQL password differs, update `.env`. If connection is unreachable, the system automatically falls back to `./cscl_dcr.db` to ensure zero-downtime development.*

#### PostgreSQL password-authentication troubleshooting

The app does not have a separate database password form. It reads the PostgreSQL role credentials from `DATABASE_URL` in the project-root `.env` file. For example:
```env
DATABASE_URL=postgresql+psycopg://postgres:URL_ENCODED_PASSWORD@127.0.0.1:5432/cscl_dcr_db
```

If the password contains URL-reserved characters, encode them in the URL (for example, `@` as `%40`, `:` as `%3A`, and `%` as `%25`). Do not share or commit your real `.env` file.

If you see `password authentication failed`, PostgreSQL is reachable, but the password does not match the `postgres` role (or the role named in the URL):
1. In PowerShell, test the credentials directly: `psql -h 127.0.0.1 -p 5432 -U postgres -d cscl_dcr_db`. Enter the password at the prompt. If `psql` is not on PATH, use SQL Shell (psql) from the PostgreSQL Start menu.
2. If you know another PostgreSQL administrator account, connect with it and reset the app role password securely using `\password postgres` in `psql`; this prompts you without putting the password into shell history. Otherwise, reset it through pgAdmin while connected as a database administrator.
3. Update `DATABASE_URL` in `.env` with the new password (URL-encoded if necessary), save, and restart Uvicorn.
4. Check the startup output for `Successfully connected to primary database.` If the connection fails, the app falls back to SQLite; do not treat a successful page load alone as proof that PostgreSQL is being used.

Do not change `pg_hba.conf` to `trust` to get around password errors. Keep password authentication enabled (for example `scram-sha-256`) and correct the role password/configuration instead.

For production deployment, use a hosted PostgreSQL URL in the host's secret environment settings, not the local `.env` file.

### 3. Launch the Server
```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Open your browser at **`http://127.0.0.1:8000`**.

---

## Development User Accounts

| Role | Username | Password | Access Level |
|---|---|---|---|
| **Administrator** | `admin` | `admin123` | Full access to Master Admin CRUD, Analytics Dashboard, DCR entry, and global logs |
| **Field Marketer** | `marketer1` | `marketer123` | Field DCR Entry, Personal Call History, and Personal Dashboard |

These are for local development only. Production startup skips development account and sample-report seeding. Existing account passwords should be changed before making a deployment public; authenticated users can use **Change Password**.

---

## Core Features & Workflow

### 1. Authentication & Session Management (`app/routers/auth.py`)
- Cookie-based session storage for web browsing alongside standard Bearer tokens for REST clients.
- Role-based route protection (`get_current_user` and `get_current_admin_user`).
- Administrators can create Admin, Manager, and Marketer accounts from the Users tab; Managers cannot manage accounts or assign roles.
- Marketers see their own DCR history and dashboard analytics, while Managers and Admins see organization-wide reports.

### 2. Daily Call Report (DCR) Form (`app/templates/dcr/form.html`)
- **Cascading Dropdowns:** Selecting a Territory dynamically issues HTMX requests to `/dcr/cascading/hospitals` and `/dcr/cascading/doctors`.
- **Asynchronous Submission:** Forms submit asynchronously via `hx-post="/dcr/"`, displaying instantaneous success banners with auto-generated sequential DCR numbers (`DCR-YYYYMMDD-XXXX`).
- **Structured Field Intelligence:** Captures indication, visit outcome, estimated therapy candidates, referral opportunities, CME plans, clinical questions, commercial concerns, competitor intelligence, and next actions.

### 3. Management Analytics Dashboard (`app/templates/dashboard/index.html`)
- Executive overview with live KPIs: Today's calls, Month-to-date volume, Doctor reach percentage, Active field force count.
- Territory call volume distribution with progress bar share.
- Top Visited Doctors Leaderboard with interaction timestamps.
- 7-day trend activity visualization.
- Marketer scorecard and doctor coverage by territory.
- Referral funnel and indication/therapy candidate breakdown.
- Territory yield matrix with a documented productive-call outcome definition.
- Role-scoped follow-up control with overdue/due-today/upcoming counts and a mark-complete action.
- Role-scoped market intelligence summaries and recent competitor, commercial, and clinical observations.
- Product-demand reporting (product names are separated by commas or semicolons in DCR entries).

### 4. Master Data Admin CRUD (`app/templates/admin/index.html`)
- Tabbed management console for Territories, Hospitals, Doctors & KOLs, and Visit Classifications.
- HTMX inline deletion and modal creation without full page refreshes.
- Admin-only account creation for Admin, Manager, and Marketer roles.

## Deploying to Vercel with Neon

Vercel detects the FastAPI entrypoint at `app/main.py`. `.python-version` selects Python 3.14, and `.gitignore`/`.vercelignore` keep local credentials, databases, and virtual environments out of deployments.

### 1. Secure the Neon connection
- The Neon connection string was shared in chat. Rotate its role password in Neon before public deployment, then use the replacement pooled connection string. Never put a real connection string in source control or share it in chat.
- Existing local PostgreSQL application data was copied to Neon and verified: 4 territories, 6 hospitals, 3 users, 6 doctors, and 5 visit types. The source database contained no DCR rows.
- Use the pooled connection string as a Vercel environment variable. Do not replace your local `.env` unless you also want local development to use Neon.

### 2. Link this folder to Vercel
From PowerShell in the project folder:
```powershell
npx vercel login
npx vercel link
```
Follow the prompts to log into your account and create/select the project.

### 3. Add production environment variables
In the Vercel dashboard, open the project and go to **Settings → Environment Variables**. Add these for **Production** (and Preview only if preview deployments should use this database):

| Name | Value |
|---|---|
| `APP_ENV` | `production` |
| `DATABASE_URL` | The rotated Neon pooled connection string |
| `SECRET_KEY` | A newly generated random secret; generate locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"` |

Keep these values private. Do not use the development signing key or paste generated values into chat. Vercel automatically defaults this app to production mode; production requires the PostgreSQL URL and secret, disables debug mode, sets secure session cookies, fails rather than silently falling back to SQLite, and skips development sample-data seeding.

### 4. Deploy
After adding the environment variables:
```powershell
npx vercel --prod
```
Open the deployment URL and verify the login page, dashboard, DCR entry, and static logo. Sign in with an existing administrator account and use **Change Password** immediately; deployment does not change existing passwords. Create separate accounts for other users, and only then share the public URL.

---

## Running Automated Tests
Run the test suite:
```powershell
.\venv\Scripts\python.exe -m unittest tests/test_dcr_system.py
```
