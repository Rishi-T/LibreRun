#!/usr/bin/env python3
"""
LibreRun v0.4
Verilator-based SystemVerilog simulation flow.
"""

import argparse
import getpass
import sys
from pathlib import Path

# Extend path so extensions/ is importable
_FLOW_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_FLOW_DIR / "extensions"))

from librerun_utils import (
    C, Console, ConfigHandler,
    ensure_dir, read_last_config, write_last_invocation,
    LOGS_DIR, TEMP_DIR, BASE_CONFIG, SIMOUT_DIR, EXE_DIR, SIM_RUNS_DIR, REGRESS_RUNS_DIR,
    _early_fatal,
)
from verilator_extension import VerilatorExtension
from filelist_extension  import FilelistExtension

VERSION = "v0.4.RC"

# =============================================================================
# Tool registry
# =============================================================================

TOOL_REGISTRY: dict[str, object] = {
    "verilator": VerilatorExtension(),
    "filelist":  FilelistExtension(),
}

# =============================================================================
# Argument parsing
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LibreRun — RTL Simulation Flow",
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=True,
    )
    parser.add_argument("-c",   "--compile",           action="store_true",
                        help="Invoke Verilator compile")
    parser.add_argument("-cfg", "--config",            default=None, metavar="NAME",
                        help="Supplementary config name (no .yaml). Defaults to last used or base_config.")
    parser.add_argument("-r",   "--run",               nargs="?", const="default", default=None, metavar="TEST",
                        help="Run simulation with optional test name (default: 'default')")
    parser.add_argument("-rg",  "--regress",           nargs="+", default=None, metavar="SUITE",
                        help="Run regression suites (space-separated suite names)")
    parser.add_argument("-w",   "--waves",             action="store_true",
                        help="Enable FST waveform dump during simulation")
    parser.add_argument("-g",   "--gui",               action="store_true",
                        help="Enable FST dump and launch GTKWave (implies --waves)")
    parser.add_argument("-s",   "--seed",              default=None, type=int, metavar="N",
                        help="Override simulation seed (0 = random)")
    parser.add_argument("-p",   "--plusargs",          nargs="+", default=[], metavar="ARG",
                        help="Extra plusargs (space-separated, no leading '+' needed)")
    parser.add_argument("-l",   "--lint",              action="store_true",
                        help="Run Verilator lint-only check")
    parser.add_argument("-flg", "--filelist_gen",      action="store_true",
                        help="Invoke RTL filelist generator")
    parser.add_argument("-flo", "--filelist_optimize", action="store_true",
                        help="Prune unreachable files from generated filelists (use with -flg)")
    parser.add_argument("-v",   "--verbose",           action="store_true",
                        help="Enable verbose/debug output to console")
    return parser.parse_args()

# =============================================================================
# Environment helpers
# =============================================================================

def get_project_root() -> Path:
    import os
    root = os.environ.get("PROJECT_ROOT")
    if not root:
        _early_fatal("PROJECT_ROOT is not set. Please source LibreRunSetup.sh first.")
    path = Path(root)
    if not path.is_dir():
        _early_fatal(f"PROJECT_ROOT does not exist or is not a directory: {path}")
    return path.resolve()

# =============================================================================
# Arg resolution (mutate args against config)
# =============================================================================

def resolve_args(args: argparse.Namespace, config: dict) -> argparse.Namespace:
    """
    Apply config-driven overrides to args.
    Extensions should only ever read args — this is the single place
    where config influences arg values.
    """
    cfg_get = ConfigHandler.cfg_get
    flow    = cfg_get(config, "flow_setup", default={})

    if cfg_get(flow, "always_lint"):
        args.lint = True

    # gui implies waves
    if args.gui:
        args.waves = True

    return args

# =============================================================================
# Task resolution
# =============================================================================

