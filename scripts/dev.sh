#!/usr/bin/env bash
set -euo pipefail

SESSION="stockflow"
ENABLE_HOST=false

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/frontend"
VENV="$ROOT/.venv"

# Parse args
for arg in "$@"; do
  case $arg in
    --host)
      ENABLE_HOST=true
      shift
      ;;
  esac
done

# Shell-independent venv activation: exec the activate script directly
# rather than relying on `source`, which is shell-specific.
ACTIVATE="$VENV/bin/activate"
# We'll prefix commands with `env` + the venv's python/binaries directly,
# avoiding `source` entirely. tmux panes inherit the base shell.
PYTHON="$VENV/bin/python"
CELERY="$VENV/bin/celery"

tmux kill-session -t "$SESSION" 2>/dev/null || true

# ─────────────────────────────────────────────
# Window 0 — Dev (Django + Frontend)
# ─────────────────────────────────────────────
tmux new-session -d -s "$SESSION" -c "$ROOT" -n "dev"

# Layout: top bar (small shell) | bottom-left backend | bottom-right frontend
tmux split-window -v -t "$SESSION:0"
tmux split-window -h -t "$SESSION:0.1"
tmux resize-pane -t "$SESSION:0.0" -y 10

# Backend (bottom-left, pane 1)
tmux send-keys -t "$SESSION:0.1" \
  "uv run manage.py runserver 0.0.0.0:8000" Enter

# Frontend (bottom-right, pane 2)
if [ -d "$FRONTEND" ] && [ -f "$FRONTEND/package.json" ]; then
  tmux send-keys -t "$SESSION:0.2" \
    "cd $FRONTEND && pnpm dev" Enter
fi

# ─────────────────────────────────────────────
# Window 1 — Workers (Redis + Celery worker + beat)
# ─────────────────────────────────────────────
HAS_CELERY=false
"$PYTHON" -c "import celery" 2>/dev/null && HAS_CELERY=true

if [ "$HAS_CELERY" = true ]; then
  tmux new-window -t "$SESSION:1" -n "workers" -c "$ROOT"

  # Redis (pane 0)
  tmux send-keys -t "$SESSION:1.0" "redis-server" Enter

  # Celery worker (pane 1)
  tmux split-window -h -t "$SESSION:1"
  tmux send-keys -t "$SESSION:1.1" \
    "VIRTUAL_ENV=$VENV PATH=$VENV/bin:\$PATH celery -A config worker -l info" Enter

  # Celery beat (pane 2, split vertically from pane 1)
  tmux split-window -v -t "$SESSION:1.1"
  tmux send-keys -t "$SESSION:1.2" \
    "VIRTUAL_ENV=$VENV PATH=$VENV/bin:\$PATH sleep 2 && celery -A config beat -l info" Enter
fi

# ─────────────────────────────────────────────
# Window 2 — Tunnels (optional, --host flag)
# ─────────────────────────────────────────────
if [ "$ENABLE_HOST" = true ]; then
  tmux new-window -t "$SESSION:2" -n "tunnels" -c "$ROOT"

  tmux send-keys -t "$SESSION:2.0" \
    'set -a && . .env.tunnels && set +a && cloudflared tunnel run --token "$CF_TOKEN_BACKEND"' Enter

  tmux split-window -h -t "$SESSION:2"
  tmux send-keys -t "$SESSION:2.1" \
    'set -a && . .env.tunnels && set +a && cloudflared tunnel run --token "$CF_TOKEN_FRONTEND"' Enter
fi

# ─────────────────────────────────────────────
# Window 3 — Shell (git, migrations, tests)
# ─────────────────────────────────────────────
tmux new-window -t "$SESSION:3" -n "shell" -c "$ROOT"
# Drop into venv by launching python's activated environment inline
tmux send-keys -t "$SESSION:3.0" \
  "VIRTUAL_ENV=$VENV PATH=$VENV/bin:\$PATH exec \$SHELL" Enter

# Focus dev window, top pane
tmux select-window -t "$SESSION:0"
tmux select-pane -t "$SESSION:0.0"

tmux attach-session -t "$SESSION"
