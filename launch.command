#!/bin/bash
# Double-click this file in Finder to open Invoice Assistant.
# First run: right-click → Open (macOS Gatekeeper), then double-click works.
cd "$(dirname "$0")"
open http://localhost:8501
streamlit run app.py
