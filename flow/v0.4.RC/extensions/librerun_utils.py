"""
librerun_utils.py
Shared utilities for LibreRun and its extensions:
  - ANSI color constants (C)
  - Console (unified output + file logging)
  - ConfigHandler (load, merge, expand)
  - Shared path helpers and duration formatting
  - Generic simulation utilities (seed generation, log parsing, plusargs)
  - Generic regression orchestration framework
"""

import argparse
import os
import re
import sys
import yaml
import random
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

# =============================================================================
# Constants (shared across LibreRun + extensions)
# =============================================================================

BASE_CONFIG      = "base_config"
LAST_INV_PREFIX  = "."
LAST_INV_SUFFIX  = "_last_invocation"
SIMOUT_DIR       = "simout"
EXE_DIR          = "exe"
SIM_RUNS_DIR     = "sim_runs"
REGRESS_RUNS_DIR = "regress_runs"
BASE_RUN_DIR     = Path("scripts") / "librerun"
LOGS_DIR         = BASE_RUN_DIR / "logs"
TEMP_DIR         = BASE_RUN_DIR / "temp"

# =============================================================================
# ANSI Color Codes
# =============================================================================

class C:
    """ANSI color constants."""
    RESET       = "\033[0m"
    STRUCT      = "\033[38;5;166m"   # darker orange — structural/dividers
    HEADER_TEXT = "\033[38;5;214m"   # lighter orange — banner text
    INFO        = "\033[38;5;44m"    # cyan
    WARNING     = "\033[33m"         # yellow
    ERROR       = "\033[31m"         # red
    FATAL       = "\033[31;1m"       # bold red
    DEBUG       = "\033[2m"          # dim
    PASS        = "\033[32;1m"       # bold green
    FAIL        = "\033[31;1m"       # bold red
    DIM         = "\033[2m"
    BOLD        = "\033[1m"

_ANSI_RE = re.compile(r'\033\[[0-9;]*m')

def strip_ansi(text: str) -> str:
    """Remove ANSI color codes from text."""
    return _ANSI_RE.sub('', text)

# =============================================================================
# Console
# =============================================================================

class Console:
    """
    Unified console + file logger.

    Responsibilities:
    - Severity-based logging (info / warning / error / fatal / debug)
    - Structural formatting (banners, headers, dividers)
    - Terminal-width-aware rendering (dynamic width, centered text)

    Structural methods:
      banner / raw / print_only / log_only / blank
    """

    _INDENT = " " * 10  # matches widest tag width: "[WARNING] "

    def __init__(self, project_root: Path, user: str,
                 args: argparse.Namespace, version: str,
                 verbose: bool = False):
        log_dir = project_root / LOGS_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path    = log_dir / f"{user}_{ts}.log"
        self.verbose = verbose
        self._f      = open(self.path, "w")
        self._write_header(user, version, args)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write_header(self, user: str, version: str, args: argparse.Namespace):
        lines = [
            f"LibreRun {version}",
            f"User      : {user}",
            f"Timestamp : {datetime.now().isoformat()}",
            f"Args      : {sys.argv}",
            "=" * 75,
            "",
        ]
        self._f.write("\n".join(lines) + "\n")
        self._f.flush()

    def _log(self, text: str):
        if self._f and not self._f.closed:
            self._f.write(strip_ansi(text) + "\n")
            self._f.flush()

    def _print(self, text: str):
        print(text)

    def _get_render_width(self) -> int:
        """
        Determine usable render width for structural elements.

        - Uses current terminal width (with fallback)
        - Clamps to a maximum width for readability
        - Enforces a minimum width for very small terminals
        """
        import shutil
        term_width = shutil.get_terminal_size(fallback=(120, 24)).columns
        MAX_WIDTH  = 100
        MIN_WIDTH  = 40
        return max(MIN_WIDTH, min(term_width, MAX_WIDTH)) - 2

    def _format_structural_line(self, text: str = "", char: str = "=", align: str = "center") -> str:
        """
        Render a structural line (banner/divider) with optional centered text.

        Behavior:
        - Expands to terminal width (clamped via _get_render_width)
        - Centers text with padding when space allows
        - Falls back to plain text if terminal is too narrow
        - ANSI-safe (uses visible text width, ignores color codes)

        Args:
            text:  Optional label to embed in the line
            char:  Fill character (e.g., '=', '~')
            align: Currently supports 'center'
        """
        width = self._get_render_width()

        visible_len = len(strip_ansi(text))
        pad = 2 if text else 0  # spacing around text

        if not text:
            return f"{C.STRUCT}{char * width}{C.RESET}"

        # If too small, fallback (no centering)
        if width <= visible_len + pad:
            return f"{C.HEADER_TEXT}{text}{C.RESET}"

        remaining = width - visible_len - pad

        if align == "center":
            left  = remaining // 2
            right = remaining - left
        else:
            left, right = 0, remaining

        return (
            f"{C.STRUCT}{char * left}{C.RESET}"
            f"{C.HEADER_TEXT}{' ' if pad else ''}{text}{' ' if pad else ''}{C.RESET}"
            f"{C.STRUCT}{char * right}{C.RESET}"
        )

    def _fmt_ml(self, color: str, tag: str, pad: str, msg_text: str) -> str:
        import shutil
        import textwrap
        term_width = shutil.get_terminal_size(fallback=(120, 24)).columns
        wrap_width = max(term_width - len(self._INDENT) - 2, 20)

        leading  = len(msg_text) - len(msg_text.lstrip("\n"))
        trailing = len(msg_text) - len(msg_text.rstrip("\n"))

        wrapped: list[str] = []
        for logical_line in msg_text.strip("\n").splitlines():
            wrapped.extend(textwrap.wrap(logical_line, width=wrap_width) or [""])

        first = f"{color}{tag}{C.RESET}{pad}{wrapped[0]}"
        rest  = [f"{self._INDENT}{l}" for l in wrapped[1:]]
        body  = "\n".join([first] + rest)
        return "\n" * leading + body + "\n" * trailing

    # ------------------------------------------------------------------
    # Severity methods
    # ------------------------------------------------------------------

    def msg(self, text: str, *, print_: bool = True, log_: bool = True):
        if print_: self._print(text)
        if log_:   self._log(text)

    def info(self, msg_text: str, *, print_: bool = True, log_: bool = True):
        self.msg(self._fmt_ml(C.INFO, "[INFO]", "    ", msg_text),
                 print_=print_, log_=log_)

    def warning(self, msg_text: str, *, print_: bool = True, log_: bool = True):
        self.msg(self._fmt_ml(C.WARNING, "[WARNING]", " ", msg_text),
                 print_=print_, log_=log_)

    def error(self, msg_text: str, *, print_: bool = True, log_: bool = True):
        self.msg(self._fmt_ml(C.ERROR, "[ERROR]", "   ", msg_text),
                 print_=print_, log_=log_)

    def fatal(self, msg: str):
        """Print fatal error and exit. Does NOT close log file (main's finally handles that)."""
        self.error(msg)
        self.log_only("[FATAL] Exiting due to fatal error.")
        sys.exit(1)

    def debug(self, msg_text: str, *, log_: bool = True):
        """Always written to log. Printed to console only if verbose=True."""
        formatted = self._fmt_ml(C.DEBUG, "[DEBUG]", "   ", msg_text)
        if self.verbose:
            self._print(formatted)
        if log_:
            self._log(formatted)

    # ------------------------------------------------------------------
    # Structural / formatting
    # ------------------------------------------------------------------

    def banner(self, text: str):
        """
        Section divider with centered label — printed and logged.

        Uses terminal-width-aware formatting and shared structural renderer.
        """
        self.msg(self._format_structural_line(char="="))
        self.msg(self._format_structural_line(text, char="="))
        self.msg(self._format_structural_line(char="="))

    def divider(self, char: str = "=", width: int = 75):
        self.msg(f"{C.STRUCT}{char * width}{C.RESET}")

    def header_line(self, text: str):
        self.msg(f"{C.HEADER_TEXT}{text}{C.RESET}")

    def raw(self, text: str, *, print_: bool = True, log_: bool = True):
        """Bypass all formatting — output text exactly as given."""
        if print_: self._print(text)
        if log_:   self._log(text)

    def print_only(self, text: str):
        self._print(text)

    def log_only(self, text: str):
        self._log(text)

    def blank(self):
        self.msg("")

    def close(self):
        if self._f and not self._f.closed:
            self._f.close()

    # ------------------------------------------------------------------
    # Program header
    # ------------------------------------------------------------------

    def print_header(self, version: str):
        """
        Print top-level LibreRun header.

        Rendered using dynamic width with centered title.
        """
        self.blank()
        self.raw(self._format_structural_line(char="="))
        self.raw(self._format_structural_line(f"LibreRun {version}  |  RTL Simulation Flow", char="="))
        self.raw(self._format_structural_line(char="="))
        self.blank()


