#!/usr/bin/env bash
# =============================================================================
# LibreRunSetup.sh
# LibreRun environment setup script.
# Source this script to set PROJECT_ROOT and the 'lr' alias for a session.
#
# Usage:
#   source LibreRunSetup.sh           # auto-detect project from CWD
#   source LibreRunSetup.sh -i        # force interactive project picker
#   source LibreRunSetup.sh -p <path> # explicitly specify project root or env dir
#
# Recommended .bashrc entry:
#   alias lrs='source <absolute path to LibreRunSetup.sh>'
# =============================================================================

# =============================================================================
# USER CONFIGURATION — edit these to match your setup
# =============================================================================
LIBRERUN_FLOW_BASE="$HOME/librerun/flow"
LIBRERUN_PROJECTS_BASE="$HOME/librerun/projects"
PYTHON_PATH="python3"
# =============================================================================

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_lr_print_header() {
    echo ""
    echo "========================================"
    echo "  LibreRun Setup"
    echo "========================================"
    echo ""
}

_lr_resolve_abs() {
    # Resolve an absolute path without using realpath (WSL safe)
    local target="$1"
    echo "$(cd "$target" 2>/dev/null && pwd)"
}

_lr_extract_version() {
    # Extract librerun_version from flow_setup section of base_config.yaml
    # Looks for a line matching '  librerun_version: <value>' (with leading spaces)
    local config_path="$1"
    grep -E '^\s+librerun_version\s*:' "$config_path" \
        | head -n1 \
        | sed 's/.*librerun_version\s*:\s*//' \
        | tr -d "\"'" \
        | tr -d '[:space:]'
}

_lr_set_project() {
    # Given a validated, resolved PROJECT_ROOT, extract version and set env + alias
    local project_root="$1"
    local config="$project_root/env/base_config.yaml"

    local version
    version=$(_lr_extract_version "$config")

    if [[ -z "$version" ]]; then
        echo "[ERROR] Could not extract librerun_version from:"
        echo "        $config"
        echo "        Ensure flow_setup.librerun_version is set in base_config.yaml"
        return 1
    fi

    local flow_script="$LIBRERUN_FLOW_BASE/$version/librerun.py"

    if [[ ! -f "$flow_script" ]]; then
        echo "[ERROR] Flow script not found: $flow_script"
        echo "        Check librerun_version in base_config.yaml and LIBRERUN_FLOW_BASE"
        return 1
    fi

    export PROJECT_ROOT="$project_root"
    alias lr="$PYTHON_PATH $flow_script"

    echo "[OK] Project   : $PROJECT_ROOT"
    echo "[OK] LR Version: $version"
    echo "[OK] Alias 'lr' set."
    echo ""
}

_lr_check_external() {
    # Warn if the project root is outside LIBRERUN_PROJECTS_BASE
    local project_root="$1"
    if [[ "$project_root" != "$LIBRERUN_PROJECTS_BASE"* ]]; then
        echo "[WARNING] Selected project is external to the configured projects base directory:"
        echo "          LIBRERUN_PROJECTS_BASE = $LIBRERUN_PROJECTS_BASE"
        echo "          PROJECT_ROOT           = $project_root"
        echo ""
    fi
}

_lr_interactive_picker() {
    # Scan LIBRERUN_PROJECTS_BASE for valid projects and let user pick one
    echo "Scanning for LibreRun projects in:"
    echo "  $LIBRERUN_PROJECTS_BASE"
    echo ""

    local projects=()
    while IFS= read -r config_file; do
        local project_dir
        project_dir="$(dirname "$(dirname "$config_file")")"
        projects+=("$project_dir")
    done < <(find "$LIBRERUN_PROJECTS_BASE" -mindepth 3 -maxdepth 3 \
                  -path "*/env/base_config.yaml" 2>/dev/null | sort)

    if [[ ${#projects[@]} -eq 0 ]]; then
        echo "[WARNING] No valid LibreRun projects found in $LIBRERUN_PROJECTS_BASE"
        return 1
    fi

    echo "Available projects:"
    local i=1
    for proj in "${projects[@]}"; do
        local name
        name="$(basename "$proj")"
        echo "  [$i] $name  ($proj)"
        ((i++))
    done
    echo "  [e] Exit"
    echo ""

    local choice
    while true; do
        read -rp "Select a project: " choice
        if [[ "$choice" == "e" || "$choice" == "E" ]]; then
            echo "Exiting LibreRunSetup."
            return 1
        elif [[ "$choice" =~ ^[0-9]+$ ]] && \
             [[ "$choice" -ge 1 ]] && \
             [[ "$choice" -le ${#projects[@]} ]]; then
            echo ""
            _lr_set_project "${projects[$((choice - 1))]}"
            return $?
        else
            echo "  Invalid selection, please enter a number between 1 and ${#projects[@]}, or 'e'."
        fi
    done
}

_lr_try_path() {
    # Try to use the given path as a project root or env dir
    local input_path="$1"
    local resolved

    resolved=$(_lr_resolve_abs "$input_path")

    if [[ -z "$resolved" ]]; then
        echo "[ERROR] Path does not exist: $input_path"
        return 1
    fi

    # Case: path is an env directory
    local basename
    basename="$(basename "$resolved")"
    if [[ "$basename" == "env" ]] && [[ -f "$resolved/base_config.yaml" ]]; then
        local project_root
        project_root=$(_lr_resolve_abs "$resolved/..")
        _lr_check_external "$project_root"
        _lr_set_project "$project_root"
        return $?
    fi

    # Case: path is a project root
    if [[ -f "$resolved/env/base_config.yaml" ]]; then
        _lr_check_external "$resolved"
        _lr_set_project "$resolved"
        return $?
    fi

    echo "[ERROR] Path is not a valid project root or env directory:"
    echo "        $resolved"
    echo "        Expected either a project root containing env/base_config.yaml,"
    echo "        or an env directory containing base_config.yaml"
    return 1
}

_lr_try_cwd() {
    # Auto-detect project from CWD
    local cwd
    cwd="$(pwd)"
    local basename
    basename="$(basename "$cwd")"

    # Case 1: CWD is a project root
    if [[ -f "$cwd/env/base_config.yaml" ]]; then
        _lr_check_external "$cwd"
        _lr_set_project "$cwd"
        return $?
    fi

    # Case 2: CWD is the env folder
    if [[ "$basename" == "env" ]] && [[ -f "$cwd/base_config.yaml" ]]; then
        local project_root
        project_root=$(_lr_resolve_abs "$cwd/..")
        _lr_check_external "$project_root"
        _lr_set_project "$project_root"
        return $?
    fi

    # Case 3: Neither — fall through to interactive picker
    echo "[WARNING] CWD is not a valid project root or env directory:"
    echo "          $cwd"
    echo ""
    _lr_interactive_picker
    return $?
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_lr_main() {
    _lr_print_header

    local force_interactive=0
    local explicit_path=""

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -i)
                force_interactive=1
                shift
                ;;
            -p)
                if [[ -z "$2" ]]; then
                    echo "[ERROR] -p requires a path argument"
                    return 1
                fi
                explicit_path="$2"
                shift 2
                ;;
            *)
                echo "[ERROR] Unknown argument: $1"
                echo "Usage: source LibreRunSetup.sh [-i] [-p <path>]"
                return 1
                ;;
        esac
    done

    if [[ "$force_interactive" -eq 1 ]]; then
        _lr_interactive_picker
    elif [[ -n "$explicit_path" ]]; then
        _lr_try_path "$explicit_path"
    else
        _lr_try_cwd
    fi
}

_lr_main "$@"
