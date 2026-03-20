#!/usr/bin/env python3
"""
LibreRun v0.1
Verilator-based SystemVerilog simulation flow.
"""

import argparse
import getpass
import os
import re
import subprocess
import sys
import yaml
from datetime import datetime
from pathlib import Path

# =============================================================================
# Constants
# =============================================================================

VERSION         = "v0.1.RC"
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
    # Structural / header (darker orange)
    STRUCT      = "\033[38;5;166m"
    # Header text (lighter orange)
    HEADER_TEXT = "\033[38;5;214m"
    # Log levels
    INFO        = "\033[38;5;44m"  # cyan (256-color, unambiguous)
    WARNING     = "\033[33m"      # yellow
    ERROR       = "\033[31m"      # red
    FATAL       = "\033[31;1m"    # bold red
    # Result verdicts
    PASS        = "\033[32;1m"    # bold green
    FAIL        = "\033[31;1m"    # bold red
    # Misc
    DIM         = "\033[2m"

_ANSI_RE = re.compile(r'\033\[[0-9;]*m')

def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)

# =============================================================================
# Console (printing + logging)
# =============================================================================

class Console:
    """
    Unified console + file logger.

    msg() / info() / warning() / error() / fatal() all accept:
      print_=True   — emit to stdout
      log_=True     — write to log file
    The log file always receives ANSI-stripped text.
    """

    def __init__(self, project_root: Path, user: str):
        log_dir = project_root / LOGS_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = log_dir / f"{user}_{ts}.log"
        self._f   = open(self.path, "w")

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _log(self, text: str):
        self._f.write(strip_ansi(text) + "\n")
        self._f.flush()

    def _print(self, text: str):
        print(text)

    def msg(self, text: str, *, print_: bool = True, log_: bool = True):
        if print_: self._print(text)
        if log_:   self._log(text)

    def log_only(self, text: str):
        self._log(text)

    def print_only(self, text: str):
        self._print(text)

    def close(self):
        self._f.close()

    # ------------------------------------------------------------------
    # Semantic helpers
    # ------------------------------------------------------------------

    # All prefixes are 10 chars wide: "[INFO]    ", "[WARNING] ", "[ERROR]   "
    # Continuation lines indent to match, so wrapped text stays aligned.
    _INDENT = " " * 10

    def _fmt_ml(self, color: str, tag: str, pad: str, msg_text: str) -> str:
        import shutil, textwrap
        term_width = shutil.get_terminal_size(fallback=(120, 24)).columns
        # All continuation lines (including the first line overflow) are indented
        # by _INDENT, so wrap width must be relative to that — not the tag length.
        wrap_width = max(term_width - len(self._INDENT) - 2, 20)

        # Preserve leading/trailing blank lines from explicit \n in the message.
        leading  = len(msg_text) - len(msg_text.lstrip("\n"))
        trailing = len(msg_text) - len(msg_text.rstrip("\n"))

        wrapped: list[str] = []
        for logical_line in msg_text.strip("\n").splitlines():
            wrapped.extend(textwrap.wrap(logical_line, width=wrap_width) or [""])

        first = f"{color}{tag}{C.RESET}{pad}{wrapped[0]}"
        rest  = [f"{self._INDENT}{l}" for l in wrapped[1:]]
        body  = "\n".join([first] + rest)
        return "\n" * leading + body + "\n" * trailing

    def info(self, msg_text: str, *, print_: bool = True, log_: bool = True):
        self.msg(self._fmt_ml(C.INFO, "[INFO]", "    ", msg_text), print_=print_, log_=log_)

    def warning(self, msg_text: str, *, print_: bool = True, log_: bool = True):
        self.msg(self._fmt_ml(C.WARNING, "[WARNING]", " ", msg_text), print_=print_, log_=log_)

    def error(self, msg_text: str, *, print_: bool = True, log_: bool = True):
        self.msg(self._fmt_ml(C.ERROR, "[ERROR]", "   ", msg_text), print_=print_, log_=log_)

    def fatal(self, msg_text: str):
        self.msg(self._fmt_ml(C.FATAL, "[FATAL]", "   ", msg_text))
        self.close()
        sys.exit(1)

    def divider(self, char: str = "=", width: int = 75):
        self.msg(f"{C.STRUCT}{char * width}{C.RESET}")

    def header_line(self, text: str):
        self.msg(f"{C.HEADER_TEXT}{text}{C.RESET}")

    def blank(self):
        self.msg("")

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def print_header(self):
        self.blank()
        self.divider("=")
        self.header_line(f"  LibreRun {VERSION}  |  RTL Simulation Flow")
        self.divider("=")
        self.blank()


# Thin module-level wrappers used before a Console instance is available
def _early_fatal(msg_text: str):
    print(f"{C.FATAL}[FATAL]{C.RESET}   {msg_text}")
    sys.exit(1)