def _early_fatal(msg_text: str):
    """Module-level fatal used before a Console instance is available."""
    print(f"{C.FATAL}[FATAL]{C.RESET}   {msg_text}")
    sys.exit(1)

# =============================================================================
# ConfigHandler
# =============================================================================

class ConfigHandler:
    """
    Loads, merges, and expands the project config.

    Usage (once, in librerun.py):
        cfg = ConfigHandler(project_root, config_name).config
    """

    def __init__(self, project_root: Path, config_name: str):
        self.project_root = project_root
        self.config_name  = config_name
        self.config       = self._load(project_root, config_name)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    @staticmethod
    def cfg_get(config: dict, *keys, default=None):
        """Safe nested key access."""
        node = config
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node if node is not None else default

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _load_yaml(path: Path) -> dict:
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}

    @staticmethod
    def _expand_env_vars(obj):
        if isinstance(obj, dict):
            return {k: ConfigHandler._expand_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [ConfigHandler._expand_env_vars(v) for v in obj]
        elif isinstance(obj, str):
            return os.path.expandvars(obj)
        return obj

    @staticmethod
    def _merge(base: dict, override: dict) -> dict:
        result = dict(base)
        for key, val in override.items():
            if key in result:
                if isinstance(result[key], list) and isinstance(val, list):
                    result[key] = result[key] + val
                elif isinstance(result[key], dict) and isinstance(val, dict):
                    result[key] = ConfigHandler._merge(result[key], val)
                else:
                    result[key] = val
            else:
                result[key] = val
        return result

    def _load(self, project_root: Path, config_name: str) -> dict:
        env_dir   = project_root / "env"
        base_path = env_dir / "base_config.yaml"

        if not base_path.exists():
            _early_fatal(f"base_config.yaml not found at: {base_path}")

        base = self._expand_env_vars(self._load_yaml(base_path))
        if config_name == BASE_CONFIG:
            return base

        supp_path = env_dir / f"{config_name}.yaml"
        if not supp_path.exists():
            _early_fatal(f"Supplementary config not found: {supp_path}")

        supp      = self._expand_env_vars(self._load_yaml(supp_path))
        supp_flow = supp.get("flow_setup", {})
        if "librerun_version" in supp_flow:
            print(f"{C.WARNING}[WARNING]{C.RESET} "
                  f"'librerun_version' in supplementary config '{config_name}' is ignored.")
            del supp_flow["librerun_version"]

        return self._merge(base, supp)

# =============================================================================
# Shared path helpers
# =============================================================================

def ensure_dir(path: Path):
    """Create directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)

def config_simout(project_root: Path, config_name: str) -> Path:
    """Return simout directory for a config."""
    return project_root / SIMOUT_DIR / config_name

def exe_dir(project_root: Path, config_name: str) -> Path:
    """Return exe directory for a config."""
    return config_simout(project_root, config_name) / EXE_DIR

def next_run_dir(project_root: Path, config_name: str, test: str) -> tuple[Path, int]:
    """
    Create next run directory: sim_runs/<test>/run_<N>/
    Returns: (run_dir_path, run_number)
    """
    import re as _re
    sim_runs = config_simout(project_root, config_name) / SIM_RUNS_DIR / test
    ensure_dir(sim_runs)
    existing = sorted(sim_runs.glob("run_*"))
    next_n   = 1
    if existing:
        nums   = [int(m.group(1)) for d in existing
                  if (m := _re.match(r"run_(\d+)$", d.name))]
        next_n = max(nums) + 1 if nums else 1
    run_dir = sim_runs / f"run_{next_n}"
    ensure_dir(run_dir)
    return run_dir, next_n

def next_regress_run_dir(project_root: Path, config_name: str) -> tuple[Path, int]:
    """
    Create next regression run directory: regress_runs/run_<N>/
    Returns: (run_dir_path, run_number)
    """
    import re as _re
    regress_runs = config_simout(project_root, config_name) / REGRESS_RUNS_DIR
    ensure_dir(regress_runs)
    existing = sorted(regress_runs.glob("run_*"))
    next_n   = 1
    if existing:
        nums   = [int(m.group(1)) for d in existing
                  if (m := _re.match(r"run_(\d+)$", d.name))]
        next_n = max(nums) + 1 if nums else 1
    run_dir = regress_runs / f"run_{next_n}"
    ensure_dir(run_dir)
    return run_dir, next_n

def last_inv_path(project_root: Path, user: str) -> Path:
    """Return path to last invocation file."""
    return project_root / TEMP_DIR / f"{LAST_INV_PREFIX}{user}{LAST_INV_SUFFIX}"

def read_last_config(project_root: Path, user: str) -> str:
    """Read config name from last invocation file."""
    path = last_inv_path(project_root, user)
    if not path.exists():
        return BASE_CONFIG
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return data.get("config", BASE_CONFIG)
    except Exception:
        return BASE_CONFIG

def write_last_invocation(project_root: Path, user: str,
                          config_name: str, args: argparse.Namespace):
    """Write last invocation details to file."""
    path   = last_inv_path(project_root, user)
    ensure_dir(path.parent)
    record = {
        "timestamp":          datetime.now().isoformat(),
        "config":             config_name,
        "compile":            args.compile,
        "run":                args.run,
        "waves":              args.waves,
        "gui":                args.gui,
        "seed":               args.seed,
        "plusargs":           args.plusargs,
        "lint":               args.lint,
        "filelist_gen":       args.filelist_gen,
        "filelist_optimize":  args.filelist_optimize,
    }
    with open(path, "w") as f:
        yaml.dump(record, f, default_flow_style=False)

# =============================================================================
# Duration formatting
# =============================================================================

def fmt_duration(delta) -> str:
    """Format a timedelta as a human-readable duration string."""
    total_ms = int(delta.total_seconds() * 1000)
    if total_ms < 1000:      return f"{total_ms}ms"
    elif total_ms < 60000:   return f"{total_ms / 1000:.2f}s"
    elif total_ms < 3600000: return f"{total_ms / 60000:.2f}m"
    else:                    return f"{total_ms / 3600000:.2f}h"

# =============================================================================
# Extension interface
# =============================================================================

class LibreRunExtension:
    """
    Base interface for all LibreRun extensions.
    Each extension must declare which tasks it provides
    and implement run(task, context).
    """
    name: str = ""

    def provides(self) -> list[str]:
        raise NotImplementedError

    def run(self, task: str, context: dict):
        raise NotImplementedError

# =============================================================================
# Hook runner
# =============================================================================

def run_hook(hook_name: str, script_str: str, cwd: Path,
             flow_args: dict, console, silent: bool = False,
             generate_log: bool = True) -> bool:
    """
    Execute a user-defined hook script with flow-appended arguments.
    Returns True on success, False on failure.

    Args:
        hook_name: Display name (e.g., "Pre-Run Script")
        script_str: Command string to execute
        cwd: Working directory for execution
        flow_args: Dictionary of flow-related arguments to append
        console: Console object for logging
        silent: If True, suppress start/end banners and success message
        generate_log: If True, write output to a log file
    """
    import shlex, subprocess

    log_name = hook_name.lower().replace(" ", "_").replace("-", "_") + ".log"
    log_path = cwd / log_name

    # Build command: user string + flow-mandated args
    cmd = shlex.split(script_str)
    for flag, value in flow_args.items():
        cmd += [flag, str(value)]

    # Structural banners use Console formatter (terminal-width aware)
    if not silent:
        console.msg("")
        console.msg(console._format_structural_line(f"Starting {hook_name}", char="~"))
        console.msg("")

    t_start = datetime.now()

    if generate_log:
        with open(log_path, "w") as log_f:
            proc = subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, cwd=str(cwd))
            for line in proc.stdout:
                if not silent:
                    print(line, end="")
                log_f.write(line)
            proc.wait()
    else:
        # No log file, just run silently
        proc = subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, cwd=str(cwd))
        for line in proc.stdout:
            if not silent:
                print(line, end="")
        proc.wait()

    duration = fmt_duration(datetime.now() - t_start)

    if not silent:
        console.msg("")
        console.msg(console._format_structural_line(f"Exiting {hook_name}", char="~"))
        console.msg("")

    if proc.returncode != 0:
        if not silent:
            console.error(f"{C.FAIL}{hook_name} failed.{C.RESET} ({duration})\nLog : {C.BOLD}{log_path}{C.RESET}")
        return False
    else:
        if not silent:
            console.info(f"{C.PASS}{hook_name} completed successfully.{C.RESET} ({duration})\nLog : {C.BOLD}{log_path}{C.RESET}")
        return True

# =============================================================================
# Generic Simulation Utilities (Tool-Agnostic)
# =============================================================================

def generate_unique_seed(used_seeds: set[int]) -> int:
    """
    Generate a unique random seed for simulation.

    Args:
        used_seeds: Set of already-used seeds (will be updated)

    Returns:
        A unique seed in range [1, 2^31-1]
    """
    while True:
        seed = random.randint(1, 2**31 - 1)
        if seed not in used_seeds:
            used_seeds.add(seed)
            return seed

def resolve_simulation_seed(args, config: dict) -> int:
    """
    Resolve simulation seed with priority: CLI arg → config → random.
    Handles special case where seed=0 means "generate random".

    Args:
        args: CLI arguments (must have .seed attribute)
        config: Project configuration

    Returns:
        Resolved seed value (1 to 2^31-1)
    """
    simopts = ConfigHandler.cfg_get(config, "simulation_options", default={})

    # Priority 1: CLI argument
    if args.seed is not None:
        if args.seed == 0:
            # Special case: -s 0 means "generate random"
            return random.randint(1, 2**31 - 1)
        else:
            return args.seed

    # Priority 2: Config setting
    cfg_seed = ConfigHandler.cfg_get(simopts, "seed")
    if cfg_seed is not None and cfg_seed != 0:
        return cfg_seed

    # Priority 3: Random generation
    return random.randint(1, 2**31 - 1)


def parse_simulation_log(log_path: Path, config: dict) -> bool:
    """
    Generic pass/fail detection for Verilog simulation logs.

    Checks for:
    - Standard Verilog system tasks: $error, $fatal, %error, %fatal
    - User-defined error keywords from config (tb_configuration.error_keywords)

    Args:
        log_path: Path to simulation log file
        config: Project configuration dictionary

    Returns:
        True if simulation passed (no errors detected), False otherwise
    """
    tb = ConfigHandler.cfg_get(config, "tb_configuration", default={})
    error_keywords = [k.lower() for k in ConfigHandler.cfg_get(tb, "error_keywords", default=[])]

    try:
        with open(log_path, "r") as f:
            for line in f:
                line_lower = line.lower()

                # Standard Verilog error patterns (IEEE 1800-2017)
                if "%error" in line_lower or "$error" in line_lower:
                    return False
                if "%fatal" in line_lower or "$fatal" in line_lower:
                    return False

                # User-defined error keywords
                for keyword in error_keywords:
                    if keyword in line_lower:
                        return False
    except OSError:
        # If we can't read the log, assume failure
        return False

    return True


class SimulatorPlusargs:
    """
    Generic plusarg builder for Verilog simulators.

    Handles:
    - Tool-specific plusargs (error limits, seed injection)
    - Generic test name injection
    - Persistent plusargs from config
    - Test-level plusargs (common to all variants)
    - Variant-specific plusargs
    - User-provided plusargs from CLI
    """

    def __init__(self, tool_prefix: str):
        """
        Args:
            tool_prefix: Tool name for prefixed plusargs (e.g., "verilator", "icarus")
                        Used for: +{tool_prefix}+error+limit+N, +{tool_prefix}+seed+N
        """
        self.tool_prefix = tool_prefix

    def build_plusargs(self, simopts: dict, args, test: str, seed: int,
                      test_plusargs: list[str] = None,
                      variant_plusargs: list[str] = None) -> tuple[list[str], dict]:
        """
        Build plusargs list and metadata for simulation command.

        Args:
            simopts: simulation_options section from config
            args: CLI arguments (containing user plusargs)
            test: Test name to inject
            seed: Seed value to inject
            test_plusargs: Test-level plusargs (common to all variants)
            variant_plusargs: Variant-specific plusargs

        Returns:
            Tuple of (plusargs_list, metadata_dict)
            - plusargs_list: List of plusarg strings to append to command
            - metadata_dict: Dict with keys 'persistent', 'test', 'variant', 'user', 'injected'
        """
        plusargs = []
        persistent_plusargs = []
        test_level_plusargs = []
        variant_level_plusargs = []
        user_plusargs = []
        injected_plusargs = []

        # Tool-specific error limit (if configured)
        error_limit = ConfigHandler.cfg_get(simopts, "error_limit")
        if error_limit is not None:
            arg = f"+{self.tool_prefix}+error+limit+{error_limit}"
            plusargs.append(arg)
            injected_plusargs.append(arg)

        # Tool-specific seed (always inject)
        seed_arg = f"+{self.tool_prefix}+seed+{seed}"
        plusargs.append(seed_arg)
        injected_plusargs.append(seed_arg)

        # Generic test name (standard convention)
        test_arg = f"+test={test}"
        plusargs.append(test_arg)
        injected_plusargs.append(test_arg)

        # Persistent plusargs from config (always applied)
        for pa in ConfigHandler.cfg_get(simopts, "persistent_plusargs", default=[]):
            arg = f"+{pa.lstrip('+')}"
            plusargs.append(arg)
            persistent_plusargs.append(arg)

        # Test-level plusargs (common to all variants of this test)
        if test_plusargs:
            for pa in test_plusargs:
                arg = f"+{pa.lstrip('+')}"
                plusargs.append(arg)
                test_level_plusargs.append(arg)

        # Variant-specific plusargs
        if variant_plusargs:
            for pa in variant_plusargs:
                arg = f"+{pa.lstrip('+')}"
                plusargs.append(arg)
                variant_level_plusargs.append(arg)

        # User plusargs from CLI (highest precedence)
        for pa in args.plusargs:
            arg = f"+{pa.lstrip('+')}"
            plusargs.append(arg)
            user_plusargs.append(arg)

        metadata = {
            "persistent": persistent_plusargs,
            "test": test_level_plusargs,
            "variant": variant_level_plusargs,
            "user": user_plusargs,
            "injected": injected_plusargs
        }

        return plusargs, metadata

# =============================================================================
# Generic Regression Framework
# =============================================================================

class RegressionRunner:
    """
    Generic regression orchestration framework for Verilog simulators.

    Provides complete regression infrastructure:
    - Suite expansion (suites → tests → jobs with seeds)
    - Parallel execution with configurable worker pool
    - Live Rich table display with real-time updates
    - Pre-run script execution (per-suite, per-test, or per-count)
    - Metadata generation and incremental writes
    - Pass/fail detection with configurable cleanup
    - Interrupt handling (CTRL+C)

    Tool-specific behavior (command building) is delegated via callback.
    """

    def __init__(self,
                 config: dict,
                 console: Console,
                 project_root: Path,
                 config_name: str,
                 tool_prefix: str):
        """
        Args:
            config: Loaded project configuration
            console: Console instance for logging
            project_root: Project root directory
            config_name: Active configuration name
            tool_prefix: Tool identifier (kept for future use, currently unused)
        """
        self.config = config
        self.con = console
        self.project_root = project_root
        self.config_name = config_name
        self.tool_prefix = tool_prefix

    def run_regression(self,
                  binary: Path,
                  args,
                  regress_run_dir: Path,
                  regress_run_num: int,
                  build_command: Callable[[Path, 'args', str, int, list[str], list[str]], tuple[list[str], list[str], list[str], list[str], list[str]]]):
        """
        Main regression orchestration entry point.

        Args:
            binary: Path to compiled simulator binary
            args: CLI arguments (must have .regress and .plusargs attributes)
            regress_run_dir: Directory for this regression run
            regress_run_num: Regression run number
            build_command: Callback function (binary, args, test, seed, test_plusargs, variant_plusargs)
                          -> (cmd, user_plusargs, injected_plusargs, test_plusargs, variant_plusargs)
                          Tool-specific command builder
        """

        # Load configuration sections
        suites_cfg = ConfigHandler.cfg_get(self.config, "regression_suites", default={})
        regress_opts = ConfigHandler.cfg_get(self.config, "regression_options", default={})
        simopts = ConfigHandler.cfg_get(self.config, "simulation_options", default={})

        # Parse regression options
        max_parallel = int(ConfigHandler.cfg_get(regress_opts, "max_parallel", default=4))
        keep_passing = bool(ConfigHandler.cfg_get(regress_opts, "keep_passing", default=False))
        keep_failing = bool(ConfigHandler.cfg_get(regress_opts, "keep_failing", default=True))
        gen_prs_logs = bool(ConfigHandler.cfg_get(regress_opts, "generate_prs_logs", default=True))
        prs_per_test = bool(ConfigHandler.cfg_get(regress_opts, "prs_per_test", default=True))
        prs_per_count = bool(ConfigHandler.cfg_get(regress_opts, "prs_per_count", default=False))
        pre_run_script = ConfigHandler.cfg_get(simopts, "pre_run_script", default="").strip()

        suite_names = args.regress

        # Validate requested suites exist
        for suite in suite_names:
            if suite not in suites_cfg:
                self.con.fatal(f"Regression suite '{suite}' not found in config.")

        # Expand suites → tests → jobs
        jobs = self._expand_jobs(suite_names, suites_cfg, regress_run_dir)

        if not jobs:
            self.con.info("No jobs to run after suite expansion.")
            return

        # Initialize run metadata
        run_meta = self._init_metadata(suite_names, jobs, regress_run_dir, regress_run_num)

        # Initialize display state tracking
        display_state = self._init_display_state(suite_names, jobs)

        # Track suite completion for incremental metadata writes
        suite_completed_jobs = {s: 0 for s in suite_names}
        suite_total_jobs = {s: sum(1 for j in jobs if j["suite"] == s) for s in suite_names}
        suite_first_job_started = {s: False for s in suite_names}
        suite_start_times = {s: None for s in suite_names}

        # Shared state management - use dict to make interrupted mutable
        state_lock = threading.Lock()
        metadata_lock = threading.Lock()
        interrupt_state = {"interrupted": False}  # Mutable container for interrupt flag
        overall_start = datetime.now()
        total_sim_time = {"seconds": 0.0}  # Cumulative simulation time
        total_prs_time = {"seconds": 0.0}  # Cumulative PRS time
        job_count = {"sims": 0, "prs": 0}  # Track number of jobs for averaging

        def write_metadata():
            """Thread-safe metadata writer."""
            with metadata_lock:
                # Compute suite-level summaries
                for suite_name, suite_data in run_meta["suites"].items():
                    total = pass_count = fail_count = 0
                    for test_data in suite_data["tests"].values():
                        total += test_data["total"]
                        pass_count += test_data["pass"]
                        fail_count += test_data["fail"]
                    suite_data["summary"] = {
                        "total": total,
                        "pass": pass_count,
                        "fail": fail_count
                    }

                run_meta["interrupted"] = interrupt_state["interrupted"]
                with open(regress_run_dir / "metadata.yaml", "w") as mf:
                    yaml.dump(run_meta, mf, default_flow_style=False)

        def run_job(job: dict) -> dict:
            """Execute single regression job (runs in thread pool worker)."""
            suite = job["suite"]
            test = job["test"]
            test_variant = job.get("test_variant")
            seed = job["seed"]
            job_dir = job["job_dir"]
            test_plusargs = job.get("test_plusargs", [])
            variant_plusargs = job.get("variant_plusargs", [])

            # Determine display key (test or test+variant)
            display_key = f"{test}{test_variant}" if test_variant else test

            # Track suite start time on first job
            if not suite_first_job_started[suite]:
                suite_first_job_started[suite] = True
                suite_start_times[suite] = datetime.now()

            # Update display: waiting → running
            with state_lock:
                display_state[suite][display_key]["waiting"] -= 1
                display_state[suite][display_key]["running"] += 1

            # Execute per-count pre-run script if configured
            prs_passed = True
            if pre_run_script and prs_per_count and not job.get("prs_failed", False):
                flow_args = {
                    "--project-root": str(self.project_root),
                    "--config-name": self.config_name,
                    "--suite": suite,
                    "--test": test,
                    "--seed": str(seed),
                    "--run-number": str(job["run_number"]),
                    "--total-runs": str(job["total_runs"]),
                    "--regress": "true",
                }
                if test_variant:
                    flow_args["--variant"] = test_variant

                prs_start = datetime.now()
                prs_passed = run_hook(
                    "Pre-Run Script", pre_run_script, job_dir, flow_args, self.con,
                    silent=True, generate_log=gen_prs_logs
                )
                prs_elapsed = (datetime.now() - prs_start).total_seconds()
                with state_lock:
                    total_prs_time["seconds"] += prs_elapsed
                    job_count["prs"] += 1

            # Build simulation command (tool-specific, now with plusargs)
            cmd, user_plusargs, injected_plusargs, test_pas, variant_pas = build_command(
                binary, args, test, seed, test_plusargs, variant_plusargs
            )

            # Execute simulation
            log_path = job_dir / "sim.log"
            sim_start = datetime.now()

            import subprocess
            with open(log_path, "w") as log_f:
                subprocess.run(cmd, text=True, stdout=log_f,
                             stderr=subprocess.STDOUT, cwd=str(job_dir))

            sim_elapsed = (datetime.now() - sim_start).total_seconds()
            with state_lock:
                total_sim_time["seconds"] += sim_elapsed
                job_count["sims"] += 1

            duration = fmt_duration(datetime.now() - sim_start)

            # Determine pass/fail
            passed = parse_simulation_log(log_path, self.config) if prs_passed else False
            verdict = "PASS" if (passed and prs_passed) else "FAIL"

            # Handle cleanup and metadata based on result
            test_passed = passed and prs_passed
            should_keep = (test_passed and keep_passing) or (not test_passed and keep_failing)

            if not should_keep:
                # Clean up job directory to save disk space
                try:
                    for item in job_dir.iterdir():
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)
                    # Remove the now-empty directory itself
                    job_dir.rmdir()
                except OSError:
                    pass
            else:
                # Write per-job metadata when keeping results
                job_meta = {
                    "test": test,
                    "test_variant": test_variant,
                    "suite": suite,
                    "seed": seed,
                    "result": verdict,
                    "duration": duration,
                    "timestamp": datetime.now().isoformat(),
                    "plusargs": {
                        "user": user_plusargs,
                        "test": test_pas,
                        "variant": variant_pas,
                        "injected": injected_plusargs,
                    },
                }
                with open(job_dir / "metadata.yaml", "w") as mf:
                    yaml.dump(job_meta, mf, default_flow_style=False)

            # Update display: running → pass/fail
            with state_lock:
                display_state[suite][display_key]["running"] -= 1
                display_state[suite][display_key]["pass" if (passed and prs_passed) else "fail"] += 1

            # Track failed seeds in run metadata
            if not (passed and prs_passed):
                with metadata_lock:
                    run_meta["suites"][suite]["tests"][display_key]["failed_seeds"].append(seed)

            # Check if suite completed and write incremental metadata
            suite_completed_jobs[suite] += 1
            if suite_completed_jobs[suite] == suite_total_jobs[suite]:
                write_metadata()

            return {
                "suite": suite,
                "test": test,
                "test_variant": test_variant,
                "seed": seed,
                "passed": passed and prs_passed,
                "prs_passed": prs_passed,
                "log": str(log_path),
                "duration": duration
            }

        # Execute pre-run scripts (per-suite or per-test level)
        prs_results, prs_total_time, prs_elapsed_seconds, prs_suite_test_count = self._execute_pre_run_scripts(
            pre_run_script, prs_per_test, prs_per_count, gen_prs_logs,
            suite_names, jobs, regress_run_dir
        )
        # Add per-test/per-suite PRS time and count to total
        total_prs_time["seconds"] += prs_elapsed_seconds
        job_count["prs"] += prs_suite_test_count

        # Mark jobs from failed PRS and update display
        prs_failed_tests = {key: True for key, success in prs_results.items() if not success}
        if prs_failed_tests:
            with state_lock:
                for job in jobs:
                    suite, test = job["suite"], job["test"]
                    test_variant = job.get("test_variant")
                    display_key = f"{test}{test_variant}" if test_variant else test

                    if (suite,) in prs_failed_tests or (suite, test) in prs_failed_tests:
                        job["prs_failed"] = True
                        display_state[suite][display_key]["waiting"] -= 1
                        display_state[suite][display_key]["fail"] += 1

        # Filter out jobs that failed PRS
        jobs_to_run = [j for j in jobs if not j.get("prs_failed", False)]

        # Print regression info header
        self._print_regression_header(regress_run_dir, prs_results, prs_total_time)

        # Print per-count PRS notice if applicable
        if prs_per_count and pre_run_script and jobs_to_run:
            self.con.info(f"Pre-Run Scripts (per-count): will execute for {len(jobs_to_run)} jobs")

        self.con.blank()

        # Execute regression with live table display
        prs_count_results = self._execute_jobs_with_display(
            jobs_to_run, run_job, run_meta, display_state, state_lock,
            max_parallel, interrupt_state
        )

        # Print per-count PRS summary if applicable
        if prs_per_count and prs_count_results and pre_run_script:
            prs_passed = sum(1 for r in prs_count_results if r)
            prs_failed = len(prs_count_results) - prs_passed

            if prs_failed > 0:
                self.con.info(
                    f"\nPre-Run Scripts (per-count) completed: {C.PASS}{prs_passed} passed{C.RESET}, "
                    f"{C.FAIL}{prs_failed} failed{C.RESET}"
                )
            else:
                self.con.info(f"\nPre-Run Scripts (per-count) completed: {C.PASS}{prs_passed} passed{C.RESET}")
            self.con.blank()

        # Final metadata write
        write_metadata()

        overall_duration = fmt_duration(datetime.now() - overall_start)

        # Calculate average times per job
        avg_sim_seconds = total_sim_time["seconds"] / job_count["sims"] if job_count["sims"] > 0 else 0.0
        avg_prs_seconds = total_prs_time["seconds"] / job_count["prs"] if job_count["prs"] > 0 else 0.0
        avg_sim_duration = fmt_duration(timedelta(seconds=avg_sim_seconds))
        avg_prs_duration = fmt_duration(timedelta(seconds=avg_prs_seconds))

        # Print summary
        self._print_summary(run_meta, overall_duration, avg_sim_duration, avg_prs_duration,
                          interrupt_state["interrupted"], regress_run_dir)

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    def _expand_jobs(self, suite_names: list[str], suites_cfg: dict,
                     regress_run_dir: Path) -> list[dict]:
        """
        Expand suites → tests → variants → jobs with unique seeds.
        Preserves order of suites and tests as specified in config.

        Supports three test specification formats:
        1. Simple string: "smoke" → uses default_count, no plusargs
        2. Colon notation: "test:7" → override count, no plusargs
        3. Structured dict:
           - name: test
             count: 5
             plusargs: ["ARG=1"]
           - name: test
             plusargs: ["COMMON=1"]  # Common to all variants
             variants:
               - suffix: "_fast"
                 plusargs: ["FAST=1"]
                 count: 10
               - plusargs: ["MODE=2"]  # Auto-suffixed as _1
        """
        jobs = []
        used_seeds = set()

        for suite_name in suite_names:
            suite_def = suites_cfg[suite_name]
            default_count = int(ConfigHandler.cfg_get(suite_def, "default_count", default=1))
            test_entries = ConfigHandler.cfg_get(suite_def, "tests", default=[])

            if not test_entries:
                self.con.warning(f"Regression suite '{suite_name}' has no tests — skipping.")
                continue

            for entry in test_entries:
                # Parse entry format
                if isinstance(entry, str):
                    # Format: "test" or "test:N"
                    if ":" in entry:
                        parts = entry.split(":", 1)
                        if len(parts) != 2:
                            self.con.error(f"Invalid test specification: '{entry}' — skipping.")
                            continue
                        test, count_str = parts
                        try:
                            count = int(count_str)
                        except ValueError:
                            self.con.error(f"Invalid count in '{entry}' — skipping.")
                            continue
                        test_plusargs = []
                        variants = None
                    else:
                        test = entry
                        count = default_count
                        test_plusargs = []
                        variants = None

                elif isinstance(entry, dict):
                    # Structured format
                    test = entry.get("name")
                    if not test:
                        self.con.error("Test entry missing 'name' field — skipping.")
                        continue

                    # Check for invalid mixing of structured + colon notation
                    if ":" in test:
                        self.con.error(f"Cannot mix structured format with colon notation: '{test}' — skipping.")
                        continue

                    test_plusargs = entry.get("plusargs", [])
                    variants = entry.get("variants")

                    # Validate conflicts: if variants exist, top-level count is ignored
                    if variants:
                        if "count" in entry:
                            self.con.warning(
                                f"Test '{test}' has both 'variants' and 'count' — "
                                f"ignoring top-level count (variants specify their own counts)."
                            )
                        count = None  # Will be handled per-variant
                    else:
                        count = entry.get("count", default_count)

                else:
                    self.con.error(f"Invalid test entry type: {type(entry)} — skipping.")
                    continue

                # Expand variants or create single test instance
                if variants:
                    for idx, variant_def in enumerate(variants):
                        if not isinstance(variant_def, dict):
                            self.con.error(f"Variant definition must be a dict — skipping variant {idx}.")
                            continue

                        # Get variant suffix (auto-generate if missing)
                        variant_suffix = variant_def.get("suffix", f"_{idx}")
                        variant_plusargs = variant_def.get("plusargs", [])
                        variant_count = variant_def.get("count", default_count)

                        # Generate jobs for this variant
                        for i in range(variant_count):
                            seed = generate_unique_seed(used_seeds)
                            job_dir = regress_run_dir / suite_name / test / f"s{seed}"
                            ensure_dir(job_dir)

                            jobs.append({
                                "suite": suite_name,
                                "test": test,
                                "test_variant": variant_suffix,
                                "count_index": i,
                                "run_number": i + 1,
                                "total_runs": variant_count,
                                "seed": seed,
                                "job_dir": job_dir,
                                "test_plusargs": test_plusargs,
                                "variant_plusargs": variant_plusargs,
                            })
                else:
                    # Single test instance (no variants)
                    for i in range(count):
                        seed = generate_unique_seed(used_seeds)
                        job_dir = regress_run_dir / suite_name / test / f"s{seed}"
                        ensure_dir(job_dir)

                        jobs.append({
                            "suite": suite_name,
                            "test": test,
                            "test_variant": None,
                            "count_index": i,
                            "run_number": i + 1,
                            "total_runs": count,
                            "seed": seed,
                            "job_dir": job_dir,
                            "test_plusargs": test_plusargs,
                            "variant_plusargs": [],
                        })

        return jobs

    def _init_metadata(self, suite_names: list[str], jobs: list[dict],
                      regress_run_dir: Path, regress_run_num: int) -> dict:
        """
        Initialize run metadata structure.
        """
        run_meta = {
            "run_number": regress_run_num,
            "timestamp": datetime.now().isoformat(),
            "run_dir": str(regress_run_dir),
            "suites": {},
            "interrupted": False
        }

        for suite in suite_names:
            suite_jobs = [j for j in jobs if j["suite"] == suite]
            tests = {}

            for job in suite_jobs:
                test = job["test"]
                test_variant = job.get("test_variant")

                # Display key includes variant suffix if present
                display_key = f"{test}{test_variant}" if test_variant else test

                if display_key not in tests:
                    tests[display_key] = {
                        "total": 0,
                        "pass": 0,
                        "fail": 0,
                        "failed_seeds": []
                    }
                tests[display_key]["total"] += 1

            run_meta["suites"][suite] = {"tests": tests}

        return run_meta

    def _init_display_state(self, suite_names: list[str], jobs: list[dict]) -> dict:
        """
        Initialize display state tracking structure.
        Groups jobs by suite → test (with variant suffix if present).
        """
        display_state = {suite: {} for suite in suite_names}

        for job in jobs:
            suite = job["suite"]
            test = job["test"]
            test_variant = job.get("test_variant")

            # Display key includes variant suffix if present
            display_key = f"{test}{test_variant}" if test_variant else test

            if display_key not in display_state[suite]:
                display_state[suite][display_key] = {
                    "waiting": 0,
                    "running": 0,
                    "pass": 0,
                    "fail": 0
                }

            display_state[suite][display_key]["waiting"] += 1

        return display_state

    def _execute_pre_run_scripts(self, pre_run_script: str, prs_per_test: bool,
                                prs_per_count: bool, gen_prs_logs: bool,
                                suite_names: list[str], jobs: list[dict],
                                regress_run_dir: Path) -> tuple[dict, str]:
        """
        Execute pre-run scripts at appropriate granularity.
        Returns (results_dict, total_time_str)
        """
        if not pre_run_script:
            return {}, "0ms", 0.0, 0

        prs_results = {}
        prs_start_time = datetime.now()

        if not prs_per_test and not prs_per_count:
            # PRS per suite
            for suite_name in suite_names:
                suite_dir = regress_run_dir / suite_name
                flow_args = {
                    "--project-root": str(self.project_root),
                    "--config-name": self.config_name,
                    "--suite": suite_name,
                    "--regress": "true",
                }
                success = run_hook(
                    "Pre-Run Script", pre_run_script, suite_dir, flow_args, self.con,
                    silent=True, generate_log=gen_prs_logs
                )
                prs_results[(suite_name,)] = success

        elif prs_per_test and not prs_per_count:
            # PRS per (suite, test) combination - parallelized
            seen_keys = set()
            test_prs_jobs = []

            for job in jobs:
                key = (job["suite"], job["test"])
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                test_dir = regress_run_dir / job["suite"] / job["test"]
                flow_args = {
                    "--project-root": str(self.project_root),
                    "--config-name": self.config_name,
                    "--suite": job["suite"],
                    "--test": job["test"],
                    "--regress": "true",
                }
                test_prs_jobs.append((key, test_dir, flow_args))

            # Execute in parallel with max_parallel workers
            regress_opts = ConfigHandler.cfg_get(self.config, "regression_options", default={})
            max_parallel = int(ConfigHandler.cfg_get(regress_opts, "max_parallel", default=4))

            def run_test_prs(prs_job):
                key, test_dir, flow_args = prs_job
                success = run_hook(
                    "Pre-Run Script", pre_run_script, test_dir, flow_args, self.con,
                    silent=True, generate_log=gen_prs_logs
                )
                return key, success

            with ThreadPoolExecutor(max_workers=max_parallel) as executor:
                futures = {executor.submit(run_test_prs, prs_job): prs_job for prs_job in test_prs_jobs}
                for future in as_completed(futures):
                    key, success = future.result()
                    prs_results[key] = success

        prs_elapsed_seconds = (datetime.now() - prs_start_time).total_seconds()
        prs_total_time = fmt_duration(datetime.now() - prs_start_time)
        prs_count = len(prs_results)
        return prs_results, prs_total_time, prs_elapsed_seconds, prs_count

    def _print_regression_header(self, regress_run_dir: Path,
                                 prs_results: dict, prs_total_time: str):
        """Print regression run information header."""
        self.con.info(f"Regression run dir : {C.DIM}{regress_run_dir}{C.RESET}")
        self.con.blank()

        # Print PRS summary if any were executed
        if prs_results:
            prs_passed = sum(1 for success in prs_results.values() if success)
            prs_failed = len(prs_results) - prs_passed

            if prs_failed > 0:
                failed_keys = [
                    k[0] if len(k) == 1 else f"{k[0]}.{k[1]}"
                    for k, success in prs_results.items() if not success
                ]
                failed_str = ", ".join(failed_keys)
                self.con.info(
                    f"Pre-Run Scripts: {C.PASS}{prs_passed} passed{C.RESET}, "
                    f"{C.FAIL}{prs_failed} failed{C.RESET} ({prs_total_time})"
                )
                self.con.info(f"  Failed: {failed_str}")
            else:
                self.con.info(
                    f"Pre-Run Scripts: {C.PASS}{prs_passed} passed{C.RESET} ({prs_total_time})"
                )

    def _execute_jobs_with_display(self, jobs: list[dict], run_job: Callable,
                                   run_meta: dict, display_state: dict,
                                   state_lock: threading.Lock, max_parallel: int,
                                   interrupt_state: dict) -> list[bool]:
        """Execute jobs in parallel with live Rich table display."""
        from rich.live import Live
        from rich.table import Table
        from rich.console import Console as RichConsole
        from rich.padding import Padding

        TABLE_INDENT = 4

        def make_table() -> Padding:
            """Generate current state table."""
            table = Table(title="Regression Progress", show_lines=False, pad_edge=False)
            table.add_column("Suite", style="bold cyan", no_wrap=True)
            table.add_column("Test", style="white", no_wrap=True)
            table.add_column("WAITING", style="dim white", justify="right")
            table.add_column("RUNNING", style="bold yellow", justify="right")
            table.add_column("PASS", style="bold green", justify="right")
            table.add_column("FAIL", style="bold red", justify="right")

            with state_lock:
                suite_list = list(display_state.items())
                for idx, (suite_name, tests) in enumerate(suite_list):
                    first_test = True
                    for test, counts in tests.items():
                        table.add_row(
                            suite_name if first_test else "",
                            test,
                            str(counts["waiting"]),
                            str(counts["running"]),
                            str(counts["pass"]),
                            str(counts["fail"]),
                        )
                        first_test = False

                    # Add divider between suites
                    if idx < len(suite_list) - 1:
                        table.add_row("─" * 15, "─" * 15, "─" * 7, "─" * 7,
                                     "─" * 4, "─" * 4, style="dim")

            return Padding(table, (0, 0, 0, TABLE_INDENT))

        rich_console = RichConsole()

        # Track per-count PRS results
        prs_count_results = []

        try:
            with Live(make_table(), console=rich_console, refresh_per_second=2) as live:
                with ThreadPoolExecutor(max_workers=max_parallel) as executor:
                    futures = {executor.submit(run_job, job): job for job in jobs}
                    try:
                        for future in as_completed(futures):
                            result = future.result()
                            suite = result["suite"]
                            test = result["test"]
                            test_variant = result.get("test_variant")
                            display_key = f"{test}{test_variant}" if test_variant else test

                            # Track PRS results
                            prs_count_results.append(result.get("prs_passed", True))

                            # Update run metadata
                            if not result["passed"]:
                                run_meta["suites"][suite]["tests"][display_key]["fail"] += 1
                            else:
                                run_meta["suites"][suite]["tests"][display_key]["pass"] += 1

                            live.update(make_table())

                    except KeyboardInterrupt:
                        interrupt_state["interrupted"] = True
                        executor.shutdown(wait=False, cancel_futures=True)
                        self.con.blank()
                        self.con.warning("Regression interrupted (CTRL+C). Cleaning up...")
                        self.con.blank()
        finally:
            pass  # Metadata write handled by caller

        return prs_count_results

    def _print_summary(self, run_meta: dict, overall_duration: str,
                      sim_duration: str, prs_duration: str,
                      interrupted: bool, regress_run_dir: Path):
        """Print regression summary to console."""
        self.con.blank()
        self.con.banner("[ Regression Summary ]")
        self.con.blank()

        for suite_name, suite_data in run_meta["suites"].items():
            summary = suite_data["summary"]
            self.con.info(
                f"Suite '{suite_name}': "
                f"{C.PASS}{summary['pass']} PASS{C.RESET} / "
                f"{C.FAIL}{summary['fail']} FAIL{C.RESET} / "
                f"{summary['total']} total"
            )

            # Show failed tests (but not individual seeds in console)
            for test, test_data in suite_data["tests"].items():
                if test_data["fail"] > 0:
                    self.con.info(f"  {test}: {test_data['fail']} failure(s)")

        self.con.blank()
        self.con.info(f"Total duration     : {overall_duration} (avg per job — sim: {sim_duration}, prs: {prs_duration})")
        self.con.blank()

        if interrupted:
            self.con.warning(
                "Regression was interrupted (CTRL+C). Partial results saved in metadata."
            )
            self.con.blank()

        self.con.info(
            f"Metadata saved     : {C.BOLD}{regress_run_dir / 'metadata.yaml'}{C.RESET}"
        )

# Convenience alias for backward compatibility
cfg_get = ConfigHandler.cfg_get
