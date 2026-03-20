# Config Reference

## flow_config.yaml

Lives in `flow/<version>/`. Configures the Verilator installation to use.

```yaml
verilator_configuration:
  verilator_base_path: <str>    # parent directory of versioned Verilator installs
  verilator_version:   <str>    # must match a subdirectory name under base_path
```

---

## base_config.yaml

The primary per-project config. Must exist at `env/base_config.yaml`.  
All paths support environment variable expansion (`$PROJECT_ROOT`, `$HOME`, etc.).

```yaml
# -------------------------------------------------------------------------
# Section 0 — Flow Setup
# librerun_version is only read from base_config; ignored in supplementary
# configs with a warning. pre_run_script is planned but not yet implemented.
# -------------------------------------------------------------------------
flow_setup:
  librerun_version: <str>
  # pre_run_script: <path>    # planned

# -------------------------------------------------------------------------
# Section 1 — Project Metadata
# -------------------------------------------------------------------------
project_configuration:
  project_name: <str>
  author:       <str>
  description:  <str>

# -------------------------------------------------------------------------
# Section 2 — RTL Configuration
# -------------------------------------------------------------------------
rtl_configuration:
  dut_top_module: <str>             # required; used by filelist gen + compile

  rtl_source_dirs:                  # recursively searched for *.sv / *.v
    - <path>                        # plain path; nickname defaults to folder name
    - <path>:<nickname>             # nicknamed; controls autogen filelist filename
    - <path>:<same_nickname>        # same nickname = files merged into one .f

  rtl_manual_filelists:             # passed to Verilator via -f, compiled first
    - <path>                        # before any autogen filelists

  file_exclude_patterns:            # glob patterns matched against filename
    - "*_stub*"

  folder_exclude_patterns:          # glob patterns matched against path components
    - "*tb*"

# -------------------------------------------------------------------------
# Section 3 — TB Configuration
# -------------------------------------------------------------------------
tb_configuration:
  tb_top_module: <str>              # required

  tb_source_files:                  # explicit list; no auto-discovery yet
    - <path>

  tb_filelists:                     # passed to Verilator via -f
    - <path>

  tb_include_dirs:                  # passed as -I to Verilator
    - <path>

  info_keywords:                    # matched case-insensitively in sim.log
    - <str>                         # hits counted and shown in post-sim summary

  warning_keywords:
    - <str>                         # hits counted; do not affect pass/fail

  error_keywords:
    - <str>                         # any hit → FAIL verdict

# -------------------------------------------------------------------------
# Section 4 — Compile Options
# -------------------------------------------------------------------------
compile_options:
  defines:                          # passed as -D<define>
    - <str>

  verilator_flags:                  # passed directly to Verilator
    - <str>                         # applied to both -l (lint) and -c (compile)
                                    # e.g. -Wno-TIMESCALEMOD, -Wno-DECLFILENAME

# -------------------------------------------------------------------------
# Section 5 — Simulation Options  (applied every run)
# -------------------------------------------------------------------------
simulation_options:
  persistent_plusargs:              # no leading + needed; added to every -r run
    - <str>

  error_limit: <int>                # optional; +verilator+error+limit+N
  seed:        <int>                # optional; 0 = random. Overridable via -s
```

---

## Supplementary Config (variant)

Any `.yaml` file in `env/` other than `base_config.yaml` is a supplementary config.  
Select one with `-cfg <name>` (no `.yaml` extension needed).

Supplementary configs are **merged over** `base_config` at runtime:
- **Lists** → appended to base lists
- **Scalars** → override base scalars

```yaml
# -------------------------------------------------------------------------
# Section 0 — Flow Setup
# librerun_version is IGNORED here (warning printed).
# pre_run_script IS variant-aware and will be honoured here (planned).
# -------------------------------------------------------------------------
flow_setup:
  # librerun_version: <ignored>
  # pre_run_script: <path>

# -------------------------------------------------------------------------
# Section 1 — Variant Metadata  (supplementary only; no equivalent in base)
# -------------------------------------------------------------------------
variant_configuration:
  variant_name: <str>
  author:       <str>
  description:  <str>

# Sections 2-5 use identical keys to base_config.
# Any key present here will merge per the rules above.
rtl_configuration:
  ...
tb_configuration:
  ...
compile_options:
  ...
simulation_options:
  ...
```

### Example use cases for supplementary configs
- Change `dut_top_module` or RTL parameters for a different design variant
- Add extra defines for a specific test scenario
- Override `tb_top_module` for a targeted testbench
- Point to a different set of RTL source directories entirely

---

## Notes

- `librerun_version` in `flow_setup` is only ever read from `base_config.yaml`
- `rtl_include_dirs` is intentionally absent from the schema — include directories are handled via `-incdir` lines inside manual and auto-generated filelists
- All string paths in both config files are expanded via `os.path.expandvars` at load time