# =============================================================================
# Argument Parsing
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="LibreRun — RTL Simulation Flow",
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=True,
    )
    parser.add_argument("-c",   "--compile",           action="store_true",
                        help="Invoke Verilator compile (incremental via Make)")
    parser.add_argument("-cfg", "--config",            default=None, metavar="NAME",
                        help="Supplementary config name (no .yaml). Defaults to last used or base_config.")
    parser.add_argument("-r",   "--sim",               action="store_true",
                        help="Run simulation using existing compiled binary")
    parser.add_argument("-w",   "--waves",             action="store_true",
                        help="Enable FST waveform dump during simulation")
    parser.add_argument("-g",   "--gui",               action="store_true",
                        help="Enable FST dump and launch GTKWave (implies --waves)")
    parser.add_argument("-s",   "--seed",              default=None, type=int, metavar="N",
                        help="Override simulation seed (0 = random)")
    parser.add_argument("-p",   "--plusargs",          nargs="+", default=[], metavar="ARG",
                        help="Extra plusargs (space-separated, no leading '+' needed)")
    parser.add_argument("-l",   "--lint",              action="store_true",
                        help="Run Verilator lint-only check (no compile, no binary)")
    parser.add_argument("-flg", "--filelist_gen",      action="store_true",
                        help="Invoke RTL parser / filelist generator")
    parser.add_argument("-flo", "--filelist_optimize", action="store_true",
                        help="Prune unreachable files from generated filelists (use with -flg)")
    return parser.parse_args()

# =============================================================================
# Environment helpers
# =============================================================================

def get_project_root() -> Path:
    root = os.environ.get("PROJECT_ROOT")
    if not root:
        _early_fatal("PROJECT_ROOT is not set. Please source LibreRunSetup.sh first.")
    path = Path(root)
    if not path.is_dir():
        _early_fatal(f"PROJECT_ROOT does not exist or is not a directory: {path}")
    return path.resolve()

def get_user() -> str:
    return getpass.getuser()

# =============================================================================
# Directory / Path Helpers
# =============================================================================

def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def config_simout(project_root: Path, config_name: str) -> Path:
    return project_root / SIMOUT_DIR / config_name

def exe_dir(project_root: Path, config_name: str) -> Path:
    return config_simout(project_root, config_name) / EXE_DIR

def next_run_dir(project_root: Path, config_name: str) -> Path:
    sim_runs = config_simout(project_root, config_name) / SIM_RUNS_DIR
    ensure_dir(sim_runs)
    existing = sorted(sim_runs.glob("run_*"))
    next_n   = 1
    if existing:
        nums = [int(m.group(1)) for d in existing
                if (m := re.match(r"run_(\d+)$", d.name))]
        next_n = max(nums) + 1 if nums else 1
    run_dir = sim_runs / f"run_{next_n}"
    ensure_dir(run_dir)
    return run_dir

# =============================================================================
# Config Loading & Merging
# =============================================================================

def load_yaml(path: Path) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}

def _expand_env_vars(obj):
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_expand_env_vars(v) for v in obj]
    elif isinstance(obj, str):
        return os.path.expandvars(obj)
    return obj

def _merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, val in override.items():
        if key in result:
            if isinstance(result[key], list) and isinstance(val, list):
                result[key] = result[key] + val
            elif isinstance(result[key], dict) and isinstance(val, dict):
                result[key] = _merge(result[key], val)
            else:
                result[key] = val
        else:
            result[key] = val
    return result

def load_config(project_root: Path, config_name: str) -> dict:
    env_dir   = project_root / "env"
    base_path = env_dir / "base_config.yaml"

    if not base_path.exists():
        _early_fatal(f"base_config.yaml not found at: {base_path}")

    base = _expand_env_vars(load_yaml(base_path))
    if config_name == BASE_CONFIG:
        return base

    supp_path = env_dir / f"{config_name}.yaml"
    if not supp_path.exists():
        _early_fatal(f"Supplementary config not found: {supp_path}")

    supp      = _expand_env_vars(load_yaml(supp_path))
    supp_flow = supp.get("flow_setup", {})
    if "librerun_version" in supp_flow:
        print(f"{C.WARNING}[WARNING]{C.RESET} 'librerun_version' in supplementary config '{config_name}' is ignored.")
        del supp_flow["librerun_version"]

    return _merge(base, supp)

def cfg_get(config: dict, *keys, default=None):
    node = config
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return default
        node = node[k]
    return node if node is not None else default

# =============================================================================
# Flow Config (flow_config.yaml)
# =============================================================================

def load_flow_config(flow_script_dir: Path) -> dict:
    path = flow_script_dir / "flow_config.yaml"
    if not path.exists():
        _early_fatal(f"flow_config.yaml not found at: {path}")
    return load_yaml(path)

def get_verilator_binary(flow_config: dict) -> Path:
    vc      = flow_config.get("verilator_configuration", {})
    base    = vc.get("verilator_base_path")
    version = vc.get("verilator_version")
    if not base or not version:
        _early_fatal("flow_config.yaml must specify verilator_base_path and verilator_version.")
    binary = Path(base) / version / "bin" / "verilator"
    if not binary.exists():
        _early_fatal(f"Verilator binary not found: {binary}")
    return binary

# =============================================================================
# Last Invocation Persistence
# =============================================================================

def last_inv_path(project_root: Path, user: str) -> Path:
    return project_root / TEMP_DIR / f"{LAST_INV_PREFIX}{user}{LAST_INV_SUFFIX}"

