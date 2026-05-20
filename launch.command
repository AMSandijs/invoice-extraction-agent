#!/bin/bash
# Double-click this file in Finder to open Invoice Assistant.
# First run: right-click → Open (macOS Gatekeeper), then double-click works.
cd "$(dirname "$0")"
source venv/bin/activate

# Start Streamlit in background, wait for it to boot, then open browser.
streamlit run app.py --browser.gatherUsageStats false --server.headless true &
STREAMLIT_PID=$!

sleep 3
open http://localhost:8501

# Bring Streamlit back to foreground so the terminal stays open while the app runs.
wait $STREAMLIT_PID
