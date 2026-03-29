"""
librerun_utils.py
Shared utilities for LibreRun and its extensions:
  - ANSI color constants (C)
  - Console (unified output + file logging)
  - ConfigHandler (load, merge, expand)
  - Shared path helpers and duration formatting
"""

import argparse
import os
import re
import sys
import yaml
from datetime import datetime
from pathlib import Path

# =============================================================================
# Constants (shared across LibreRun + extensions)
# =============================================================================

BASE_CONFIG     = "base_config"
LAST_INV_PREFIX = "."
LAST_INV_SUFFIX = "_last_invocation"
SIMOUT_DIR      = "simout"
EXE_DIR         = "exe"
SIM_RUNS_DIR    = "sim_runs"
LOGS_DIR        = Path("scripts") / "librerun_logs"
TEMP_DIR        = Path("scripts") / "librerun_temp"

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

_ANSI_RE = re.compile(r'\033\[[0-9;]*m')

def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)

# =============================================================================
# Console
# =============================================================================

class Console:
    """
    Unified console + file logger.

    Severity:   info / warning / error / fatal / debug
    Structural: banner / raw / print_only / log_only / blank
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
        self._f.write(strip_ansi(text) + "\n")
        self._f.flush()

    def _print(self, text: str):
        print(text)

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

    def fatal(self, msg_text: str):
        self.msg(self._fmt_ml(C.FATAL, "[FATAL]", "   ", msg_text))
        self.close()
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
        """Section divider with label — printed and logged."""
        width = 75
        line  = f"{C.STRUCT}{'=' * width}{C.RESET}"
        label = f"{C.HEADER_TEXT}  {text}{C.RESET}"
        self.msg(line)
        self.msg(label)
        self.msg(line)

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
        self._f.close()

    # ------------------------------------------------------------------
    # Program header
    # ------------------------------------------------------------------

    def print_header(self, version: str):
        self.blank()
        self.raw(f"{C.STRUCT}{'=' * 75}{C.RESET}")
        self.raw(f"{C.HEADER_TEXT}  LibreRun {version}  |  RTL Simulation Flow{C.RESET}")
        self.raw(f"{C.STRUCT}{'=' * 75}{C.RESET}")
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
    path.mkdir(parents=True, exist_ok=True)

def config_simout(project_root: Path, config_name: str) -> Path:
    return project_root / SIMOUT_DIR / config_name

def exe_dir(project_root: Path, config_name: str) -> Path:
    return config_simout(project_root, config_name) / EXE_DIR

def next_run_dir(project_root: Path, config_name: str) -> Path:
    import re as _re
    sim_runs = config_simout(project_root, config_name) / SIM_RUNS_DIR
    ensure_dir(sim_runs)
    existing = sorted(sim_runs.glob("run_*"))
    next_n   = 1
    if existing:
        nums   = [int(m.group(1)) for d in existing
                  if (m := _re.match(r"run_(\d+)$", d.name))]
        next_n = max(nums) + 1 if nums else 1
    run_dir = sim_runs / f"run_{next_n}"
    ensure_dir(run_dir)
    return run_dir

def last_inv_path(project_root: Path, user: str) -> Path:
    return project_root / TEMP_DIR / f"{LAST_INV_PREFIX}{user}{LAST_INV_SUFFIX}"

def read_last_config(project_root: Path, user: str) -> str:
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
    path   = last_inv_path(project_root, user)
    ensure_dir(path.parent)
    record = {
        "timestamp":          datetime.now().isoformat(),
        "config":             config_name,
        "compile":            args.compile,
        "sim":                args.sim,
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