def read_last_config(project_root: Path, user: str) -> str:
    path = last_inv_path(project_root, user)
    if not path.exists():
        return BASE_CONFIG
    try:
        data = load_yaml(path)
        return data.get("config", BASE_CONFIG)
    except Exception:
        return BASE_CONFIG

def write_last_invocation(project_root: Path, user: str,
                          config_name: str, args: argparse.Namespace):
    path = last_inv_path(project_root, user)
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
# Duration Formatting
# =============================================================================

def _fmt_duration(delta) -> str:
    total_ms = int(delta.total_seconds() * 1000)
    if total_ms < 1000:      return f"{total_ms}ms"
    elif total_ms < 60000:   return f"{total_ms / 1000:.2f}s"
    elif total_ms < 3600000: return f"{total_ms / 60000:.2f}m"
    else:                    return f"{total_ms / 3600000:.2f}h"

# =============================================================================
# VerilatorHandler
# =============================================================================

class VerilatorHandler:
    """
    Encapsulates all Verilator interactions: lint, compile, and simulation.
    """

    def __init__(self, verilator_bin: Path, config: dict,
                 exe: Path, config_name: str, console: Console):
        self.verilator_bin = verilator_bin
        self.config        = config
        self.exe           = exe
        self.config_name   = config_name
        self.con           = console

    # ------------------------------------------------------------------
    # Shared command building utilities
    # ------------------------------------------------------------------

    def _common_verilator_flags(self) -> list[str]:
        rtl   = cfg_get(self.config, "rtl_configuration", default={})
        tb    = cfg_get(self.config, "tb_configuration",  default={})
        copts = cfg_get(self.config, "compile_options",   default={})

        cmd = []
        for d in cfg_get(rtl, "rtl_include_dirs", default=[]):
            cmd += ["-I", str(d)]
        for d in cfg_get(tb,  "tb_include_dirs",  default=[]):
            cmd += ["-I", str(d)]
        for define in cfg_get(copts, "defines", default=[]):
            cmd += [f"-D{define}"]
        cmd += cfg_get(copts, "verilator_flags", default=[])
        return cmd

    def _filelist_flags(self) -> list[str]:
        rtl = cfg_get(self.config, "rtl_configuration", default={})
        tb  = cfg_get(self.config, "tb_configuration",  default={})
        cmd = []
        for fl in cfg_get(rtl, "rtl_manual_filelists", default=[]):
            cmd += ["-f", str(fl)]
        for fl in self._get_autogen_filelists():
            cmd += ["-f", str(fl)]
        for fl in cfg_get(tb, "tb_filelists", default=[]):
            cmd += ["-f", str(fl)]
        return cmd

    def _source_flags(self) -> list[str]:
        rtl = cfg_get(self.config, "rtl_configuration", default={})
        tb  = cfg_get(self.config, "tb_configuration",  default={})
        cmd = []
        for src_dir in cfg_get(rtl, "rtl_source_dirs", default=[]):
            for ext in ("*.sv", "*.v"):
                for f in Path(src_dir).glob(ext):
                    cmd.append(str(f))
        for f in cfg_get(tb, "tb_source_files", default=[]):
            cmd.append(str(f))
        return cmd

    def _get_autogen_filelists(self) -> list[Path]:
        project_root = self.exe.parent.parent.parent
        marker = project_root / TEMP_DIR / f".autogen_{self.config_name}"
        if not marker.exists():
            return []
        stem = marker.stem.lstrip(".")
        if not stem.startswith("autogen_"):
            return []
        if stem[len("autogen_"):] != self.config_name:
            return []
        try:
            data      = load_yaml(marker)
            rel_paths = data.get("generated_filelists", [])
        except Exception:
            return []
        return [project_root / rel for rel in rel_paths if (project_root / rel).exists()]

    def _tb_top(self) -> str:
        tb_top = cfg_get(self.config, "tb_configuration", "tb_top_module")
        if not tb_top:
            self.con.fatal("tb_configuration.tb_top_module is not set in config.")
        return tb_top

    # ------------------------------------------------------------------
    # Command builders
    # ------------------------------------------------------------------

    def build_compile_cmd(self) -> list[str]:
        dut_top = cfg_get(self.config, "rtl_configuration", "dut_top_module")
        if not dut_top:
            self.con.fatal("rtl_configuration.dut_top_module is not set in config.")
        cmd = [
            str(self.verilator_bin),
            "--binary", "--sv", "--timing", "--trace-fst",
            "--build-jobs", "0", "-Wno-fatal",
            "--Mdir", str(self.exe),
            "--top-module", self._tb_top(),
        ]
        cmd += self._common_verilator_flags()
        cmd += self._filelist_flags()
        cmd += self._source_flags()
        return cmd

    def build_lint_cmd(self) -> list[str]:
        cmd = [
            str(self.verilator_bin),
            "--lint-only", "--sv", "--timing",
            "--top-module", self._tb_top(),
        ]
        cmd += self._common_verilator_flags()
        cmd += self._filelist_flags()
        cmd += self._source_flags()
        return cmd

    def build_sim_cmd(self, binary: Path, args: argparse.Namespace) -> list[str]:
        simopts = cfg_get(self.config, "simulation_options", default={})
        cmd     = [str(binary)]

        error_limit = cfg_get(simopts, "error_limit")
        if error_limit is not None:
            cmd += [f"+verilator+error+limit+{error_limit}"]

        seed = args.seed if args.seed is not None else cfg_get(simopts, "seed")
        if seed is not None and seed != 0:
            cmd += [f"+verilator+seed+{seed}"]

        for pa in cfg_get(simopts, "persistent_plusargs", default=[]):
            cmd.append(f"+{pa.lstrip('+')}")
        for pa in args.plusargs:
            cmd.append(f"+{pa.lstrip('+')}")

        if args.waves or args.gui:
            cmd.append("+waves")
        return cmd

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def run_lint(self):
        cmd = self.build_lint_cmd()
        ensure_dir(self.exe)
        lint_dir = self.exe.parent / "lint"
        ensure_dir(lint_dir)
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        lint_log = lint_dir / f"lint_{ts}.log"

        self.con.info(f"Lint command : {' '.join(cmd)}\n", print_=True, log_=True)
        self.con.info("Lint in progress...")

        t_start = datetime.now()
        result  = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, cwd=str(self.exe))
        duration = _fmt_duration(datetime.now() - t_start)

        with open(lint_log, "w") as lf:
            lf.write(result.stdout)
        self.con.log_only(result.stdout)

        if result.returncode != 0:
            self.con.error(f"Lint failed. ({duration})")
            self.con.error(f"Lint report  : {lint_log}")
            sys.exit(1)
        else:
            self.con.info(f"Lint clean. ({duration})")

    def run_compile(self):
        ensure_dir(self.exe)
        compile_log = self.exe / "compile.log"
        cmd         = self.build_compile_cmd()

        self.con.info(f"\nCompile command : {' '.join(cmd)}")
        self.con.info("\nCompilation in progress...")

        t_start = datetime.now()
        with open(compile_log, "w") as log_f:
            result = subprocess.run(cmd, text=True, stdout=log_f,
                                    stderr=subprocess.STDOUT, cwd=str(self.exe))
        duration = _fmt_duration(datetime.now() - t_start)

        self.con.log_only(open(compile_log).read())

        if result.returncode != 0:
            print(open(compile_log).read())
            self.con.error(f"Compilation failed. ({duration})\nCompile log  : {compile_log}\n")
            sys.exit(1)
        else:
            self.con.info(f"Compilation successful. ({duration})\n")

    def run_sim(self, binary: Path, args: argparse.Namespace, run_dir: Path):
        cmd      = self.build_sim_cmd(binary, args)
        log_path = run_dir / "sim.log"
        fst_path = run_dir / "waves.fst"

        self.con.info(f"Sim run directory : {run_dir}")
        self.con.info(f"Sim command       : {' '.join(cmd)}")
        if not args.gui:
            self.con.msg(f"\n{C.STRUCT}{'~' * 17} Starting Simulation Run {'~' * 18}{C.RESET}\n")

        interrupted = False
        duration    = "unknown"

        try:
            with open(log_path, "w"):
                pass  # ensure file exists
            if args.gui:
                duration = self._run_with_gtkwave(cmd, log_path, fst_path, run_dir)
            else:
                t_start = datetime.now()
                self._run_tee(cmd, log_path, run_dir)
                duration = _fmt_duration(datetime.now() - t_start)
        except KeyboardInterrupt:
            interrupted = True

        if not args.gui:
            self.con.msg(f"\n{C.STRUCT}{'~' * 17}  Exiting Simulation Run {'~' * 18}{C.RESET}\n")
        self._parse_and_report(log_path, duration, interrupted)

    def _run_tee(self, cmd: list, log_path: Path, run_dir: Path):
        with open(log_path, "w") as log_f:
            proc = subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, cwd=str(run_dir))
            for line in proc.stdout:
                print(line, end="")
                log_f.write(line)
            proc.wait()

    def _run_with_gtkwave(self, cmd: list, log_path: Path,
                          fst_path: Path, run_dir: Path) -> str:
        import threading, time
        sim_duration = [None]

        def run_sim_thread():
            self.con.info("\nSimulation in progress...")
            t = datetime.now()
            with open(log_path, "w") as log_f:
                subprocess.run(cmd, text=True, stdout=log_f,
                               stderr=subprocess.STDOUT, cwd=str(run_dir))
            sim_duration[0] = _fmt_duration(datetime.now() - t)
            self.con.info("\nSimulation finished. Close GTKWave to continue.\n")

        def run_gtkwave_thread():
            self.con.info("\nWaiting for FST file to appear...")
            for _ in range(20):
                if fst_path.exists():
                    break
                time.sleep(0.1)
            if not fst_path.exists():
                self.con.warning("FST file did not appear within 2s — launching GTKWave anyway.")
            self.con.info(f"Launching GTKWave: {fst_path}")
            gtkwave_log = run_dir / "gtkwave.log"
            with open(gtkwave_log, "w") as gw_f:
                subprocess.run(["gtkwave", "--dark", str(fst_path)],
                               stdout=gw_f, stderr=gw_f,
                               start_new_session=True)
            self.con.info(f"GTKWave closed. Proceeding to log analysis.\n")

        sim_t     = threading.Thread(target=run_sim_thread)
        gtkwave_t = threading.Thread(target=run_gtkwave_thread)
        sim_t.start()
        gtkwave_t.start()
        sim_t.join()
        gtkwave_t.join()
        return sim_duration[0]

    # ------------------------------------------------------------------
    # Post-sim log parsing
    # ------------------------------------------------------------------

    def _parse_and_report(self, log_path: Path, duration: str, interrupted: bool):
        tb          = cfg_get(self.config, "tb_configuration", default={})
        info_kws    = [k.lower() for k in cfg_get(tb, "info_keywords",    default=[])]
        warning_kws = [k.lower() for k in cfg_get(tb, "warning_keywords", default=[])]
        error_kws   = [k.lower() for k in cfg_get(tb, "error_keywords",   default=[])]

        counts = {
            "$error":   0,
            "$fatal":   0,
            "info_kw":  {k: 0 for k in info_kws},
            "warn_kw":  {k: 0 for k in warning_kws},
            "error_kw": {k: 0 for k in error_kws},
        }

        with open(log_path, "r") as f:
            for line in f:
                ll = line.lower()
                if "%error" in ll or "$error" in ll: counts["$error"] += 1
                if "%fatal" in ll or "$fatal" in ll: counts["$fatal"] += 1
                for k in info_kws:
                    if k in ll: counts["info_kw"][k]  += 1
                for k in warning_kws:
                    if k in ll: counts["warn_kw"][k]  += 1
                for k in error_kws:
                    if k in ll: counts["error_kw"][k] += 1

        self.con.divider("-", width=60)
        self.con.header_line("  Post-Sim Log Summary")
        self.con.divider("-", width=60)
        self.con.msg(f"  $error  hits : {counts['$error']}")
        self.con.msg(f"  $fatal  hits : {counts['$fatal']}")

        if info_kws:
            self.con.blank()
            self.con.msg("  Info keywords:")
            for k, n in counts["info_kw"].items():
                self.con.msg(f"    {k:<25} : {n}")

        if warning_kws:
            self.con.blank()
            self.con.msg("  Warning keywords:")
            for k, n in counts["warn_kw"].items():
                self.con.msg(f"    {k:<25} : {n}")

        if error_kws:
            self.con.blank()
            self.con.msg("  Error keywords:")
            for k, n in counts["error_kw"].items():
                self.con.msg(f"    {k:<25} : {n}")

        failed = (
            counts["$error"] > 0
            or counts["$fatal"] > 0
            or any(n > 0 for n in counts["error_kw"].values())
        )
        verdict     = "PASS" if not failed else "FAIL"
        verdict_str = (f"{C.PASS}  Result : {verdict}{C.RESET}"
                       if not failed else
                       f"{C.FAIL}  Result : {verdict}{C.RESET}")
        dur_str = f". ({duration})" if duration else "."

        self.con.divider("=", width=60)
        self.con.msg(verdict_str)
        self.con.divider("=", width=60)

        if interrupted:
            self.con.warning(f"\nSimulation was interrupted before completion{dur_str}\nSim log    : {log_path}")
        elif failed:
            self.con.error(f"\nSimulation failed{dur_str}\nSim log    : {log_path}")
        else:
            self.con.info(f"\nSimulation completed successfully{dur_str}\nSim log    : {log_path}")

        self.con.blank()

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def find_binary(self, tb_top: str) -> Path | None:
        candidate = self.exe / f"V{tb_top}"
        return candidate if candidate.is_file() else None

