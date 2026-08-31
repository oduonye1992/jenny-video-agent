#!/bin/bash
# Jenny Video Agent — one-command setup
# Usage: bash setup.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}!${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; }

echo ""
echo "  Jenny Video Agent — Setup"
echo "  ─────────────────────────────"
echo ""

# ── 1. Check system dependencies ──────────────────────────────────────────

MISSING=()

# Python 3.13+
if command -v python3.13 &>/dev/null; then
    ok "Python 3.13"
elif command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    if [[ "$PY_VER" == "3.13" || "$PY_VER" > "3.13" ]]; then
        ok "Python $PY_VER"
    else
        fail "Python $PY_VER (need 3.13+)"
        MISSING+=("python3.13")
    fi
else
    fail "Python not found"
    MISSING+=("python3.13")
fi

# ffmpeg
if command -v ffmpeg &>/dev/null; then
    ok "ffmpeg"
else
    fail "ffmpeg not found"
    MISSING+=("ffmpeg")
fi

# Node.js is optional and is only needed for the local viewer.
if command -v node &>/dev/null; then
    ok "Node.js $(node -v)"
else
    warn "Node.js not found — install it to use the optional viewer"
fi

# Homebrew (macOS only, for installing missing deps)
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! command -v brew &>/dev/null; then
        warn "Homebrew not found — install from https://brew.sh"
    fi
fi

if [[ ${#MISSING[@]} -gt 0 ]]; then
    echo ""
    fail "Missing dependencies: ${MISSING[*]}"
    if [[ "$OSTYPE" == "darwin"* ]] && command -v brew &>/dev/null; then
        echo ""
        echo "  Install with:"
        for dep in "${MISSING[@]}"; do
            case $dep in
                python3.13) echo "    brew install python@3.13" ;;
                ffmpeg)     echo "    brew install ffmpeg" ;;
                node)       echo "    brew install node" ;;
            esac
        done
    fi
    echo ""
    echo "  Re-run this script after installing."
    exit 1
fi

echo ""

# ── 2. Python venv + dependencies ─────────────────────────────────────────

if [[ ! -d "venv" ]]; then
    echo "Creating Python virtual environment..."
    python3.13 -m venv venv
    ok "venv created"
else
    ok "venv exists"
fi

echo "Installing Python dependencies..."
venv/bin/pip install -q -r requirements.txt
ok "Python dependencies installed"

echo ""

# ── 3. Environment file ───────────────────────────────────────────────────

if [[ -f ".env" ]]; then
    ok ".env exists"

    # Check which keys are set
    KEYS_OK=0
    KEYS_MISSING=0

    check_key() {
        local key=$1
        local label=$2
        local required=$3
        if grep -q "^${key}=" .env && ! grep -qE "^${key}=(your_|replace-with|$)" .env; then
            ok "  $label"
            KEYS_OK=$((KEYS_OK + 1))
        elif [[ "$required" == "required" ]]; then
            fail "  $label (required)"
            KEYS_MISSING=$((KEYS_MISSING + 1))
        else
            warn "  $label (optional)"
        fi
    }

    echo ""
    echo "  API Keys:"
    check_key "FAL_KEY"           "FAL (image/video gen, upscale)" "required"
    check_key "ELEVENLABS_API_KEY" "ElevenLabs (TTS, voice, music)" "required"
    check_key "GOOGLE_API_KEY"     "Google Gemini (video analysis)" "optional"
    check_key "ANTHROPIC_API_KEY"  "Anthropic (verification)"       "optional"
    check_key "SUPABASE_URL"       "Supabase (image hosting)"       "required"
    check_key "SUPABASE_SECRET_KEY" "Supabase secret key"           "required"
    check_key "AIRTABLE_API_KEY"   "Airtable (batch pipeline)"      "optional"

    if [[ $KEYS_MISSING -gt 0 ]]; then
        echo ""
        warn "Some required keys are missing. Edit .env to add them."
    fi
else
    cp .env.example .env
    warn ".env created from template — edit it with your API keys:"
    echo ""
    echo "  Required:"
    echo "    FAL_KEY            — https://fal.ai/dashboard/keys"
    echo "    ELEVENLABS_API_KEY — https://elevenlabs.io/app/settings/api-keys"
    echo "    SUPABASE_URL       — https://supabase.com/dashboard (project settings)"
    echo "    SUPABASE_SECRET_KEY"
    echo ""
    echo "  Optional:"
    echo "    GOOGLE_API_KEY     — https://aistudio.google.com/apikey"
    echo "    ANTHROPIC_API_KEY  — https://console.anthropic.com/settings/keys"
    echo "    AIRTABLE_API_KEY   — https://airtable.com/create/tokens (for batch)"
    echo ""
fi

echo ""

# ── 4. Verify ─────────────────────────────────────────────────────────────

echo "Running tests..."
if venv/bin/python -m pytest tests/ -q --tb=no 2>/dev/null; then
    ok "All tests pass"
else
    fail "Some tests failed — run 'make test' for details"
fi

echo ""
echo "  ─────────────────────────────"
echo -e "  ${GREEN}Setup complete.${NC}"
echo ""
echo "  Quick start:"
echo "    source venv/bin/activate"
    echo "    make test                     # run the test suite"
    echo "    python workflow/engine.py --help"
echo ""
