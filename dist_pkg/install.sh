#!/bin/bash
# Installer script for Omni Trainer SITL Launcher
# This script installs all dependencies and configures the environment

set -e

echo "=========================================="
echo "Omni Trainer SITL Launcher - Installer"
echo "=========================================="
echo ""

# Detect OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="ubuntu"
    if command -v apt-get &> /dev/null; then
        echo "[INFO] Detected Ubuntu/Debian system"
    else
        echo "[ERROR] This installer supports Ubuntu/Debian systems only"
        exit 1
    fi
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
    echo "[INFO] Detected macOS"
else
    echo "[ERROR] Unsupported OS: $OSTYPE"
    exit 1
fi

# Check Python
echo "[INFO] Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 not found. Please install Python 3.8 or later."
    exit 1
fi
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "[OK] Python $PYTHON_VERSION found"
echo ""

# Install system packages
if [ "$OS" = "ubuntu" ]; then
    echo "[INFO] Installing system packages..."
    sudo apt-get update -qq
    sudo apt-get install -y \
        python3-pip \
        python3-dev \
        python3-pyqt5 \
        python3-pyqt5.qtwebengine \
        python3-pyqt5.qtwebchannel \
        libgl1-mesa-glx \
        libgl1-mesa-dri \
        libegl1-mesa \
        docker.io \
        xterm \
        git \
        2>&1 | grep -E "^(Get|Setting|Processing|Reading)" || true
    sudo apt-get install -y docker-compose-plugin 2>&1 | grep -E "^(Get|Setting|Processing|Reading)" || true
    echo "[OK] System packages installed"
    echo ""
elif [ "$OS" = "macos" ]; then
    echo "[INFO] Installing dependencies with Homebrew..."
    if ! command -v brew &> /dev/null; then
        echo "[ERROR] Homebrew not found. Please install from https://brew.sh"
        exit 1
    fi
    brew install python3 pyqt5 git || true
    echo "[OK] Dependencies installed"
    echo ""
fi

# Install Python packages
echo "[INFO] Installing Python packages..."
python3 -m pip install --user --upgrade pip setuptools wheel 2>&1 | tail -3 || true
python3 -m pip install --user \
    PyYAML \
    pymavlink \
    MAVProxy \
    2>&1 | grep -E "Successfully|already satisfied" || true
echo "[OK] Python packages installed"
echo ""

ARDUPILOT_ROOT="${OMNI_ARDUPILOT_ROOT:-$HOME/ardupilot}"
MODEL_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/assets/ardupilot/aircraft/Omni-Trainer"
MODEL_TARGET="$ARDUPILOT_ROOT/Tools/autotest/aircraft/Omni-Trainer"

if [ -d "$ARDUPILOT_ROOT" ] && [ -d "$MODEL_SOURCE" ]; then
    mkdir -p "$(dirname "$MODEL_TARGET")"
    cp -a "$MODEL_SOURCE/." "$MODEL_TARGET/"
    echo "[OK] Installed Omni-Trainer assets to $MODEL_TARGET"
    echo ""
fi

echo "=========================================="
echo "[SUCCESS] Installation complete!"
echo "=========================================="
echo ""
echo "You can now run the Omni Trainer SITL Launcher:"
echo "  ./omni-trainer-sitl"
echo ""
echo "This installer assumes ArduPilot SITL is already installed on the device."
echo "If you need to use a custom ArduPilot checkout, set:"
echo "  OMNI_ARDUPILOT_ROOT=/path/to/ardupilot ./omni-trainer-sitl"
echo "Default auto-detected ArduPilot path: $HOME/ardupilot"
if command -v docker >/dev/null 2>&1; then
    echo "Docker SITL is available from the GUI checkbox or:"
    echo "  bash scripts/docker_sitl.sh"
    echo "If Docker permission is denied, run: sudo usermod -aG docker \$USER"
    echo "Then log out and log back in."
fi
echo ""