# =============================================================================
# FilelistHandler
# =============================================================================

# --- Patterns: module definitions ---
MODULE_DEF_PATTERNS = [
    re.compile(r'^\s*module\s+(\w+)', re.MULTILINE),
]

# --- Patterns: module instantiations ---
MODULE_INST_PATTERNS = [
    re.compile(r'^\s*(\w+)\s+(?:#\s*\(|(\w+)\s*\()', re.MULTILINE),
]

# --- SV/V reserved words ---
SV_V_KEYWORDS = frozenset([
    "module", "endmodule", "interface", "endinterface", "package", "endpackage",
    "program", "endprogram", "checker", "endchecker", "config", "endconfig",
    "input", "output", "inout", "ref", "parameter", "localparam", "defparam",
    "logic", "wire", "reg", "bit", "byte", "shortint", "int", "longint",
    "integer", "real", "realtime", "time", "string", "chandle", "event",
    "void", "shortreal", "signed", "unsigned",
    "assign", "always", "always_ff", "always_comb", "always_latch",
    "initial", "final", "generate", "endgenerate", "genvar",
    "begin", "end", "fork", "join", "join_any", "join_none",
    "if", "else", "case", "casez", "casex", "endcase",
    "for", "foreach", "while", "do", "repeat", "forever",
    "break", "continue", "return", "disable",
    "task", "endtask", "function", "endfunction", "automatic", "static",
    "virtual", "pure", "extern", "import", "export", "context",
    "local", "protected", "const", "var",
    "class", "endclass", "extends", "implements", "new", "this", "super",
    "typedef", "struct", "union", "enum", "packed",
    "modport", "clocking", "endclocking",
    "assert", "assume", "cover", "restrict", "property", "endproperty",
    "sequence", "endsequence",
    "posedge", "negedge", "edge",
    "specify", "endspecify", "primitive", "endprimitive",
    "table", "endtable", "supply0", "supply1", "tri", "triand", "trior",
    "wand", "wor", "uwire",
])


