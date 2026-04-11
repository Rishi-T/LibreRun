"""
verilator_extension.py
LibreRun extension — Verilator lint, compile, simulation, and regression.
"""

import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import yaml

from librerun_utils import (
    C, LibreRunExtension, ConfigHandler,
    ensure_dir, exe_dir, next_run_dir, next_regress_run_dir, fmt_duration,
    run_hook, TEMP_DIR,
    # Import generic simulation utilities
    parse_simulation_log, resolve_simulation_seed,
    SimulatorPlusargs, RegressionRunner,
)

cfg_get = ConfigHandler.cfg_get


class VerilatorExtension(LibreRunExtension):
    name = "verilator"

    def provides(self) -> list[str]:
        return ["lint", "compile", "run", "regress"]

    def run(self, task: str, context: dict):
        con          = context["console"]
        config       = context["config"]
        args         = context["args"]
        paths        = context["paths"]
        project_root = paths["project_root"]
        config_name  = paths["config_name"]

        tool_setup   = cfg_get(config, "tool_setup", default={})
        base_path    = tool_setup.get("verilator_base_path")
        version      = tool_setup.get("verilator_version")
        if not base_path or not version:
            con.fatal("tool_setup.verilator_base_path and tool_setup.verilator_version "
                      "must be set in config.")
        verilator_bin = Path(base_path) / version / "bin" / "verilator"
        if not verilator_bin.exists():
            con.fatal(f"Verilator binary not found: {verilator_bin}")

        exe = exe_dir(project_root, config_name)

        handler = _VerilatorHandler(verilator_bin, config, exe, config_name, con, project_root)

        con.blank()
        con.banner(f"[ Verilator ] — {task.upper()}")
        con.blank()

        if task == "lint":
            handler.run_lint()
        elif task == "compile":
            success = handler.run_compile()
            if not success:
                con.error("Compilation failed. Cannot proceed to simulation.")
                sys.exit(1)
        elif task == "run":
            if args.gui:
                if not shutil.which("gtkwave"):
                    con.fatal("GTKWave not found on PATH. Install it with:\n"
                              "         sudo apt install gtkwave")
            tb_top = cfg_get(config, "tb_configuration", "tb_top_module")
            if not tb_top:
                con.fatal("tb_configuration.tb_top_module is not set in config.")
            binary = handler.find_binary(tb_top)
            if binary is None:
                expected = handler.exe / f"V{tb_top}"
                con.error(
                    f"No compiled simulation binary found for config '{config_name}'.\n"
                    f"Expected : {C.BOLD}{expected}{C.RESET}\n"
                    f"Run      : {C.BOLD}lr -c{C.RESET}"
                )
                sys.exit(1)

            # Get test name from args
            test = args.run if args.run else "default"
            run_dir, run_num = next_run_dir(project_root, config_name, test)
            handler.run_sim(binary, args, run_dir, test, run_num)

        elif task == "regress":
            tb_top = cfg_get(config, "tb_configuration", "tb_top_module")
            if not tb_top:
                con.fatal("tb_configuration.tb_top_module is not set in config.")
            binary = handler.find_binary(tb_top)
            if binary is None:
                expected = handler.exe / f"V{tb_top}"
                con.error(
                    f"No compiled simulation binary found for config '{config_name}'.\n"
                    f"Expected : {C.BOLD}{expected}{C.RESET}\n"
                    f"Run      : {C.BOLD}lr -c{C.RESET}"
                )
                sys.exit(1)
            regress_run_dir, regress_run_num = next_regress_run_dir(project_root, config_name)
            handler.run_regression(binary, args, regress_run_dir, regress_run_num)


# =============================================================================
# Internal handler (implementation detail — not part of public interface)
# =============================================================================

