# Load Testing

## Prerequisites

- Install k6: https://k6.io/docs/get-started/installation/

## Run

`k6 run backend/loadtest/health_load.js -e BASE_URL=http://localhost:8000`

## Goal

- Baseline health endpoint latency and availability under concurrent load.
- Extend this script for room create/join/start flows before production launch.
