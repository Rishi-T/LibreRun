# Project Layout

## Full Directory Structure

```
<project_name>/
├── env/
│   ├── base_config.yaml               # primary project config (required)
│   └── <variant_name>.yaml            # supplementary configs (optional)
├── rtl/                               # RTL source files
├── tb/                                # Testbench source files
├── misc/
│   └── filelists/
│       ├── autogen_<nickname>.f       # auto-generated filelists (-flg)
│       └── duplicate_mapping_<cfg>.yaml
├── scripts/
│   ├── librerun_logs/
│   │   └── <user>_<YYYYMMDD_HHMMSS>.log   # one log per invocation
│   └── librerun_temp/
│       ├── .<user>_last_invocation         # last-used config + args
│       └── .autogen_<config_name>          # autogen filelist marker
└── simout/
    └── <config_name>/
        ├── exe/
        │   └── compile.log            # Verilator + Make output
        ├── lint/
        │   └── lint_<YYYYMMDD_HHMMSS>.log
        └── sim_runs/
            └── run_<N>/
                ├── sim.log
                └── waves.fst          # only present if -w or -g was used
```

---

## Key Conventions

### `env/`
Contains all YAML configs for the project. Only `base_config.yaml` is required. Any other `.yaml` file here is treated as a supplementary (variant) config. See [Config Reference](config.md) for schema details.

### `rtl/` and `tb/`
No enforced internal structure. LibreRun discovers files via `rtl_source_dirs` and explicit `tb_source_files` lists in the config. You can organise subdirectories however you like.

### `misc/filelists/`
Output directory for `-flg` generated filelists and the duplicate mapping file. Do not manually edit auto-generated `.f` files — re-run `-flg` instead.

### `scripts/librerun_logs/`
One log file is written per LibreRun invocation, regardless of which commands were run. Filenames sort chronologically. Verbose output that is suppressed from the terminal (duplicate mapping changes, pruned file lists, compile/lint output) is always written here.

### `scripts/librerun_temp/`
Internal marker files. Do not edit manually unless you know what you're doing.

### `simout/`
All build and run output. Each config gets its own subdirectory. Within each:
- `exe/` — persistent compiled binary (`V<tb_top_module>`), Verilator intermediates, and `compile.log`
- `lint/` — one log per `-l` invocation
- `sim_runs/run_<N>/` — auto-incrementing; each `-r` invocation creates a new run directory containing `sim.log` and optionally `waves.fst`

### Environment Variables in Config
All string values in both `base_config.yaml` and supplementary configs are expanded through `os.path.expandvars` at load time. Use `$PROJECT_ROOT`, `$HOME`, or any other exported variable freely in paths.