class _VerilatorHandler:
    """Full Verilator logic: command building, invocation, result parsing."""

    def __init__(self, verilator_bin: Path, config: dict,
                 exe: Path, config_name: str, console, project_root: Path):
        self.verilator_bin = verilator_bin
        self.config        = config
        self.exe           = exe
        self.config_name   = config_name
        self.con           = console
        self.project_root  = project_root
        # Initialize plusargs builder for Verilator
        self.plusargs_builder = SimulatorPlusargs("verilator")

    # ------------------------------------------------------------------
    # Shared flag builders
    # ------------------------------------------------------------------

    def _common_verilator_flags(self) -> list[str]:
        rtl   = cfg_get(self.config, "rtl_configuration", default={})
        tb    = cfg_get(self.config, "tb_configuration",  default={})
        copts = cfg_get(self.config, "compile_options",   default={})
        cmd   = []
        for d in cfg_get(rtl, "rtl_include_dirs", default=[]):
            cmd.append(f"+incdir+{d}")
        for d in cfg_get(tb, "tb_include_dirs", default=[]):
            cmd.append(f"+incdir+{d}")
        for define in cfg_get(copts, "defines", default=[]):
            cmd += [f"-D{define}"]
        cmd += cfg_get(copts, "verilator_flags", default=[])
        # Add C++ compiler flags via -CFLAGS
        cflags = cfg_get(copts, "cflags", default=[])
        if cflags:
            cmd += ["-CFLAGS", " ".join(cflags)]
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
        """Return autogenerated filelist paths from filelist generator."""
        marker = self.project_root / TEMP_DIR / f".autogen_{self.config_name}"
        if not marker.exists():
            return []

        stem = marker.stem.lstrip(".")
        if not stem.startswith("autogen_") or stem[len("autogen_"):] != self.config_name:
            return []

        try:
            with open(marker) as f:
                data = yaml.safe_load(f) or {}
            rel_paths = data.get("generated_filelists", [])
        except (OSError, yaml.YAMLError) as e:
            self.con.debug(f"Failed to read autogen marker {marker}: {e}")
            return []

        return [self.project_root / rel for rel in rel_paths if (self.project_root / rel).exists()]

    def _tb_top(self) -> str:
        tb_top = cfg_get(self.config, "tb_configuration", "tb_top_module")
        if not tb_top:
            self.con.fatal("tb_configuration.tb_top_module is not set in config.")
        return tb_top

    # ------------------------------------------------------------------
    # Command builders
    # ------------------------------------------------------------------

    def build_lint_cmd(self) -> list[str]:
        cmd = [
            str(self.verilator_bin),
            "--lint-only", "--sv", "--timing", "-Wall",
            "--top-module", self._tb_top(),
        ]
        cmd += self._common_verilator_flags()
        cmd += self._filelist_flags()
        cmd += self._source_flags()
        return cmd

    def build_compile_cmd(self) -> list[str]:
        dut_top = cfg_get(self.config, "rtl_configuration", "dut_top_module")
        if not dut_top:
            self.con.fatal("rtl_configuration.dut_top_module is not set in config.")

        # Get simulation_threads from compile_options (default to 1)
        copts = cfg_get(self.config, "compile_options", default={})
        sim_threads = cfg_get(copts, "simulation_threads", default=1)

        # Normalize: 0 or negative values default to 1
        if sim_threads <= 0:
            sim_threads = 1

        cmd = [
            str(self.verilator_bin),
            "--binary", "--sv", "--timing", "--trace-fst",
            "--build-jobs", "0", "-Wno-fatal",
            "--Mdir", str(self.exe),
            "--top-module", self._tb_top(),
        ]

        # Add --threads flag only if > 1
        if sim_threads > 1:
            cmd += ["--threads", str(sim_threads)]

        cmd += self._common_verilator_flags()
        cmd += self._filelist_flags()
        cmd += self._source_flags()
        return cmd

    def build_sim_cmd(self, binary: Path, args, test: str, seed: int,
                     test_plusargs: list[str] = None,
                     variant_plusargs: list[str] = None) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
        """
        Build sim command for normal run (-r).
        Returns: (full_cmd, user_plusargs, injected_plusargs, test_plusargs, variant_plusargs)
        """
        simulation_options = cfg_get(self.config, "simulation_options", default={})

        # Use generic plusargs builder with test/variant plusargs
        plusargs, plusargs_meta = self.plusargs_builder.build_plusargs(
            simulation_options, args, test, seed, test_plusargs, variant_plusargs
        )

        # Waves control (Verilator-specific)
        if args.waves or args.gui:
            plusargs.append("+waves")
            plusargs_meta["injected"].append("+waves")

        cmd = [str(binary)] + plusargs
        return (cmd,
                plusargs_meta["user"],
                plusargs_meta["injected"],
                plusargs_meta["test"],
                plusargs_meta["variant"])

    def build_regress_sim_cmd(self, binary: Path, args, test: str, seed: int,
                             test_plusargs: list[str] = None,
                             variant_plusargs: list[str] = None) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
        """
        Build sim command for regression job.
        Returns: (full_cmd, user_plusargs, injected_plusargs, test_plusargs, variant_plusargs)
        """
        simulation_options = cfg_get(self.config, "simulation_options", default={})

        # Use generic plusargs builder (no waves in regression)
        plusargs, plusargs_meta = self.plusargs_builder.build_plusargs(
            simulation_options, args, test, seed, test_plusargs, variant_plusargs
        )

        cmd = [str(binary)] + plusargs
        return (cmd,
                plusargs_meta["user"],
                plusargs_meta["injected"],
                plusargs_meta["test"],
                plusargs_meta["variant"])


    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def run_lint(self):
        cmd      = self.build_lint_cmd()
        lint_dir = self.exe.parent / "lint"
        ensure_dir(lint_dir)
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        lint_log = lint_dir / f"lint_{ts}.log"

        self.con.info(f"Lint command : {C.DIM}{' '.join(cmd)}{C.RESET}\n")
        self.con.info("Lint in progress...")

        t_start  = datetime.now()
        result   = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, cwd=str(lint_dir))
        duration = fmt_duration(datetime.now() - t_start)

        with open(lint_log, "w") as lf:
            lf.write(result.stdout)
        self.con.log_only(result.stdout)

        if result.returncode != 0:
            # Parse output for common errors that need better messaging
            if "Cannot find file containing module:" in result.stdout or \
               "%Error: Cannot find file containing module:" in result.stdout:
                self.con.error(f"{C.FAIL}Lint failed.{C.RESET} ({duration})")
                self.con.error(
                    f"Verilator cannot find RTL module files. This usually means filelists weren't generated.\n"
                    f"Try running: flow -flg (filelist generation) before lint.\n"
                )
                self.con.error(f"Lint report  : {C.BOLD}{lint_log}{C.RESET}")
            else:
                self.con.error(f"{C.FAIL}Lint failed.{C.RESET} ({duration})")
                self.con.error(f"Lint report  : {C.BOLD}{lint_log}{C.RESET}")
        else:
            self.con.info(f"{C.PASS}Lint clean.{C.RESET} ({duration})")

    def run_compile(self) -> bool:
        """Returns True if compilation succeeded, False otherwise."""
        ensure_dir(self.exe)
        compile_log = self.exe / "compile.log"
        cmd         = self.build_compile_cmd()

        self.con.info(f"Compile command : {C.DIM}{' '.join(cmd)}{C.RESET}")
        self.con.info("\nCompilation in progress...")

        t_start = datetime.now()
        with open(compile_log, "w") as log_f:
            result = subprocess.run(cmd, text=True, stdout=log_f,
                                    stderr=subprocess.STDOUT, cwd=str(self.exe))
        duration = fmt_duration(datetime.now() - t_start)

        self.con.log_only(open(compile_log).read())

        if result.returncode != 0:
            print(open(compile_log).read())
            self.con.error(f"{C.FAIL}Compilation failed. ({duration}){C.RESET}\nCompile log  : {C.BOLD}{compile_log}{C.RESET}\n")
            return False
        else:
            self.con.info(f"{C.PASS}Compilation successful.{C.RESET} ({duration})")
            return True

    def run_sim(self, binary: Path, args, run_dir: Path, test: str, run_num: int):
        """
        Single simulation run with test-aware directory structure.
        Generates seed, writes metadata, injects test name.
        """
        simulation_options = cfg_get(self.config, "simulation_options", default={})

        # Use generic seed resolution
        seed = resolve_simulation_seed(args, self.config)

        cmd, user_plusargs, injected_plusargs, test_plusargs, variant_plusargs = self.build_sim_cmd(binary, args, test, seed)
        log_path = run_dir / "sim.log"
        fst_path = run_dir / "waves.fst"

        self.con.info(f"Sim run directory : {C.DIM}{run_dir}{C.RESET}")
        self.con.info(f"Test name         : {C.DIM}{test}{C.RESET}")
        self.con.info(f"Seed              : {C.DIM}{seed}{C.RESET}")

        pre_run_script = cfg_get(simulation_options, "pre_run_script", default="").strip()
        if pre_run_script:
            flow_args = {
                "--project-root": str(self.project_root),
                "--config-name":  self.config_name,
                "--test":         test,
                "--seed":         str(seed),
                "--run-number":   str(run_num),
            }
            success = run_hook("Pre-Run Script", pre_run_script, run_dir, flow_args, self.con)
            if not success:
                sys.exit(1)

        self.con.blank()
        self.con.info(f"Sim command       : {C.DIM}{' '.join(cmd)}{C.RESET}")

        if not args.gui:
            self.con.msg(f"\n{C.STRUCT}{'~' * 17} Starting Simulation Run {'~' * 18}{C.RESET}\n")

        interrupted = False
        duration    = "unknown"
        t_start     = datetime.now()

        try:
            with open(log_path, "w"):
                pass
            if args.gui:
                duration = self._run_with_gtkwave(cmd, log_path, fst_path, run_dir)
            else:
                t_start  = datetime.now()
                self._run_tee(cmd, log_path, run_dir)
                duration = fmt_duration(datetime.now() - t_start)
        except KeyboardInterrupt:
            interrupted = True
            duration = fmt_duration(datetime.now() - t_start)

        # Use generic log parser
        passed = parse_simulation_log(log_path, self.config) if not interrupted else False
        verdict = "PASS" if passed else ("INTERRUPTED" if interrupted else "FAIL")

        # Write metadata
        metadata = {
            "test":       test,
            "seed":       seed,
            "result":     verdict,
            "duration":   duration,
            "timestamp":  datetime.now().isoformat(),
            "plusargs": {
                "user":     user_plusargs,
                "injected": injected_plusargs,
            },
            "waves":      args.waves or args.gui,
            "interrupted": interrupted,
        }
        with open(run_dir / "metadata.yaml", "w") as mf:
            yaml.dump(metadata, mf, default_flow_style=False)

        if not args.gui:
            self.con.msg(f"\n{C.STRUCT}{'~' * 17}  Exiting Simulation Run {'~' * 18}{C.RESET}\n")

        self._parse_and_report(log_path, duration, interrupted)

        self.con.blank()
        self.con.info(f"Metadata saved    : {C.BOLD}{run_dir / 'metadata.yaml'}{C.RESET}")

    # ------------------------------------------------------------------
    # Regression
    # ------------------------------------------------------------------

    def run_regression(self, binary: Path, args, regress_run_dir: Path, regress_run_num: int):
        """Run regression suites with parallel execution."""

        runner = RegressionRunner(
            self.config, self.con, self.project_root, self.config_name, "verilator"
        )

        # Pass command builder that accepts plusargs
        runner.run_regression(
            binary, args, regress_run_dir, regress_run_num,
            build_command=self.build_regress_sim_cmd
        )

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _run_tee(self, cmd: list, log_path: Path, run_dir: Path):
        """Run command with output to both console and log file."""
        with open(log_path, "w") as log_f:
            proc = subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, cwd=str(run_dir))
            for line in proc.stdout:
                print(line, end="")
                log_f.write(line)
            proc.wait()

    def _run_with_gtkwave(self, cmd: list, log_path: Path,
                          fst_path: Path, run_dir: Path) -> str:
        """Run simulation with GTKWave for live waveform viewing."""
        import time

        # Use list to communicate duration from thread
        sim_duration = [None]

        def run_sim_thread():
            self.con.info("\nSimulation in progress...")
            t = datetime.now()
            with open(log_path, "w") as log_f:
                subprocess.run(cmd, text=True, stdout=log_f,
                             stderr=subprocess.STDOUT, cwd=str(run_dir))
            sim_duration[0] = fmt_duration(datetime.now() - t)
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
                             stdout=gw_f, stderr=subprocess.STDOUT)

        sim_thread = threading.Thread(target=run_sim_thread, daemon=True)
        gtk_thread = threading.Thread(target=run_gtkwave_thread, daemon=True)

        sim_thread.start()
        gtk_thread.start()

        sim_thread.join()
        gtk_thread.join()

        return sim_duration[0]

    def _parse_and_report(self, log_path: Path, duration: str, interrupted: bool):
        """
        Parse simulation log and generate detailed report.
        Uses generic parse_simulation_log() for pass/fail, then adds detailed counts.
        """
        tb_config = cfg_get(self.config, "tb_configuration", default={})
        info_keywords    = [k.lower() for k in cfg_get(tb_config, "info_keywords",    default=[])]
        warning_keywords = [k.lower() for k in cfg_get(tb_config, "warning_keywords", default=[])]
        error_keywords   = [k.lower() for k in cfg_get(tb_config, "error_keywords",   default=[])]

        counts = {
            "$error":   0,
            "$fatal":   0,
            "info_kw":  {k: 0 for k in info_keywords},
            "warn_kw":  {k: 0 for k in warning_keywords},
            "error_kw": {k: 0 for k in error_keywords},
        }

        # Single pass through log file for all counting
        try:
            with open(log_path, "r") as f:
                for line in f:
                    line_lower = line.lower()
                    if "%error" in line_lower or "$error" in line_lower:
                        counts["$error"] += 1
                    if "%fatal" in line_lower or "$fatal" in line_lower:
                        counts["$fatal"] += 1
                    for k in info_keywords:
                        if k in line_lower:
                            counts["info_kw"][k] += 1
                    for k in warning_keywords:
                        if k in line_lower:
                            counts["warn_kw"][k] += 1
                    for k in error_keywords:
                        if k in line_lower:
                            counts["error_kw"][k] += 1
        except OSError:
            self.con.error(f"Failed to read log file: {log_path}")
            return

        # Display detailed report
        self.con.divider("-", width=60)
        self.con.header_line("  Post-Sim Log Summary")
        self.con.divider("-", width=60)
        self.con.msg(f"  $error  hits : {counts['$error']}")
        self.con.msg(f"  $fatal  hits : {counts['$fatal']}")

        if info_keywords:
            self.con.blank()
            self.con.msg("  Info keywords:")
            for k, n in counts["info_kw"].items():
                self.con.msg(f"    {k:<25} : {n}")
        if warning_keywords:
            self.con.blank()
            self.con.msg("  Warning keywords:")
            for k, n in counts["warn_kw"].items():
                self.con.msg(f"    {k:<25} : {n}")
        if error_keywords:
            self.con.blank()
            self.con.msg("  Error keywords:")
            for k, n in counts["error_kw"].items():
                self.con.msg(f"    {k:<25} : {n}")

        # Determine pass/fail (consistent with parse_simulation_log logic)
        failed = (counts["$error"] > 0 or counts["$fatal"] > 0
                  or any(n > 0 for n in counts["error_kw"].values()))
        verdict = "PASS" if not failed else "FAIL"
        verdict_str = (f"{C.PASS}  Result : {verdict}{C.RESET}"
                       if not failed else
                       f"{C.FAIL}  Result : {verdict}{C.RESET}")
        dur_str = f". ({duration})" if duration else "."

        self.con.divider("=", width=60)
        self.con.msg(verdict_str)
        self.con.divider("=", width=60)
        self.con.blank()

        if interrupted:
            self.con.warning(f"\n{C.WARNING}Simulation was interrupted before completion{C.RESET}{dur_str}\n"
                             f"Sim log    : {C.BOLD}{log_path}{C.RESET}")
        elif failed:
            self.con.error(f"\n{C.FAIL}Simulation failed{C.RESET}{dur_str}\nSim log    : {C.BOLD}{log_path}{C.RESET}")
        else:
            self.con.info(f"{C.PASS}Simulation completed successfully{C.RESET}{dur_str}\n"
                          f"Sim log    : {C.BOLD}{log_path}{C.RESET}")

    def find_binary(self, tb_top: str):
        """
        Locate and validate compiled simulation binary.

        Ensures:
        - Binary exists
        - Is a file
        - Is executable (best-effort)
        """
        binary = self.exe / f"V{tb_top}"

        if not binary.exists() or not binary.is_file():
            return None

        # Optional: check executability (skip hard fail, just warn later if needed)
        try:
            import os
            if not os.access(binary, os.X_OK):
                return None
        except Exception:
            # If access check fails for any reason, fall back to existence
            pass

        return binary
