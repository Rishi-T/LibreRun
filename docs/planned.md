# Planned Features

This page tracks confirmed and evaluated future work for LibreRun.  
Items marked **Confirmed** are committed to the design. Items marked **Evaluating** are under consideration.

---

## Confirmed

### Pre-Run Script Support
**Status:** Designed, not yet implemented.

A `pre_run_script` field under `flow_setup` in the config will allow the user to specify a script that LibreRun executes after invocation but before the simulation run itself.

The script will receive context from LibreRun as arguments or environment variables:
- Active config name
- `run_<N>/` directory path
- `PROJECT_ROOT`
- Any other relevant paths

**Intended use cases:**
- C → `.o` → `.hex` → `.txt` pipelines for RISC-V cores (feeding `$readmemh` in the TB)
- Custom pre-processing steps unique to a project

`pre_run_script` will be variant-aware — it can be set or overridden in supplementary configs. Scripts are expected to live in the project's `scripts/` folder by convention, though any path is accepted.

`librerun_version` in `flow_setup` is the only field that is **not** variant-aware.

---

### C++ Testbench Support
**Status:** Designed, not yet implemented.

A `tb_type` field under `tb_configuration` will select the testbench mode:

```yaml
tb_configuration:
  tb_type: sv     # current default
  # tb_type: cpp  # planned
```

In `cpp` mode:
- `tb_source_files` points to `.cpp` files instead of `.sv`
- Compile path splits into two steps: Verilator generates the C++ model, then `g++`/Make compiles the C++ TB against it
- Wave gating moves from `$test$plusargs("waves")` in SV to checking `argc/argv` in the C++ `main()`
- Sim invocation and log parsing remain identical

The rest of the flow (run directories, log parsing, pass/fail verdict, wave handling) is unchanged.

---

### Simulator Backend Selection
**Status:** Designed, not yet implemented.

A `simulator_backend` field under `flow_setup` will allow switching between simulation backends:

```yaml
flow_setup:
  simulator_backend: verilator   # default
  # simulator_backend: icarus    # planned
```

When introduced, compile and simulation option sections will gain backend-prefixed names (e.g. `verilator_compile_options`) to allow backend-specific configuration alongside backend-agnostic settings.

**Icarus Verilog** is the primary candidate for a second backend. It is event-driven (no Verilator-style synthesizability restrictions) and useful for designs or TB constructs that Verilator cannot handle.

---

### Auto TB File Picking
**Status:** Evaluating.

Automatically discover TB files by globbing `tb/` for `*.sv`/`*.v`, similar to how `-flg` works for RTL. Would be an opt-in behaviour rather than replacing explicit `tb_source_files` lists, since TB file ordering can be sensitive. Potential C++ support in the futre will further complicate things.

---

## Evaluating

### Multi-Simulator Regression Runner
Running the same TB across multiple seeds or configs in a single `lr` invocation, with an aggregated pass/fail summary. Likely implemented as a separate script or a new CLI flag rather than baked into `librerun.py`.

### GTKWave Save File Support
Automatically passing a `.gtkw` save file to GTKWave when `-g` is used, so signal groups and formatting are preserved across runs. Would be configured as an optional field in TB configuration.

### Supplementary Config Auto-Discovery Enhancements
Currently any `.yaml` in `env/` (other than `base_config.yaml`) is a valid supplementary config. Future work may add naming conventions, validation, or a `lr --list-configs` command to enumerate available configs.

### `--list-runs` / Run Comparison
A utility command to list all `run_<N>` directories for the current config with their timestamps, pass/fail verdict, and seed — parsed from stored logs.
