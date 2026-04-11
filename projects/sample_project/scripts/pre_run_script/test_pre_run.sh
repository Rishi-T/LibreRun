#!/usr/bin/env bash

# Parse flow-mandated args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-root) PROJECT_ROOT="$2"; shift 2 ;;
        --config-name)  CONFIG_NAME="$2";  shift 2 ;;
        --run-number)   RUN_NUMBER="$2";   shift 2 ;;
        --test)         TEST_NAME="$2";    shift 2 ;;
        --seed)         SEED="$2";         shift 2 ;;
        --suite)        SUITE="$2";        shift 2 ;;
        --regress)      REGRESS="$2";      shift 2 ;;
        *) echo "Unknown arg: $1"; shift ;;
    esac
done

echo "[pre-run] Project Root : $PROJECT_ROOT"
echo "[pre-run] Config Name  : $CONFIG_NAME"
echo "[pre-run] Run Number   : $RUN_NUMBER"
echo "[pre-run] Test Name    : $TEST_NAME"
echo "[pre-run] Seed         : $SEED"
echo "[pre-run] Suite        : $SUITE"
echo "[pre-run] Regress Mode : $REGRESS"
echo "[pre-run] CWD          : $(pwd)"

# Conditional logic example:
if [[ "$REGRESS" == "true" ]]; then
    echo "[pre-run] Running in regression mode for suite: $SUITE, test: $TEST_NAME"
else
    echo "[pre-run] Running single simulation for test: $TEST_NAME"
fi

echo "[pre-run] Pre-run checks passed, proceeding to simulation."

# exit 1 # to test the flow exiting after pre-run script fails
