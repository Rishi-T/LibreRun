"""
filelist_extension.py
LibreRun extension — RTL filelist generation.
"""

import os
import re
import sys
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from librerun_utils import (
    LibreRunExtension, ConfigHandler,
    ensure_dir, TEMP_DIR,
)

cfg_get = ConfigHandler.cfg_get

# =============================================================================
# SV/V parsing constants
# =============================================================================

MODULE_DEF_PATTERNS = [
    re.compile(r'^\s*module\s+(\w+)', re.MULTILINE),
]

MODULE_INST_PATTERNS = [
    re.compile(r'^\s*(\w+)\s+(?:#\s*\(|(\w+)\s*\()', re.MULTILINE),
]

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

# =============================================================================
# Extension
# =============================================================================

class FilelistExtension(LibreRunExtension):
    name = "filelist"

    def provides(self) -> list[str]:
        return ["filelist_gen"]

    def run(self, task: str, context: dict):
        con          = context["console"]
        config       = context["config"]
        args         = context["args"]
        paths        = context["paths"]
        project_root = paths["project_root"]
        config_name  = paths["config_name"]

        con.blank()
        con.banner("[ Filelist Generator ] — Generating RTL Filelists")
        con.blank()
        handler = _FilelistHandler(config, config_name, project_root, con)
        handler.run(optimize=args.filelist_optimize)


# =============================================================================
# Internal handler
# =============================================================================

class _FilelistHandler:
    """RTL file discovery, parsing, duplicate resolution, filelist writing."""

    def __init__(self, config: dict, config_name: str,
                 project_root: Path, console):
        self.config       = config
        self.config_name  = config_name
        self.project_root = project_root
        self.con          = console

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, optimize: bool = False):
        rtl           = cfg_get(self.config, "rtl_configuration", default={})
        source_dirs   = cfg_get(rtl, "rtl_source_dirs",         default=[])
        file_excl     = cfg_get(rtl, "file_exclude_patterns",   default=[])
        folder_excl   = cfg_get(rtl, "folder_exclude_patterns", default=[])
        dut_top       = cfg_get(rtl, "dut_top_module")
        filelists_dir = self.project_root / "misc" / "filelists"
        mapping_path  = filelists_dir / f"duplicate_mapping_{self.config_name}.yaml"

        if not source_dirs:
            self.con.fatal("rtl_configuration.rtl_source_dirs is empty — "
                           "nothing to generate filelists from.")
        if not dut_top:
            self.con.fatal("rtl_configuration.dut_top_module is required "
                           "for filelist generation.")

        self.con.info("Discovering RTL files...")
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
                include_dirs = [d for d in include_dirs
                                if any(f.parent == d for f in ordered)]

            fl_path = filelists_dir / f"autogen_{nickname}.f"
            self._write_filelist(fl_path, ordered, unreachable, include_dirs)
            generated_filelists.append(fl_path)
            self.con.info(
                f"Written: {fl_path}  "
                f"({len(all_group_files)} files, {len(include_dirs)} include dirs)"
            )
            self.con.log_only(f"Filelist written: {fl_path}")

        self._write_autogen_marker(generated_filelists)

        if optimize and total_pruned > 0:
            self.con.warning(
                f"-flo pruned {total_pruned} unreachable file(s) from filelists. "
                f"See log for full list: {self.con.path}"
            )

        self.con.info(
            f"\nFilelist generation complete.\n"
            f"{len(generated_filelists)} filelist(s) written."
        )

    # ------------------------------------------------------------------
    # File discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_source_dir_entry(entry: str) -> tuple[str, str]:
        if ":" in entry:
            parts     = entry.rsplit(":", 1)
            path_part = parts[0].strip()
            nickname  = parts[1].strip()
        else:
            path_part = entry.strip()
            nickname  = Path(path_part).name
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
        module_to_files: dict[str, list[Path]] = {}
        file_to_deps: dict[Path, list[str]]    = {}

        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(self._parse_file, f): f for f in all_files}
            for future in as_completed(futures):
                fpath                 = futures[future]
                defined, instantiated = future.result()
                file_to_deps[fpath]   = instantiated
                for mod in defined:
                    module_to_files.setdefault(mod, []).append(fpath)

        return module_to_files, file_to_deps

    # ------------------------------------------------------------------
    # Duplicate resolution
    # ------------------------------------------------------------------

    def _resolve_duplicates(self, module_to_files, filelists_dir, mapping_path) -> dict:
        duplicates = {mod: files for mod, files in module_to_files.items()
                      if len(files) > 1}
        if not duplicates:
            if mapping_path.exists():
                mapping_path.unlink()
                self.con.info("No duplicates found. Previous duplicate mapping file removed.")
            return module_to_files

        existing_mapping         = (yaml.safe_load(open(mapping_path)) or {}
                                    if mapping_path.exists() else {})
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

        unresolved = [mod for mod, entry in updated_mapping.items()
                      if entry.get("file_to_use") == "Not Set"]
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
                            changes.append(
                                f"RESET {mod}: chosen file '{chosen_file}' no longer present"
                            )
                    except (ValueError, IndexError):
                        changes.append(
                            f"RESET {mod}: could not resolve old index {old_choice}"
                        )

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
