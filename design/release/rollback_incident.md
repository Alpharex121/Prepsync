# Rollback and Incident Response Checklist

## Rollback checklist

1. Identify the deployed backend/frontend image tags.
2. Roll back backend deployment to previous stable image.
3. Roll back frontend deployment to previous stable image.
4. Re-run DB migration status check before rollbacking schema changes.
5. Verify `/health` and critical user journeys.

## Incident response checklist

1. Declare incident and assign incident commander.
2. Capture timestamps, affected components, blast radius.
3. Enable heightened logging and collect key metrics.
4. Apply mitigation (throttle, rollback, feature flag disable).
5. Confirm recovery via smoke tests and monitoring.
6. Publish incident summary and postmortem action items.
