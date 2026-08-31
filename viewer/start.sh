#!/bin/bash
# Start the Pipeline Viewer (backend + frontend)
# Usage: ./viewer/start.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Starting Pipeline Viewer..."
echo "  Backend:  http://localhost:8420"
echo "  Frontend: http://localhost:5173"
echo ""

# Start backend
cd "$PROJECT_ROOT"
source venv/bin/activate
cd viewer/backend
python app.py &
BACKEND_PID=$!

# Start frontend
cd "$SCRIPT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

# Cleanup on exit
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM

echo "Both servers running. Press Ctrl+C to stop."
wait
