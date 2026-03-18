# SSO Login & Per-User Settings — User Guide

**Feature Version**: 0.4.0-sso-user-settings  
**Application**: MCP Client Web  
**Date**: March 2026

---

## Table of Contents

1. [Overview](#1-overview)
2. [How SSO Works in This Application](#2-how-sso-works-in-this-application)
3. [Signing In](#3-signing-in)
4. [Your Session](#4-your-session)
5. [User Menu & Avatar](#5-user-menu--avatar)
6. [My Account Tab](#6-my-account-tab)
7. [Per-User Data Isolation](#7-per-user-data-isolation)
8. [Signing Out](#8-signing-out)
9. [Admin Capabilities](#9-admin-capabilities)
10. [Administrator Setup (Environment Variables)](#10-administrator-setup-environment-variables)
11. [Single-User (No SSO) Mode](#11-single-user-no-sso-mode)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Overview

SSO (Single Sign-On) support lets multiple users share a single MCP Client Web deployment while keeping their data completely separate. Each user logs in with their existing corporate or Google identity — no new passwords to create or manage.

**What SSO adds:**

| Capability | Details |
|---|---|
| Identity providers | Microsoft (Azure AD / Entra ID) and Google Workspace |
| Per-user data isolation | Each user has their own MCP servers, LLM configuration, and chat sessions |
| Persistent preferences | Theme, density, and tool panel settings sync across all your browsers |
| User menu | Avatar and dropdown in the header for quick access to settings and sign-out |
| Admin panel | Administrators can view, disable, and reset any user |

**SSO is optional.** If the server is not configured with a `SECRET_KEY` and at least one identity provider, the application runs in single-user mode exactly as before — no login screen, no changes.

---

## 2. How SSO Works in This Application

The application uses the **OIDC Authorization Code Flow with PKCE** — the modern, secure standard for browser-based SSO. Here is what happens behind the scenes when you sign in:

```
  Your browser                   MCP Client Backend              Your IdP (Azure/Google)
  ─────────────                  ──────────────────              ───────────────────────
  1. Visit the app
       ↓
  2. Redirected to /login
       ↓
  3. Click "Sign in with Microsoft"
       ↓  (PKCE code generated in browser)
  4. ──────────────────────────────────────────────────────────→  Authorization URL
  5. ←──────────────────────────────────────────────────────────  Login + consent screen
  6. IdP redirects back to /auth/callback with a one-time code
       ↓
  7.                             Exchanges code for tokens
  8.                             Validates ID token (JWKS, nonce, expiry)
  9.                             Upserts user record in DB
  10.                            Issues HttpOnly session cookie (app_token)
       ↓
  11. Redirected to the chat UI — you are logged in
```

**Key security properties:**
- Your IdP password is never seen by this application
- The session cookie is `HttpOnly` (JavaScript cannot read it), `Secure` (HTTPS only), and `SameSite=Strict`
- API credentials you store (OpenAI keys, etc.) are encrypted at rest with AES-256-GCM

---

## 3. Signing In

### 3.1 First Visit

When SSO is enabled, visiting any page while unauthenticated redirects you to the **login page** (`/login`).

```
┌─────────────────────────────────────────┐
│                                         │
│          MCP Client Web                 │
│                                         │
│   ┌─────────────────────────────────┐   │
│   │  🔷  Sign in with Microsoft     │   │
│   └─────────────────────────────────┘   │
│                                         │
│   ┌─────────────────────────────────┐   │
│   │  🔴  Sign in with Google        │   │
│   └─────────────────────────────────┘   │
│                                         │
│   By signing in you accept the          │
│   Terms of Use                          │
└─────────────────────────────────────────┘
```

Only providers that the administrator has configured appear. If you only see one button, only one provider is set up.

### 3.2 Completing the Login

1. Click your provider button.
2. Your browser is redirected to Microsoft or Google's login page.
3. Enter your credentials and approve any consent screen (first time only).
4. You are redirected back to the MCP Client chat interface, now logged in.

The entire flow typically takes **under 5 seconds** on a normal connection.

### 3.3 First-Time vs. Returning Users

| Scenario | What Happens |
|---|---|
| First login | A new user account is created using your IdP profile (name, email, avatar) |
| Returning login | Your existing account is found; `last_login_at` is updated; all your data is restored |
| Different browser, same account | Your preferences and data load from the backend — nothing to re-configure |

---

## 4. Your Session

### 4.1 Session Duration

Sessions are valid for **8 hours** by default (configurable by your administrator). You do not need to re-login during a working day.

### 4.2 Session Expiry

When your session expires:

1. The next API call returns HTTP 401.
2. The application automatically redirects to `/login` within 2 seconds.
3. A banner appears on the login page:

   > **"Your session expired. Please sign in again."**

Simply click your provider button to resume exactly where you left off — your servers, LLM config, and preferences are all still there.

### 4.3 Disabled Account

If an administrator disables your account, you will see:

> **HTTP 403 — Account disabled. Contact your administrator.**

---

## 5. User Menu & Avatar

Once signed in, the top-right corner of the header shows **your avatar** instead of the gear icon.

```
┌─────────────────────────────────────────────────────────────┐
│  MCP Client Web                              [A]  ← avatar  │
└─────────────────────────────────────────────────────────────┘
```

**Clicking your avatar** opens a dropdown menu:

```
┌─────────────────────────────────┐
│  Alice Smith                    │
│  alice@example.com              │
│  ─────────────────────────────  │
│  ⚙  My Settings                 │
│  ─────────────────────────────  │
│  ↩  Sign Out                    │
└─────────────────────────────────┘
```

| Menu Item | Action |
|---|---|
| Name + email | Read-only identity display |
| **My Settings** | Opens the Settings modal pre-navigated to the "My Account" tab |
| **Sign Out** | Ends your session and returns to the login page |

**Avatar display:**
- If your IdP provides a profile picture, it is shown.
- If not (or if the image fails to load), your initials are shown on a coloured background.

The dropdown closes when you click outside it or press **Escape**.

---

## 6. My Account Tab

Open the Settings modal (via the avatar menu → **My Settings**) to find the **"My Account"** tab — the first tab in the modal.

### 6.1 Profile Section

Displays read-only identity information pulled from your IdP at login:

| Field | Description |
|---|---|
| Avatar | Profile picture or initials placeholder |
| Display Name | Full name from your IdP |
| Email | Your primary email address |
| Member Since | When your account was first created in this application |
| Role Badge | Shows **Admin** if you have the admin role |

Profile fields (name, avatar) come from your IdP and cannot be edited here.

### 6.2 Appearance

| Setting | Options | Default |
|---|---|---|
| **Theme** | Light / Dark / System | System |
| **Message Density** | Compact / Comfortable | Comfortable |

Changes take effect immediately and are saved to the backend automatically — no Save button needed. Your preference will be restored the next time you log in, even from a different browser.

### 6.3 Chat Defaults

| Setting | Description | Default |
|---|---|---|
| **Tool Panel Visible** | Show or hide the tool execution panel in the chat view | On |

### 6.4 Sign Out Button

A **Sign Out** button at the bottom of the tab is an alternative to the avatar dropdown.

---

## 7. Per-User Data Isolation

Every piece of data in the application is scoped to **your user account**. Other users cannot see or access your data, and you cannot see theirs.

### 7.1 MCP Servers

- The servers you add (`Settings → MCP Servers`) are visible only to you.
- The tools discovered from those servers are only available in your chat sessions.
- Server IDs are UUIDs; guessing another user's server ID returns HTTP 403.

### 7.2 LLM Configuration

- Your LLM provider, model, API key, and other settings are stored separately from every other user.
- API keys are **encrypted at rest** on the server and are never returned in full from any API call.
  - The settings panel shows a masked version such as `sk-...abcd` to confirm the key is saved.
  - To update a key, just paste the new value in the field and save.
  - To keep the existing key unchanged, leave the field blank when saving other settings.

### 7.3 Chat Sessions

- Sessions are created in your name and only your messages are stored in them.
- Session IDs are opaque; even if someone guesses a session ID, they receive HTTP 403 if it is not theirs.
- **Note:** Chat history is in-memory. It does not survive a server restart (this is a known limitation of v0.4.0).

### 7.4 Isolation Summary

| Resource | Isolated? | What Happens on Cross-User Access |
|---|---|---|
| MCP Servers | ✅ Yes | HTTP 403 |
| LLM Config | ✅ Yes | HTTP 403 |
| Chat Sessions | ✅ Yes | HTTP 403 |
| UI Preferences | ✅ Yes | Each user's own settings |
| Tool Discovery | ✅ Yes | Only tools from your servers |

---

## 8. Signing Out

You can sign out in two ways:

1. **Avatar menu** → **Sign Out**
2. **Settings modal** → **My Account** tab → **Sign Out** button

Both call `POST /auth/logout`, which:
- Clears the `app_token` session cookie from your browser.
- Redirects you to `/login`.

After signing out, pressing the browser back button or navigating to `/` will redirect you back to the login page — no data from your previous session is accessible.

---

## 9. Admin Capabilities

Users whose email is listed in the `SSO_ADMIN_EMAILS` environment variable automatically receive the `admin` role at each login.

### 9.1 Identifying Admin Users

Admins see an **Admin** badge next to their name in the My Account tab.

### 9.2 User Management API

Admins have access to the following endpoints (HTTP 403 for regular users):

| Action | Endpoint |
|---|---|
| List all users (paginated) | `GET /api/admin/users?limit=50&offset=0` |
| View a specific user | `GET /api/admin/users/{user_id}` |
| Enable / disable a user | `PATCH /api/admin/users/{user_id}` `{"is_active": false}` |
| Reset a user's settings | `DELETE /api/admin/users/{user_id}/settings` |

### 9.3 Disabling a User

```json
PATCH /api/admin/users/{user_id}
{ "is_active": false }
```

- The user's next API request returns HTTP 403 — Account disabled.
- Their data (servers, LLM config, preferences) is preserved; set `is_active: true` to re-enable.

### 9.4 Resetting a User's Settings

```
DELETE /api/admin/users/{user_id}/settings
```

- Clears the user's **LLM configuration** and **UI preferences**.
- Does **not** delete the user account or their registered servers.
- The user will need to re-enter their LLM provider settings on next login.

### 9.5 Granting Admin Role

Admin promotion is managed via an environment variable — no UI required:

```bash
export SSO_ADMIN_EMAILS=alice@example.com,bob@corp.com
```

The role is re-evaluated on every login. Adding or removing an email from this list takes effect the next time that user signs in — no restart required.

---

## 10. Administrator Setup (Environment Variables)

### 10.1 Required Variables

| Variable | Description |
|---|---|
| `SECRET_KEY` | 32-byte hex key for JWT signing and credential encryption. Generate with: `python -c "import secrets; print(secrets.token_hex(32))"` |

Without `SECRET_KEY`, SSO is disabled and the application runs in single-user mode.

### 10.2 Azure AD / Entra ID

| Variable | Description |
|---|---|
| `AZURE_AD_CLIENT_ID` | App registration client ID |
| `AZURE_AD_CLIENT_SECRET` | App registration client secret |
| `AZURE_AD_TENANT_ID` | Your Azure tenant ID |
| `AZURE_AD_REDIRECT_URI` | Must exactly match the registered redirect URI (e.g. `https://mcp.example.com/auth/callback/azure_ad`) |

**Azure App Registration checklist:**
1. Platform: Web
2. Redirect URI: `https://{your-domain}/auth/callback/azure_ad`
3. API Permissions: `openid`, `email`, `profile` (delegated)
4. Token configuration: ensure `email` and `name` optional claims are enabled

### 10.3 Google Workspace

| Variable | Description |
|---|---|
| `GOOGLE_CLIENT_ID` | OAuth 2.0 client ID |
| `GOOGLE_CLIENT_SECRET` | OAuth 2.0 client secret |
| `GOOGLE_REDIRECT_URI` | Must exactly match the registered redirect URI (e.g. `https://mcp.example.com/auth/callback/google`) |

**Google Cloud Console checklist:**
1. Create an OAuth 2.0 client (Web application type)
2. Authorised redirect URI: `https://{your-domain}/auth/callback/google`
3. Scopes: `openid`, `email`, `profile`

### 10.4 Optional Variables

| Variable | Default | Description |
|---|---|---|
| `SSO_SESSION_TTL_HOURS` | `8` | How long a login session lasts |
| `SSO_ADMIN_EMAILS` | _(empty)_ | Comma-separated admin email addresses |
| `DB_URL` | `sqlite:///./mcp_client.db` | SQLAlchemy DB URL (use Postgres for multi-instance deployments) |
| `JWKS_CACHE_TTL_SECONDS` | `3600` | How long to cache IdP public keys |

### 10.5 Complete Example `.env`

```bash
# Required for SSO
SECRET_KEY=a3f8c2d1e4b5a6079f8e3d2c1b0a9887f6e5d4c3b2a190807060504030201f0

# Session and admin
SSO_SESSION_TTL_HOURS=8
SSO_ADMIN_EMAILS=alice@corp.com

# Azure AD
AZURE_AD_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_AD_CLIENT_SECRET=your-azure-client-secret
AZURE_AD_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_AD_REDIRECT_URI=https://mcp.example.com/auth/callback/azure_ad

# Google (optional — only needed if using Google login)
GOOGLE_CLIENT_ID=xxxxxxxxxxxxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=https://mcp.example.com/auth/callback/google

# Database (optional — defaults to SQLite)
DB_URL=sqlite:///./mcp_client.db
```

### 10.6 Starting the Server

```bash
source venv/bin/activate
export SECRET_KEY=...       # or load from .env
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

On startup, the application:
1. Initialises the database schema (creates tables if not present).
2. Loads configured SSO providers from environment variables.
3. Logs which providers are active: `SSO providers loaded: ['azure_ad']`

---

## 11. Single-User (No SSO) Mode

If `SECRET_KEY` is not set, or no IdP environment variables are configured, the application starts in **single-user mode**:

- No login screen is shown.
- All existing functionality works exactly as in v0.2.0/v0.3.0.
- All data is stored in-memory (global shared state, no per-user isolation).
- The user avatar and "My Account" tab are not shown.

This allows existing deployments to upgrade without any configuration changes.

---

## 12. Troubleshooting

### "No providers configured" on the login page

The login page shows no buttons if no IdP environment variables are set. Verify:
- `AZURE_AD_CLIENT_ID` (and the other Azure vars) are set for Microsoft login.
- `GOOGLE_CLIENT_ID` (and the other Google vars) are set for Google login.
- The server was restarted after setting the variables.

### `redirect_uri_mismatch` error from your IdP

The `AZURE_AD_REDIRECT_URI` or `GOOGLE_REDIRECT_URI` value must exactly match the URI registered in your IdP app (including `http` vs `https` and trailing slashes).

### "Invalid state parameter" on callback

Occurs when the `state` cookie/storage value does not match what the IdP returned. Common causes:
- The user took too long (> session storage lifetime) to complete the login.
- Cookies were cleared between the redirect and the callback.

Solution: Try signing in again.

### Session expires immediately

Verify that the server clock is accurate. JWT expiry validation compares against the server's system time. A large clock skew between the server and the IdP will cause instant expiry.

### API keys appear as `null` after login

If you recently upgraded from single-user mode, your old `localStorage`-based LLM config is not automatically migrated to the per-user backend store. Re-enter your LLM provider settings in `Settings → LLM Config` after your first SSO login.

### "Account disabled" (HTTP 403)

Contact your administrator. An admin can re-enable your account via:

```
PATCH /api/admin/users/{your_user_id}
{ "is_active": true }
```

### Avatar not showing (initials displayed instead)

The avatar URL comes from your IdP's `picture` claim. If your IdP profile has no picture, or the picture URL is not publicly accessible from your browser, the fallback initials placeholder is shown automatically.

### Preferences not syncing to another browser

Settings sync requires a successful `GET /api/users/me/settings` call on login. Check browser console for network errors. If the backend is unreachable at login time, the application falls back to the locally cached preferences in `localStorage`.

---

## Quick Reference

| Task | How |
|---|---|
| Sign in | Visit the app → click your provider button on `/login` |
| Sign out | Avatar menu → Sign Out (or My Account tab → Sign Out) |
| Change theme | Avatar menu → My Settings → My Account → Appearance |
| Change message density | Avatar menu → My Settings → My Account → Appearance |
| Toggle tool panel | Avatar menu → My Settings → My Account → Chat Defaults |
| Add MCP servers | Avatar menu → My Settings → MCP Servers |
| Configure LLM | Avatar menu → My Settings → LLM Config |
| Session expired | Sign in again — all your data is preserved |

---

*MCP Client Web — SSO User Guide — v0.4.0-sso-user-settings*
