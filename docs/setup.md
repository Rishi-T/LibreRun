# Setup & Installation

## Directory Layout

LibreRun expects the following top-level layout:

```
librerun/
├── flow/
│   └── v0.1.RC/
│       ├── librerun.py
│       └── flow_config.yaml
├── projects/
│   └── <your_project>/
│       └── ...
└── misc/
    └── LibreRunSetup.sh
```

`flow/` holds one subdirectory per LibreRun version. `projects/` holds all your LibreRun projects. These paths are configurable.

---

## flow_config.yaml

Each versioned flow directory contains a `flow_config.yaml` that tells LibreRun where to find Verilator:

```yaml
verilator_configuration:
  verilator_base_path: /tools/verilator       # parent dir of all versioned installs
  verilator_version: v5.046                   # must match a subdirectory name
```

LibreRun will look for the Verilator binary at:  
`<verilator_base_path>/<verilator_version>/bin/verilator`

---

## LibreRunSetup.sh

`LibreRunSetup.sh` is a Bash script that must be **sourced** (not executed) to set up a terminal session. It exports `PROJECT_ROOT` and creates the `lr` alias pointing to the correct `librerun.py` version.

### Constants (edit once)

At the top of the script, set these three variables:

```bash
LIBRERUN_FLOW_BASE="/absolute/path/to/librerun/flow"
LIBRERUN_PROJECTS_BASE="/absolute/path/to/librerun/projects"
PYTHON_PATH="python3"
```

> Use `$HOME` or full absolute paths. Do **not** use `~` — it does not expand inside double quotes in Bash.

### Recommended `.bashrc` entry

```bash
alias lrs='source /absolute/path/to/LibreRunSetup.sh'
```

After adding this, run `source ~/.bashrc` once. From then on, `lrs` sets up a session.

---

## Selecting a Project

Run `lrs` from a terminal. The script determines your project via the following logic:

### With `-p <path>`
Explicitly specify a project root or its `env/` subdirectory:
```bash
lrs -p /path/to/my_project
lrs -p /path/to/my_project/env
```
If the path is outside `LIBRERUN_PROJECTS_BASE`, a warning is printed but the project is still used.

### With `-i`
Force the interactive picker regardless of CWD:
```bash
lrs -i
```

### Automatic CWD detection (default)
1. If CWD contains `env/base_config.yaml` → CWD is used as project root
2. If CWD is named `env` and contains `base_config.yaml` → parent is used as project root
3. Otherwise → warning printed, interactive picker launched

### Interactive Picker
Scans all subdirectories of `LIBRERUN_PROJECTS_BASE` for `env/base_config.yaml`, prints an enumerated list, and prompts you to select one. Enter `e` to exit without selecting.

---

## What the Script Sets

After a successful project selection, the script:

1. Reads `librerun_version` from `env/base_config.yaml` via grep/sed
2. Exports `PROJECT_ROOT` as the resolved absolute path of the project
3. Sets the `lr` alias:
   ```bash
   alias lr='python3 /path/to/flow/<version>/librerun.py'
   ```

From this point, `lr <args>` can be run from **any working directory** in that terminal session.

---

## Switching Projects or Configs

To switch projects in the same terminal, simply re-run `lrs`. The `PROJECT_ROOT` and `lr` alias will be updated.

To switch configs within the same project, pass `-cfg <name>` to `lr`. LibreRun remembers the last used config per user in `scripts/librerun_temp/.<user>_last_invocation`.
