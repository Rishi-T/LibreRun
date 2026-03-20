# LibreRun

A lightweight, Verilator-based SystemVerilog simulation flow for pure-SV testbenches.  
Designed for RTL experimentation, learning, and small-to-medium designs — with a clean CLI, persistent builds, and structured run output.

> ⚠️ **This is very much a WIP tool. Expect rough edges.**

---

## Prerequisites

- Python 3.10+ with `pyyaml` (`pip install pyyaml`)
- [Verilator](https://verilator.org) (built and installed to a versioned path)
- `ccache` — recommended for faster incremental builds (`sudo apt install ccache`)
- `gtkwave` — required only for `-g` / `--gui` (`sudo apt install gtkwave`)
- Bash (WSL2/Ubuntu fully supported)

---

## Quick Start

```bash
# 1. Configure constants in LibreRunSetup.sh (one time)
#    Set LIBRERUN_FLOW_BASE, LIBRERUN_PROJECTS_BASE, PYTHON_PATH

# 2. Add a session alias to ~/.bashrc (one time)
echo "alias lrs='source /path/to/LibreRunSetup.sh'" >> ~/.bashrc
source ~/.bashrc

# 3. Select a project (run from project root, or anywhere with -i)
lrs

# 4. Lint, compile, and run
lr -l          # lint only
lr -c          # compile
lr -r          # run sim
lr -c -r -w    # compile + run + dump waves
lr -r -g       # run with live GTKWave
```

---

## Documentation

| Doc | Contents |
|-----|----------|
| [Setup & Installation](docs/setup.md) | LibreRunSetup.sh, constants, first run walkthrough |
| [Project Layout](docs/project_layout.md) | Directory structure, simout layout, file conventions |
| [Config Reference](docs/config.md) | Full schema for `base_config.yaml`, `flow_config.yaml`, supplementary configs |
| [CLI Reference](docs/cli.md) | All arguments, chaining, examples |
| [Filelist Generation](docs/filelist.md) | `-flg` / `-flo`, duplicate mapping, config additions |
| [Planned Features](docs/planned.md) | Confirmed and evaluated future work |

---

## TB Wave Gating Convention

LibreRun always compiles with FST trace support baked in. Wave dumping is gated at runtime by a plusarg — add this to every testbench top:

```systemverilog
initial begin
    if ($test$plusargs("waves")) begin
        $dumpfile("waves.fst");
        $dumpvars(0, tb_top);
    end
end
```

Pass `-w` or `-g` to LibreRun to enable dumping. No recompile needed to toggle.

---

## License

TBD
