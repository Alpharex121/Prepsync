# Migration and seed

Run migration:

`psql "$POSTGRES_URL" -f backend/migrations/001_initial.sql`

Run seed:

`psql "$POSTGRES_URL" -f backend/scripts/seed.sql`
