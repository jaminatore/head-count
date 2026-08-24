#!/usr/bin/env bash
set -e

echo "Starting stack..."
docker compose up -d --build --scale app=3

echo "Waiting for app to be healthy..."
until curl -sf http://localhost:1234/healthz > /dev/null 2>&1; do
  sleep 1
done

echo "Seeding database..."
python seed.py --reset

echo "Running tests..."
pytest tests/ -v

echo "Tearing down..."
docker compose down -v