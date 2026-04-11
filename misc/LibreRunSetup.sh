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
LIBRERUN_FLOW_BASE="$HOME/LibreRun/flow"
LIBRERUN_PROJECTS_BASE="$HOME/LibreRun/projects"
PYTHON_PATH="python3"
# =============================================================================

# =============================================================================
# ANSI COLORS (mirroring LibreRun Console)
# =============================================================================
C_RESET="\\033[0m"
C_INFO="\\033[38;5;44m"
C_WARNING="\\033[33m"
C_ERROR="\\033[31m"
C_PASS="\\033[32;1m"
C_STRUCT="\\033[38;5;166m"
C_HEADER="\\033[38;5;214m"
C_DIM="\\033[2m"
C_BOLD="\\033[1m"
# =============================================================================

_lr_print_header() {
    echo ""
    echo -e "${C_STRUCT}========================================${C_RESET}"
    echo -e "${C_HEADER}  LibreRun Setup${C_RESET}"
    echo -e "${C_STRUCT}========================================${C_RESET}"
    echo ""
}

_lr_resolve_abs() {
    local target="$1"
    echo "$(cd "$target" 2>/dev/null && pwd)"
}

_lr_extract_version() {
    local config_path="$1"
    local line

    line=$(grep -E '^\s+librerun_version\s*:' "$config_path" | head -n1)
    echo "$line" \
        | sed 's/.*librerun_version\s*:\s*//' \
        | tr -d "\"'" \
        | tr -d '[:space:]'
}

_lr_set_project() {
    local project_root="$1"
    local config="$project_root/env/base_config.yaml"

    local version
    version=$(_lr_extract_version "$config")

    if [[ -z "$version" ]]; then
        echo -e "${C_ERROR}[ERROR]${C_RESET} Could not extract librerun_version from:"
        echo "        $config"
        echo "        Ensure flow_setup.librerun_version is set in base_config.yaml"
        return 1
    fi

    local flow_script="$LIBRERUN_FLOW_BASE/$version/librerun.py"

    if [[ ! -f "$flow_script" ]]; then
        echo -e "${C_ERROR}[ERROR]${C_RESET} Flow script not found: $flow_script"
        echo "        Check librerun_version in base_config.yaml and LIBRERUN_FLOW_BASE"
        return 1
    fi

    export PROJECT_ROOT="$project_root"
    alias lr="$PYTHON_PATH $flow_script"

    echo -e "${C_INFO}[INFO]${C_RESET}    Project : ${C_BOLD}$PROJECT_ROOT${C_RESET}"
    echo -e "${C_INFO}[INFO]${C_RESET}    LR Version : ${C_BOLD}$version${C_RESET}"
    echo -e "${C_INFO}[INFO]${C_RESET}    Alias 'lr' set"
    echo ""
}

_lr_check_external() {
    local project_root="$1"
    if [[ "$project_root" != "$LIBRERUN_PROJECTS_BASE"* ]]; then
        echo -e "${C_WARNING}[WARNING]${C_RESET} Selected project is external to the configured projects base directory:"
        echo "          LIBRERUN_PROJECTS_BASE = $LIBRERUN_PROJECTS_BASE"
        echo "          PROJECT_ROOT           = $project_root"
        echo ""
    fi
}