class FilelistHandler:
    """
    Encapsulates RTL file discovery, parsing, duplicate resolution,
    dependency ordering, and filelist writing.
    """

    def __init__(self, config: dict, config_name: str,
                 project_root: Path, console: Console):
        self.config       = config
        self.config_name  = config_name
        self.project_root = project_root
        self.con          = console

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, optimize: bool = False):
        rtl             = cfg_get(self.config, "rtl_configuration", default={})
        source_dirs     = cfg_get(rtl, "rtl_source_dirs",         default=[])
        file_excl       = cfg_get(rtl, "file_exclude_patterns",   default=[])
        folder_excl     = cfg_get(rtl, "folder_exclude_patterns", default=[])
        dut_top         = cfg_get(rtl, "dut_top_module")
        filelists_dir   = self.project_root / "misc" / "filelists"
        mapping_path    = filelists_dir / f"duplicate_mapping_{self.config_name}.yaml"

        if not source_dirs:
            self.con.fatal("rtl_configuration.rtl_source_dirs is empty — nothing to generate filelists from.")
        if not dut_top:
            self.con.fatal("rtl_configuration.dut_top_module is required for filelist generation.")

        self.con.info("\nDiscovering RTL files...")
        groups    = self._discover_files(source_dirs, file_excl, folder_excl)
        all_files = [f for files in groups.values() for f in files]
        self.con.info(f"Found {len(all_files)} RTL file(s) across {len(groups)} group(s).")
        self.con.log_only(f"RTL file discovery: {len(all_files)} files in {len(groups)} groups")
        for nick, files in groups.items():
            self.con.log_only(f"  Group '{nick}': {len(files)} files")
            for f in files:
                self.con.log_only(f"    {f}")

        self.con.info("Parsing files for module definitions and instantiations...")
        module_to_files, file_to_deps = self._build_registry(all_files)

        module_to_files = self._resolve_duplicates(
            module_to_files, filelists_dir, mapping_path
        )

        generated_filelists = []
        total_pruned        = 0

        for nickname, files in groups.items():
            ordered, unreachable = self._topological_sort(
                files, module_to_files, file_to_deps, dut_top
            )

            if optimize:
                total_pruned += len(unreachable)
                self.con.log_only(f"\n-flo pruned from group '{nickname}':")
                for pf in unreachable:
                    self.con.log_only(f"  {pf}")
                unreachable = []

            all_group_files = unreachable + ordered
            include_dirs    = self._collect_include_dirs(all_group_files)
            if optimize:
                include_dirs = [d for d in include_dirs if any(f.parent == d for f in ordered)]

            fl_path = filelists_dir / f"autogen_{nickname}.f"
            self._write_filelist(fl_path, ordered, unreachable, include_dirs)
            generated_filelists.append(fl_path)
            self.con.info(f"Written: {fl_path}  ({len(all_group_files)} files, {len(include_dirs)} include dirs)")
            self.con.log_only(f"Filelist written: {fl_path}")

        self._write_autogen_marker(generated_filelists)

        if optimize and total_pruned > 0:
            self.con.warning(
                f"-flo pruned {total_pruned} unreachable file(s) from filelists. "
                f"See log for full list: {self.con.path}"
            )

        self.con.info(f"\nFilelist generation complete.\n{len(generated_filelists)} filelist(s) written.\n")

    # ------------------------------------------------------------------
    # File discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_source_dir_entry(entry: str) -> tuple[str, str]:
        if ":" in entry:
            parts      = entry.rsplit(":", 1)
            path_part  = parts[0].strip()
            nickname   = parts[1].strip()
        else:
            path_part  = entry.strip()
            nickname   = Path(path_part).name
        return os.path.expandvars(path_part), nickname

    @staticmethod
    def _matches_any_pattern(name: str, patterns: list[str]) -> bool:
        from fnmatch import fnmatch
        return any(fnmatch(name, p) for p in patterns)

    def _discover_files(self, source_dirs, file_excl, folder_excl) -> dict[str, list[Path]]:
        groups: dict[str, list[Path]] = {}
        for entry in source_dirs:
            src_str, nickname = self._parse_source_dir_entry(entry)
            src_path = Path(src_str)
            if not src_path.is_dir():
                self.con.warning(f"RTL source dir not found, skipping: {src_path}")
                continue
            groups.setdefault(nickname, [])
            for ext in ("*.sv", "*.v"):
                for fpath in src_path.rglob(ext):
                    if any(self._matches_any_pattern(p, folder_excl) for p in fpath.parts):
                        continue
                    if self._matches_any_pattern(fpath.name, file_excl):
                        continue
                    groups[nickname].append(fpath)
        return groups

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_file(fpath: Path) -> tuple[list[str], list[str]]:
        try:
            text = fpath.read_text(errors="replace")
        except Exception:
            return [], []

        text = re.sub(r'//.*', '', text)
        text = re.sub(r'/[*].*?[*]/', '', text, flags=re.DOTALL)

        defined = []
        for pat in MODULE_DEF_PATTERNS:
            for m in pat.finditer(text):
                name = m.group(1)
                if name not in SV_V_KEYWORDS:
                    defined.append(name)

        instantiated = []
        for pat in MODULE_INST_PATTERNS:
            for m in pat.finditer(text):
                name = m.group(1)
                if name not in SV_V_KEYWORDS and name not in defined:
                    instantiated.append(name)

        return defined, list(set(instantiated))

    def _build_registry(self, all_files: list[Path]):
        from concurrent.futures import ThreadPoolExecutor, as_completed

        module_to_files: dict[str, list[Path]] = {}
        file_to_deps: dict[Path, list[str]]    = {}

        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(self._parse_file, f): f for f in all_files}
            for future in as_completed(futures):
                fpath              = futures[future]
                defined, instantiated = future.result()
                file_to_deps[fpath]   = instantiated
                for mod in defined:
                    module_to_files.setdefault(mod, []).append(fpath)

        return module_to_files, file_to_deps

    # ------------------------------------------------------------------
    # Duplicate resolution
    # ------------------------------------------------------------------

    def _resolve_duplicates(self, module_to_files, filelists_dir, mapping_path) -> dict:
        duplicates = {mod: files for mod, files in module_to_files.items() if len(files) > 1}
        if not duplicates:
            if mapping_path.exists():
                mapping_path.unlink()
                self.con.info("No duplicates found. Previous duplicate mapping file removed.")
            return module_to_files

        existing_mapping         = load_yaml(mapping_path) if mapping_path.exists() else {}
        updated_mapping, changes = self._merge_duplicate_mapping(existing_mapping, duplicates)

        ensure_dir(filelists_dir)
        with open(mapping_path, "w") as mf:
            yaml.dump(updated_mapping, mf, default_flow_style=False, sort_keys=True)

        if changes:
            self.con.log_only("\nDuplicate mapping changes:")
            for c in changes:
                self.con.log_only(f"  {c}")
            self.con.warning(
                f"{len(changes)} duplicate mapping change(s). "
                f"Check log for details: {self.con.path}"
            )

        unresolved = [
            mod for mod, entry in updated_mapping.items()
            if entry.get("file_to_use") == "Not Set"
        ]
        if unresolved:
            self.con.log_only("\nUnresolved duplicates (file_to_use = Not Set):")
            for mod in unresolved:
                entry = updated_mapping[mod]
                self.con.log_only(f"  {mod}:")
                for i, f in enumerate(entry["files"]):
                    self.con.log_only(f"    [{i}] {f}")
            self.con.error(
                f"{len(unresolved)} unresolved duplicate module(s). "
                f"Edit {mapping_path} to resolve, then re-run -flg.\n"
                f"[ERROR]   Full details in log: {self.con.path}"
            )
            sys.exit(1)

        # Apply resolved mappings
        for mod, entry in updated_mapping.items():
            chosen_idx           = int(entry["file_to_use"])
            chosen_file          = self.project_root / entry["files"][chosen_idx]
            module_to_files[mod] = [chosen_file]

        return module_to_files

    def _merge_duplicate_mapping(self, existing, new_duplicates) -> tuple[dict, list[str]]:
        updated = {}
        changes = []

        for mod, files in new_duplicates.items():
            rel_files  = [str(f.relative_to(self.project_root)) for f in files]
            old_entry  = existing.get(mod)

            if old_entry is None:
                updated[mod] = {"file_to_use": "Not Set", "files": rel_files}
                changes.append(f"NEW duplicate: {mod} -> {rel_files}")
                continue

            old_files  = old_entry.get("files", [])
            old_choice = old_entry.get("file_to_use", "Not Set")

            if set(rel_files) == set(old_files):
                updated[mod] = {"file_to_use": old_choice, "files": rel_files}
            else:
                new_choice = "Not Set"
                if old_choice != "Not Set":
                    try:
                        chosen_file = old_files[int(old_choice)]
                        if chosen_file in rel_files:
                            new_choice = str(rel_files.index(chosen_file))
                            changes.append(
                                f"ADJUSTED index for {mod}: {old_choice} -> {new_choice} "
                                f"(file: {chosen_file})"
                            )
                        else:
                            changes.append(f"RESET {mod}: chosen file '{chosen_file}' no longer present")
                    except (ValueError, IndexError):
                        changes.append(f"RESET {mod}: could not resolve old index {old_choice}")

                if set(rel_files) != set(old_files) and new_choice == "Not Set":
                    changes.append(f"NEW FILE ADDED to {mod}, reset to Not Set")

                updated[mod] = {"file_to_use": new_choice, "files": rel_files}

        for mod in existing:
            if mod not in new_duplicates:
                changes.append(f"RESOLVED: {mod} is no longer a duplicate")

        return updated, changes

    # ------------------------------------------------------------------
    # Dependency ordering
    # ------------------------------------------------------------------

    @staticmethod
    def _topological_sort(all_files, module_to_files, file_to_deps, dut_top):
        file_deps: dict[Path, set[Path]] = {}
        for fpath in all_files:
            deps = set()
            for mod in file_to_deps.get(fpath, []):
                for dep_file in module_to_files.get(mod, []):
                    if dep_file != fpath:
                        deps.add(dep_file)
            file_deps[fpath] = deps

        visited: set[Path] = set()
        ordered: list[Path] = []

        def visit(f: Path):
            if f in visited:
                return
            visited.add(f)
            for dep in file_deps.get(f, []):
                visit(dep)
            ordered.append(f)

        for tf in module_to_files.get(dut_top, []):
            visit(tf)

        unreachable = [f for f in all_files if f not in visited]
        return ordered, unreachable

    # ------------------------------------------------------------------
    # Filelist writing
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_include_dirs(files: list[Path]) -> list[Path]:
        seen = set()
        dirs = []
        for f in files:
            d = f.parent
            if d not in seen:
                seen.add(d)
                dirs.append(d)
        return dirs

    @staticmethod
    def _write_filelist(fpath: Path, ordered: list[Path],
                        unreachable: list[Path], include_dirs: list[Path]):
        ensure_dir(fpath.parent)
        with open(fpath, "w") as f:
            f.write("# Auto-generated by LibreRun -flg. Do not edit manually.\n")
            for d in include_dirs:
                f.write(f"+incdir+{d}\n")
            f.write("\n")
            if unreachable:
                f.write("# Files not reached from dut_top (placed here for safety)\n")
                for src in unreachable:
                    f.write(f"{src}\n")
                f.write("\n")
            for src in ordered:
                f.write(f"{src}\n")

    def _write_autogen_marker(self, generated_filelists: list[Path]):
        marker    = self.project_root / TEMP_DIR / f".autogen_{self.config_name}"
        rel_paths = [str(f.relative_to(self.project_root)) for f in generated_filelists]
        ensure_dir(marker.parent)
        with open(marker, "w") as f:
            yaml.dump({"generated_filelists": rel_paths}, f, default_flow_style=False)