def resolve_tasks(args: argparse.Namespace) -> list[str]:
    """
    Build the ordered task list from resolved args.
    Order: filelist_gen → lint → compile → run / regress
    """
    if args.run is not None and args.regress is not None:
        _early_fatal("Cannot use --run and --regress together.")

    tasks = []
    if args.filelist_gen: tasks.append("filelist_gen")
    if args.lint:         tasks.append("lint")
    if args.compile:      tasks.append("compile")
    if args.run is not None:
        tasks.append("run")
    if args.regress is not None:
        tasks.append("regress")
    return tasks

# =============================================================================
# Tool resolution
# =============================================================================

def resolve_extension(task: str, config: dict) -> object:
    """
    Map a task to its registered extension.
    Today tool selection is implicit (only Verilator exists).
    When multi-tool support is added, tool_setup.compile_and_run_tool
    will drive this lookup.
    """
    cfg_get    = ConfigHandler.cfg_get
    tool_setup = cfg_get(config, "tool_setup", default={})

    if task == "filelist_gen":
        return TOOL_REGISTRY["filelist"]

    # compile_and_run_tool drives lint/compile/run/regress (default: verilator)
    tool = tool_setup.get("compile_and_run_tool", "verilator").lower()
    if tool not in TOOL_REGISTRY:
        _early_fatal(f"Unknown tool '{tool}' specified in tool_setup.compile_and_run_tool.")
    return TOOL_REGISTRY[tool]

# =============================================================================
# Main
# =============================================================================

def main():
    args         = parse_args()
    project_root = get_project_root()
    user         = getpass.getuser()

    ensure_dir(project_root / LOGS_DIR)
    ensure_dir(project_root / TEMP_DIR)

    # Resolve config name
    config_name = args.config if args.config else read_last_config(project_root, user)

    # Load + merge config (once, shared with all extensions via context)
    config_handler = ConfigHandler(project_root, config_name)
    config         = config_handler.config
    cfg_get        = ConfigHandler.cfg_get

    # Console — created once, passed to all extensions via context
    console = Console(project_root, user, args, VERSION, verbose=args.verbose)
    console.print_header(VERSION)

    lr_version = cfg_get(config, "flow_setup", "librerun_version", default="")
    if "RC" in str(lr_version).upper() or "RC" in VERSION.upper():
        console.warning("This is a pre-release (RC) version of LibreRun and may be unstable.")
        console.blank()

    proj_name = cfg_get(config, "project_configuration", "project_name", default="<unnamed>")
    console.info(f"Project : {C.BOLD}{proj_name}{C.RESET}")
    console.info(f"Config  : {C.BOLD}{config_name}{C.RESET}")
    console.info(f"Root    : {C.BOLD}{project_root}{C.RESET}")
    console.blank()

    if not args.config:
        console.info(f"No --config specified, using last: '{C.BOLD}{config_name}{C.RESET}'")

    console.log_only(f"Project : {proj_name}")
    console.log_only(f"Config  : {config_name}")

    # Resolve args against config, then tasks, then extensions
    args  = resolve_args(args, config)
    tasks = resolve_tasks(args)

    if not tasks:
        console.info(
            "No action requested. "
            "Use -c, -r, -rg, -l, -flg, or -h for help.\n"
        )
        console.close()
        return

    # Ensure standard output directories exist before dispatch
    ensure_dir(project_root / SIMOUT_DIR / config_name / EXE_DIR)
    ensure_dir(project_root / SIMOUT_DIR / config_name / SIM_RUNS_DIR)
    ensure_dir(project_root / SIMOUT_DIR / config_name / REGRESS_RUNS_DIR)

    # Build shared context — extensions receive this, nothing else
    context = {
        "config":  config,   # read-only by convention
        "args":    args,
        "paths": {
            "project_root": project_root,
            "config_name":  config_name,
        },
        "console": console,
    }

    # Dispatch loop
    try:
        for task in tasks:
            ext = resolve_extension(task, config)
            ext.run(task, context)
    finally:
        console.blank()
        # Final completion banner (printed for all non-fatal exits)
        console.banner("LibreRun Invocation Complete")
        console.blank()
        console.close()
        write_last_invocation(project_root, user, config_name, args)


if __name__ == "__main__":
    main()
