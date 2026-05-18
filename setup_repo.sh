#!/bin/bash
# ============================================================
# One-time script to create a private GitHub repo and push
# all current project files.
#
# Prerequisites:
#   - GitHub CLI:  brew install gh
#   - Then login:  gh auth login
#
# Run this script from inside the project folder:
#   cd ~/Desktop/homework\ task
#   chmod +x setup_repo.sh
#   ./setup_repo.sh
# ============================================================

set -e  # stop on first error

REPO_NAME="invoice-extraction-agent"

echo ""
echo "=== Invoice Extraction Agent — Repo Setup ==="
echo ""

# Check gh is installed
if ! command -v gh &> /dev/null; then
    echo "[ERROR] GitHub CLI not found. Install it first:"
    echo "  brew install gh"
    echo "  gh auth login"
    exit 1
fi

# Check gh is authenticated
if ! gh auth status &> /dev/null; then
    echo "[ERROR] Not logged into GitHub. Run:"
    echo "  gh auth login"
    exit 1
fi

# Init git if not already a repo
if [ ! -d ".git" ]; then
    echo "[1/5] Initialising git repository..."
    git init
    git branch -M main
else
    echo "[1/5] Git already initialised."
fi

# Stage all files
echo "[2/5] Staging files..."
git add .
git status --short

# Initial commit
echo "[3/5] Creating initial commit..."
git commit -m "Initial commit: invoice extractor + RAG conversational agent

Mandatory part:
- extractor.py: unified Level 2 + Level 3 invoice extraction via GPT-4o
  - text-based PDFs  → pdfplumber + GPT-4o text
  - scanned/image PDFs → GPT-4o Vision
- requirements.txt, README.md

Optional part (Option 2 - Conversational Agent):
- store.py: loads extracted CSV into SQLite
- agent.py: Text-to-SQL core logic using GPT-4o
- app.py: Streamlit chat UI with SQL transparency panel

Supports both OpenAI and Azure AI Foundry as LLM providers."

# Create private GitHub repo and push
echo "[4/5] Creating private GitHub repo: $REPO_NAME..."
gh repo create "$REPO_NAME" --private --source=. --remote=origin --push

echo "[5/5] Done!"
echo ""
echo "Your repo is live at: https://github.com/$(gh api user --jq .login)/$REPO_NAME"
echo ""