_lr_interactive_picker() {
    echo -e "${C_INFO}[INFO]${C_RESET}    Scanning for LibreRun projects in:"
    echo "          $LIBRERUN_PROJECTS_BASE"
    echo ""

    local projects=()
    while IFS= read -r config_file; do
        local project_dir
        project_dir="$(dirname "$(dirname "$config_file")")"
        projects+=("$project_dir")
    done < <(find "$LIBRERUN_PROJECTS_BASE" -mindepth 3 -maxdepth 3 -path "*/env/base_config.yaml" 2>/dev/null | sort)

    if [[ ${#projects[@]} -eq 0 ]]; then
        echo -e "${C_WARNING}[WARNING]${C_RESET} No valid LibreRun projects found in $LIBRERUN_PROJECTS_BASE"
        return 1
    fi

    # Compute max project name length for alignment
    local max_len=0
    for proj in "${projects[@]}"; do
        local name
        name="$(basename "$proj")"
        (( ${#name} > max_len )) && max_len=${#name}
    done

    echo -e "    ${C_INFO}Available projects:${C_RESET}"
    local i=0
    for proj in "${projects[@]}"; do
        local name padded
        name="$(basename "$proj")"
        printf -v padded "%-${max_len}s" "$name"

        echo -e "      ${C_STRUCT}[$i]${C_RESET} ${C_BOLD}$padded${C_RESET}  ${C_DIM}($proj)${C_RESET}"
        ((i++))
    done

    echo -e "      ${C_WARNING}[e]${C_RESET} Exit"
    echo ""

    local choice
    while true; do
        echo -ne "    ${C_INFO}Select a project:${C_RESET} "
        read choice
        if [[ "$choice" == "e" || "$choice" == "E" ]]; then
            echo "Exiting LibreRunSetup."
            return 1
        elif [[ "$choice" =~ ^[0-9]+$ ]] && [[ "$choice" -ge 0 ]] && [[ "$choice" -lt ${#projects[@]} ]]; then
            echo ""
            _lr_set_project "${projects[$choice]}"
            return $?
        else
            echo -e "${C_ERROR}[ERROR]${C_RESET} Invalid selection, please enter a number between 0 and $(( ${#projects[@]} - 1 )), or 'e'."
        fi
    done
}

_lr_try_path() {
    local input_path="$1"
    local resolved

    resolved=$(_lr_resolve_abs "$input_path")

    if [[ -z "$resolved" ]]; then
        echo -e "${C_ERROR}[ERROR]${C_RESET} Path does not exist: $input_path"
        return 1
    fi

    local basename
    basename="$(basename "$resolved")"

    if [[ "$basename" == "env" ]] && [[ -f "$resolved/base_config.yaml" ]]; then
        local project_root
        project_root=$(_lr_resolve_abs "$resolved/..")
        _lr_check_external "$project_root"
        _lr_set_project "$project_root"
        return $?
    fi

    if [[ -f "$resolved/env/base_config.yaml" ]]; then
        _lr_check_external "$resolved"
        _lr_set_project "$resolved"
        return $?
    fi

    echo -e "${C_ERROR}[ERROR]${C_RESET} Path is not a valid project root or env directory:"
    echo "        $resolved"
    echo "        Expected either a project root containing env/base_config.yaml,"
    echo "        or an env directory containing base_config.yaml"
    return 1
}

_lr_try_cwd() {
    local cwd
    cwd="$(pwd)"
    local basename
    basename="$(basename "$cwd")"

    if [[ -f "$cwd/env/base_config.yaml" ]]; then
        _lr_check_external "$cwd"
        _lr_set_project "$cwd"
        return $?
    fi

    if [[ "$basename" == "env" ]] && [[ -f "$cwd/base_config.yaml" ]]; then
        local project_root
        project_root=$(_lr_resolve_abs "$cwd/..")
        _lr_check_external "$project_root"
        _lr_set_project "$project_root"
        return $?
    fi

    echo -e "${C_WARNING}[WARNING]${C_RESET} CWD is not a valid project root or env directory:"
    echo "          $cwd"
    echo ""
    _lr_interactive_picker
    return $?
}

_lr_main() {
    _lr_print_header

    local force_interactive=0
    local explicit_path=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -i)
                force_interactive=1
                shift
                ;;
            -p)
                if [[ -z "$2" ]]; then
                    echo -e "${C_ERROR}[ERROR]${C_RESET} -p requires a path argument"
                    return 1
                fi
                explicit_path="$2"
                shift 2
                ;;
            *)
                echo -e "${C_ERROR}[ERROR]${C_RESET} Unknown argument: $1"
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
