#!/bin/bash
# CartIQ — Start all services
# Run this from the "Minor 2" project root: bash start.sh

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

echo ""
echo "🛒 Starting CartIQ..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Kill any existing processes on our ports ──────────────────────────────────
lsof -ti:8001 | xargs kill -9 2>/dev/null
lsof -ti:3001 | xargs kill -9 2>/dev/null
lsof -ti:3000 | xargs kill -9 2>/dev/null
sleep 1

# ── Python Scraper (port 8001) ────────────────────────────────────────────────
echo "🐍 Starting Python Scraper on :8001 ..."
cd "$PROJECT_DIR/apps/scraper"
source venv/bin/activate
nohup uvicorn main:app --port 8001 > /tmp/qc-scraper.log 2>&1 &
SCRAPER_PID=$!
echo "   PID: $SCRAPER_PID (logs: /tmp/qc-scraper.log)"

# ── API Gateway (port 3001) ───────────────────────────────────────────────────
echo "⚡ Starting API Gateway on :3001 ..."
cd "$PROJECT_DIR/apps/api-gateway"
nohup node src/index.js > /tmp/qc-api.log 2>&1 &
API_PID=$!
echo "   PID: $API_PID (logs: /tmp/qc-api.log)"

# ── Wait for both to be ready ─────────────────────────────────────────────────
sleep 3
echo ""
echo "🔍 Checking services..."

# Health check API gateway
if curl -s http://localhost:3001/health > /dev/null 2>&1; then
  echo "   ✅ API Gateway  → http://localhost:3001"
else
  echo "   ⚠️  API Gateway not responding yet (check /tmp/qc-api.log)"
fi

# Health check scraper
if curl -s http://localhost:8001/health > /dev/null 2>&1; then
  echo "   ✅ Scraper      → http://localhost:8001"
else
  echo "   ⚠️  Scraper not responding yet (check /tmp/qc-scraper.log)"
fi

# ── Frontend (port 3000) ──────────────────────────────────────────────────────
echo ""
echo "🎨 Starting Next.js Frontend on :3000 ..."
cd "$PROJECT_DIR/apps/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ All services starting!"
echo ""
echo "   🌐  Open: http://localhost:3000"
echo ""
echo "   To stop all: kill $SCRAPER_PID $API_PID $FRONTEND_PID"
echo "   Or run:      bash stop.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Keep terminal open and show frontend logs
wait $FRONTEND_PID
