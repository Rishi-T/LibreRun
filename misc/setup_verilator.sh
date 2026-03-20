#!/usr/bin/env bash

set -e  # exit on error

############################
# USER CONFIG (EDIT THIS)
############################
export VERILATOR_VERSION=5.046

############################
# INTERNAL CONFIG
############################
VERILATOR_SRC_DIR=~/verilator
VERILATOR_INSTALL_DIR=/tools/verilator/v$VERILATOR_VERSION

FIRST_RUN=false

if [[ "$1" == "-fr" ]]; then
    FIRST_RUN=true
fi

echo "== Verilator setup for version $VERILATOR_VERSION =="

############################
# STEP 0: Prerequisites (only on -fr)
############################
if $FIRST_RUN; then
    echo "[INFO] Installing prerequisites..."
    sudo apt update
    sudo apt install -y git help2man perl python3 make autoconf g++ flex bison ccache \
        libgoogle-perftools-dev numactl perl-doc \
        libfl2 libfl-dev zlib1g zlib1g-dev

    echo "[INFO] Removing existing source dir (clean start)..."
    rm -rf $VERILATOR_SRC_DIR
fi

############################
# STEP 1: Clone or reuse repo
############################
if [[ ! -d "$VERILATOR_SRC_DIR" ]]; then
    echo "[INFO] Cloning Verilator repo..."
    git clone https://github.com/verilator/verilator.git $VERILATOR_SRC_DIR
else
    echo "[INFO] Verilator repo exists, reusing..."
fi

cd $VERILATOR_SRC_DIR

############################
# STEP 2: Fetch latest tags
############################
echo "[INFO] Fetching latest tags..."
git fetch --tags

############################
# STEP 3: Checkout version
############################
echo "[INFO] Checking out version v$VERILATOR_VERSION..."
git checkout v$VERILATOR_VERSION

############################
# STEP 4: Prepare build system
############################
echo "[INFO] Running autoconf..."
autoconf

############################
# STEP 5: Configure
############################
echo "[INFO] Configuring build..."
./configure --prefix=$VERILATOR_INSTALL_DIR

############################
# STEP 6: Build
############################
echo "[INFO] Building..."
make -j$(nproc)

############################
# STEP 7: Install
############################
echo "[INFO] Installing to $VERILATOR_INSTALL_DIR..."
sudo make install

############################
# STEP 8: Verify
############################
echo "[INFO] Verifying installation..."
if [[ -x "$VERILATOR_INSTALL_DIR/bin/verilator" ]]; then
    "$VERILATOR_INSTALL_DIR/bin/verilator" --version
else
    echo "[ERROR] Verilator binary not found!"
    exit 1
fi

echo "== Done =="