# =============================================================================
# Main
# =============================================================================

def main():
    args         = parse_args()
    project_root = get_project_root()
    user         = get_user()
    flow_dir     = Path(__file__).parent.resolve()

    ensure_dir(project_root / LOGS_DIR)
    ensure_dir(project_root / TEMP_DIR)

    # Resolve config name
    if args.config:
        config_name = args.config
    else:
        config_name = read_last_config(project_root, user)

    flow_config = load_flow_config(flow_dir)
    config      = load_config(project_root, config_name)

    # Console is used for the whole lifetime of the run
    console = Console(project_root, user)
    console.print_header()

    lr_version = cfg_get(config, "flow_setup", "librerun_version", default="")
    if "RC" in str(lr_version).upper() or "RC" in VERSION.upper():
        console.warning("This is a pre-release (RC) version of LibreRun and may be unstable.")
        console.blank()

    proj_name = cfg_get(config, "project_configuration", "project_name", default="<unnamed>")
    console.info(f"Project : {proj_name}")
    console.info(f"Config  : {config_name}")
    console.info(f"Root    : {project_root}")
    console.blank()

    if not args.config:
        console.info(f"No --config specified, using last: '{config_name}'")

    console.log_only(f"LibreRun {VERSION}")
    console.log_only(f"Project : {proj_name}")
    console.log_only(f"Config  : {config_name}")
    console.log_only(f"Args    : {sys.argv}")

    # Filelist generation
    if args.filelist_gen:
        flh = FilelistHandler(config, config_name, project_root, console)
        flh.run(optimize=args.filelist_optimize)
        if not (args.compile or args.sim or args.lint):
            console.close()
            write_last_invocation(project_root, user, config_name, args)
            return

    # Guard: nothing to do
    if not args.compile and not args.sim and not args.lint and not args.filelist_gen:
        console.info("No action requested. Use -c to compile, -r to run, -l to lint, -flg to generate filelists, or -h for help.")
        console.close()
        return

    verilator_bin = get_verilator_binary(flow_config)
    exe           = exe_dir(project_root, config_name)
    tb_top        = cfg_get(config, "tb_configuration", "tb_top_module")
    if not tb_top:
        console.fatal("tb_configuration.tb_top_module is not set in config.")

    vh = VerilatorHandler(verilator_bin, config, exe, config_name, console)

    try:
        if args.lint:
            vh.run_lint()

        if args.compile:
            vh.run_compile()

        if args.sim:
            if args.gui:
                import shutil
                if not shutil.which("gtkwave"):
                    console.fatal("GTKWave not found on PATH. Install it with:\n"
                                  "         sudo apt install gtkwave")
            binary = vh.find_binary(tb_top)
            if binary is None:
                console.info(f"No compiled binary found for config '{config_name}'.")
                console.info("Run with -c to compile first.")
                return

            run_dir = next_run_dir(project_root, config_name)
            vh.run_sim(binary, args, run_dir)

    finally:
        console.close()
        write_last_invocation(project_root, user, config_name, args)


if __name__ == "__main__":
    main()
