# Dispensa Planejada Backend

## Vercel Environment Variables (Turso)

For the deployed FastAPI backend to connect to Turso, the following environment
variables must be configured in the **Vercel dashboard**:

- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`

**Important requirements:**

- Store the values **WITHOUT quotes** (no surrounding single or double quotes).
- Store the values **WITHOUT a trailing newline**.
- Set them in the **Production** scope.
- A **Redeploy** is required after changing them for the new values to take effect.