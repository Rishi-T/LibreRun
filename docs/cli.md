# CLI Reference

All commands are invoked via the `lr` alias set by `LibreRunSetup.sh`.  
`lr` can be run from **any working directory** after a session is set up.

---

## Arguments

| Long | Short | Type | Description |
|------|-------|------|-------------|
| `--lint` | `-l` | flag | Lint-only Verilator check. No binary produced. Warnings are fatal. |
| `--compile` | `-c` | flag | Full Verilator compile. Warnings do not abort (use `-l` to clean them first). |
| `--run` | `-r` | flag | Run simulation using the existing compiled binary. |
| `--waves` | `-w` | flag | Enable FST waveform dump during simulation. |
| `--gui` | `-g` | flag | Enable FST dump and launch GTKWave live alongside the sim. Implies `-w`. |
| `--seed` | `-s` | scalar | Override simulation seed. `0` = random. |
| `--plusargs` | `-p` | list | Space-separated extra plusargs. No leading `+` needed. |
| `--config` | `-cfg` | scalar | Select a supplementary config by name (no `.yaml`). Defaults to last used, or `base_config`. |
| `--filelist_gen` | `-flg` | flag | Run RTL parser and generate filelists. See [Filelist Generation](filelist.md). |
| `--filelist_optimize` | `-flo` | flag | Prune unreachable files from generated filelists. Must be used with `-flg`. |

All flags are freely chainable in any combination.

---

## Default Config Behaviour

If `-cfg` is not passed, LibreRun uses the config from the last invocation (stored per-user in `scripts/librerun_temp/.<user>_last_invocation`). On first ever run, it defaults to `base_config`.

---

## Compile Behaviour

- `-c` invokes Verilator with `--binary --build-jobs 0 -Wno-fatal`
- Make and ccache handle incrementality — only changed files are recompiled
- If `-r` is run with no existing binary and without `-c`, LibreRun prints a friendly message and exits cleanly (no error)
- Running `-c` again without changing any files is safe and fast (ccache hit)

---

## Lint vs Compile

| | `-l` (lint) | `-c` (compile) |
|-|-------------|----------------|
| Verilator mode | `--lint-only` | `--binary` |
| Warnings fatal? | Yes | No (`-Wno-fatal`) |
| Binary produced? | No | Yes |
| Output | `simout/<cfg>/lint/lint_<ts>.log` | `simout/<cfg>/exe/compile.log` |
| Terminal | Suppressed (summary + log path on failure) | Suppressed (summary + log path on failure) |

Recommended workflow: run `-l` until clean, then `-c`.

---

## Simulation Run Numbering

Each `-r` invocation creates a new `simout/<config>/sim_runs/run_<N>/` directory.  
`N` is auto-incremented by scanning existing `run_*` directories. Runs are never overwritten.

---

## Waveforms

The testbench must gate `$dumpfile`/`$dumpvars` behind `$test$plusargs("waves")` — see the [README](../README.md) for the standard snippet.

- `-w` injects `+waves` at runtime, enabling the dump
- `-g` additionally launches GTKWave against the live `.fst` file in parallel with the sim
- GTKWave is polled for up to 2 seconds to allow the FST header to be written before opening
- Log parsing runs only after both sim and GTKWave are closed
- Requires `gtkwave` on PATH. Install with: `sudo apt install gtkwave`

---

## Plusargs

Plusargs from three sources are merged at runtime, in this order:
1. `simulation_options.persistent_plusargs` from config (always applied)
2. `-p` CLI plusargs (per-run)
3. Internal LibreRun plusargs (`+waves`, `+verilator+error+limit+N`, etc.)

Leading `+` is optional — LibreRun normalises all plusargs before passing them.

---

## Examples

```bash
# Lint only
lr -l

# Compile only
lr -c

# Compile then run
lr -c -r

# Run with waves, open GTKWave live
lr -r -g

# Run a specific variant config
lr -cfg fast_variant -r

# Compile + run + seed + extra plusargs
lr -c -r -s 42 -p test_mode=1 verbose

# Generate filelists
lr -flg

# Generate and optimize (prune unreachable files)
lr -flg -flo

# Generate filelists then immediately compile
lr -flg -c

# Full flow from scratch with GTKWave
lr -flg -flo -l -c -r -g
```
