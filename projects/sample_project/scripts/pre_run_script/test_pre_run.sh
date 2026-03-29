#!/usr/bin/env bash

# Parse flow-mandated args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-root) PROJECT_ROOT="$2"; shift 2 ;;
        --config-name)  CONFIG_NAME="$2";  shift 2 ;;
        --run-number)   RUN_NUMBER="$2";   shift 2 ;;
        *) echo "Unknown arg: $1"; shift ;;
    esac
done

echo "[pre-run] Project Root : $PROJECT_ROOT"
echo "[pre-run] Config Name  : $CONFIG_NAME"
echo "[pre-run] Run Number   : $RUN_NUMBER"
echo "[pre-run] CWD          : $(pwd)"
echo "[pre-run] Pre-run checks passed, proceeding to simulation."

# exit 1 # to test the flow exiting after pre-run script fails
