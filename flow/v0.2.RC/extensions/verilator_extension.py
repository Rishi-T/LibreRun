"""
verilator_extension.py
LibreRun extension — Verilator lint, compile, and simulation.
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from librerun_utils import (
    C, LibreRunExtension, ConfigHandler,
    ensure_dir, exe_dir, next_run_dir, fmt_duration,
    TEMP_DIR,
)

cfg_get = ConfigHandler.cfg_get


class VerilatorExtension(LibreRunExtension):
    name = "verilator"

    def provides(self) -> list[str]:
        return ["lint", "compile", "run"]

    def run(self, task: str, context: dict):
        con         = context["console"]
        config      = context["config"]
        args        = context["args"]
        paths       = context["paths"]
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

        handler = _VerilatorHandler(verilator_bin, config, exe, config_name, con)

        con.blank()
        con.banner(f"[ Verilator ] — {task.upper()}")
        con.blank()
        if task == "lint":
            handler.run_lint()
        elif task == "compile":
            handler.run_compile()
        elif task == "run":
            if args.gui:
                import shutil
                if not shutil.which("gtkwave"):
                    con.fatal("GTKWave not found on PATH. Install it with:\n"
                              "         sudo apt install gtkwave")
            tb_top = cfg_get(config, "tb_configuration", "tb_top_module")
            if not tb_top:
                con.fatal("tb_configuration.tb_top_module is not set in config.")
            binary = handler.find_binary(tb_top)
            if binary is None:
                con.error(
                    f"No compiled binary found for config '{config_name}'.\n"
                    f"Run with -c to compile first."
                )
                sys.exit(1)
            run_dir = next_run_dir(project_root, config_name)
            handler.run_sim(binary, args, run_dir)


# =============================================================================
# Internal handler (implementation detail — not part of public interface)
# =============================================================================

class _VerilatorHandler:
    """Full Verilator logic: command building, invocation, result parsing."""

    def __init__(self, verilator_bin: Path, config: dict,
                 exe: Path, config_name: str, console):
        self.verilator_bin = verilator_bin
        self.config        = config
        self.exe           = exe
        self.config_name   = config_name
        self.con           = console

    # ------------------------------------------------------------------
    # Shared flag builders
    # ------------------------------------------------------------------

    def _common_verilator_flags(self) -> list[str]:
        rtl   = cfg_get(self.config, "rtl_configuration", default={})
        tb    = cfg_get(self.config, "tb_configuration",  default={})
        copts = cfg_get(self.config, "compile_options",   default={})
        cmd   = []
        for d in cfg_get(rtl, "rtl_include_dirs", default=[]):
            cmd += ["-I", str(d)]
        for d in cfg_get(tb, "tb_include_dirs", default=[]):
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
        import yaml
        project_root = self.exe.parent.parent.parent
        marker       = project_root / TEMP_DIR / f".autogen_{self.config_name}"
        if not marker.exists():
            return []
        stem = marker.stem.lstrip(".")
        if not stem.startswith("autogen_") or stem[len("autogen_"):] != self.config_name:
            return []
        try:
            with open(marker) as f:
                data      = yaml.safe_load(f) or {}
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

    def build_sim_cmd(self, binary: Path, args) -> list[str]:
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
        cmd      = self.build_lint_cmd()
        lint_dir = self.exe.parent / "lint"
        ensure_dir(lint_dir)
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        lint_log = lint_dir / f"lint_{ts}.log"

        self.con.info(f"Lint command : {' '.join(cmd)}\n")
        self.con.info("Lint in progress...")

        t_start  = datetime.now()
        result   = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, cwd=str(lint_dir))
        duration = fmt_duration(datetime.now() - t_start)

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

        self.con.info(f"Compile command : {' '.join(cmd)}")
        self.con.info("\nCompilation in progress...")

        t_start = datetime.now()
        with open(compile_log, "w") as log_f:
            result = subprocess.run(cmd, text=True, stdout=log_f,
                                    stderr=subprocess.STDOUT, cwd=str(self.exe))
        duration = fmt_duration(datetime.now() - t_start)

        self.con.log_only(open(compile_log).read())

        if result.returncode != 0:
            print(open(compile_log).read())
            self.con.error(f"Compilation failed. ({duration})\nCompile log  : {compile_log}")
            sys.exit(1)
        else:
            self.con.info(f"Compilation successful. ({duration})")

    def run_sim(self, binary: Path, args, run_dir: Path):
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
                pass
            if args.gui:
                duration = self._run_with_gtkwave(cmd, log_path, fst_path, run_dir)
            else:
                t_start  = datetime.now()
                self._run_tee(cmd, log_path, run_dir)
                duration = fmt_duration(datetime.now() - t_start)
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
        import threading
        import time
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
                               stdout=gw_f, stderr=gw_f,
                               start_new_session=True)
            self.con.info("GTKWave closed. Proceeding to log analysis.\n")

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

        failed      = (counts["$error"] > 0 or counts["$fatal"] > 0
                       or any(n > 0 for n in counts["error_kw"].values()))
        verdict     = "PASS" if not failed else "FAIL"
        verdict_str = (f"{C.PASS}  Result : {verdict}{C.RESET}"
                       if not failed else
                       f"{C.FAIL}  Result : {verdict}{C.RESET}")
        dur_str = f". ({duration})" if duration else "."

        self.con.divider("=", width=60)
        self.con.msg(verdict_str)
        self.con.divider("=", width=60)

        if interrupted:
            self.con.warning(f"\nSimulation was interrupted before completion{dur_str}\n"
                             f"Sim log    : {log_path}")
        elif failed:
            self.con.error(f"\nSimulation failed{dur_str}\nSim log    : {log_path}")
        else:
            self.con.info(f"\nSimulation completed successfully{dur_str}\nSim log    : {log_path}")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def find_binary(self, tb_top: str) -> Path | None:
        candidate = self.exe / f"V{tb_top}"
        return candidate if candidate.is_file() else None
