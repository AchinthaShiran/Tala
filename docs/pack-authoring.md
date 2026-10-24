# Writing tool packs

A pack is one YAML file. Drop it in a pack directory and the assistant can use it.

| Layer (later wins) | Location |
| --- | --- |
| builtin | shipped with the package |
| user | `<config dir>/packs/` (see `deskaide doctor`) |
| project | `./.deskaide/packs/` (ignored until you run `deskaide packs trust` in that directory) |
| extra | `packs.dirs` in `config.yaml` |

Always run `deskaide packs validate` after editing. It uses the same rules the loader uses, and `--strict`
also fails on warnings (good for CI).

## File format

```yaml
pack: net-extras            # required: pack name (used for policy overrides and disabling)
version: 1.0.0              # optional
description: Extra network tools.
tools:
  - name: ping_host         # ^[a-z][a-z0-9_]{1,63}$
    description: Check whether a host or IP address is reachable and measure round-trip time.
    risk: read_only         # required: read_only | mutating | destructive
    category: network       # optional, indexed
    keywords: [ping, reachable, latency]            # optional, indexed
    examples:                                        # at least 1 required, 2+ recommended, indexed
      - ping google.com
      - is 8.8.8.8 reachable
    timeout: 45             # seconds, default 30
    max_output_bytes: 64000 # default 64000
    output_encoding: utf-8  # or e.g. cp850; `oem` = Windows console code page
    confirm_message: ...    # required when risk is destructive
    parameters:
      host:
        type: string        # string | integer | number | boolean
        description: Host name or IP address
        pattern: '^[A-Za-z0-9._:-]+$'
        max_length: 253
      count:
        type: integer
        description: Number of echo requests
        default: 4
        minimum: 1
        maximum: 10
    run:
      windows: {exe: ping, args: [-n, "{count}", "{host}"]}
      linux:   {exe: ping, args: [-c, "{count}", "{host}"]}
      macos:   {exe: ping, args: [-c, "{count}", "{host}"]}
```

### Run variants

`run` maps a platform (`windows`, `linux`, `macos`, `any`) to `{exe, args}`. The exact platform wins,
otherwise `any`. A tool with no variant for the current OS, or whose `exe` is not on `PATH`, is
**unavailable**: it is never offered to the model and `deskaide packs list --all` says why.

Give one *logical* tool the same name and schema on every OS; only the command differs. The model
then sees a stable capability (`disk_free`) rather than OS-specific commands (`df`, `Get-PSDrive`).

### Arguments

`args` is a list of strings with `{param}` placeholders, rendered into an argv list (**no shell is
ever involved**). A placeholder is replaced only where it appears; other braces are literal.

Conditional arguments appear only when the parameter was supplied and is not `false` or empty:

```yaml
args:
  - uninstall
  - {when: keep_data, args: [-k]}          # boolean flag
  - {when: record_type, args: ["-type={record_type}"]}
  - "{package_name}"
```

Rules the loader enforces (violations are errors naming the file and tool):

- every `{placeholder}` and every `when:` refers to a declared parameter;
- every declared parameter is used by at least one variant;
- a parameter that is optional **and has no default** may only be used inside a `when:` block;
- `risk` is present; `destructive` tools have a `confirm_message`;
- constraints fit the type (`pattern`/`max_length` for strings, `minimum`/`maximum` for numbers),
  defaults match the type, regexes compile;
- tool names are unique within a root (a later root may deliberately override an earlier one).

### Parameter constraints are your security boundary

The model fills parameters; treat every value as untrusted.

- Values for string parameters may **not start with `-`** unless you set `allow_dash: true`. This stops a
  value from being read as a command option (`git add --force`).
- Always add `pattern` (or `enum`, or at least `max_length`) to string parameters.
  The linter warns when a string parameter has none of them.
- **Re-parsing commands (`adb shell ...`, `ssh host ...`, `cmd /c ...`, `powershell -Command ...`)
  re-interprets arguments with another shell.** Constrain those values to a safe alphabet
  (`^[A-Za-z0-9._/@+-]+$`) and never interpolate user values into script text. The builtin tests check this
  for the `adb shell` tools.
- Prefer `enum` for anything with a small set of valid values.

### Choosing `risk`

| Level | Use for | Default approval |
| --- | --- | --- |
| `read_only` | Only reads or reports (`df`, `git status`, `ping`) | auto |
| `mutating` | Changes state but is recoverable (`git commit`, `docker stop`, install a package) | ask (yes/no) |
| `destructive` | Hard to undo or affects others (`kill`, delete, `git push`, uninstall) | confirm (user types the tool name) |

When unsure, choose the higher level. A user can relax or tighten per tool/pack in `config.yaml`, but
destructive tools can never be made automatic.

### Writing for retrieval

The index searches `name`, `description`, `keywords`, `category` and `examples`. The cheapest accuracy
win is realistic `examples`: the phrases a person would actually type ("is my laptop charging").
Use `deskaide eval retrieval -v` and add cases to the golden set when a request picks the wrong tool.

## Cookbook

**Read-only command with an optional filter**

```yaml
- name: list_containers
  description: List docker containers, optionally only those whose name contains some text.
  risk: read_only
  examples: [which containers are running, show docker containers named web]
  parameters:
    name_filter:
      type: string
      description: Only show containers whose name contains this text
      optional: true
      pattern: '^[A-Za-z0-9_.-]+$'
      max_length: 64
  run:
    any:
      exe: docker
      args:
        - ps
        - {when: name_filter, args: ["--filter", "name={name_filter}"]}
```

**Destructive command**

```yaml
- name: delete_branch
  description: Delete a local git branch that has been merged.
  risk: destructive
  confirm_message: This permanently deletes the branch reference.
  examples: [delete the branch feature-x, remove merged branch old-work]
  parameters:
    branch: {type: string, description: Branch name, pattern: '^[A-Za-z0-9._/-]+$', max_length: 100}
  run:
    any: {exe: git, args: [branch, -d, "{branch}"]}
```

**Disable or override**

```yaml
# config.yaml
packs:
  disabled_tools: [kill_process]
  disabled_packs: [winget]
safety:
  tool_overrides: {git_status: auto}
  pack_overrides: {docker: ask}
```

To replace a builtin tool, define a tool with the same name in a user or project pack.

## Not supported (yet)

- Long-running or interactive programs (GUI apps, `scrcpy`, `ssh` sessions): commands are killed at `timeout`.
- Piping several commands together in one tool. Make separate tools, or call a script file you control
  with fixed arguments.
- Script/HTTP/MCP tool kinds. The design leaves room (see architecture, extension points).
