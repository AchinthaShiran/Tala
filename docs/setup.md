# Installing and first-run setup

## One-line install

The installers put the app in its own isolated environment (using `uv` or `pipx`, installing `pipx`
for you if neither is present) and then start the setup wizard.

```powershell
# Windows (PowerShell)
irm <URL-of-install.ps1> | iex
```

```sh
# macOS / Linux
curl -fsSL <URL-of-install.sh> | sh
```

Replace the placeholders with wherever you host the two files (for example the raw file URLs of your
repository). Both scripts need Python 3.11 or newer only when neither `uv` nor `pipx` is installed.

| Variable | Effect |
| --- | --- |
| `TALA_SOURCE` | What to install instead of the default package: a PyPI name, a git URL (`git+https://...`) or a local path |
| `TALA_NO_SETUP=1` | Install only; do not start the wizard |

The scripts keep the product name, command and package name in variables at the top, mirroring
`src/assistant/domain/branding.py`; a test fails if they drift apart.

You also need [Ollama](https://ollama.com/download) running locally. The wizard tells you if it is not.

## The setup wizard

```
tala setup                 # choose Default or Advanced interactively
tala setup --default       # recommended settings, no questions except the final confirmation
tala setup --advanced      # pick everything yourself
tala setup --check         # show detected hardware and the recommendation, change nothing
```

The wizard also offers itself once, automatically, the first time you run `tala chat` or `tala ask`
in a terminal with no configuration. Declining is remembered, so it never nags.

### What it detects

RAM, CPU threads and an NVIDIA GPU with its memory (via `nvidia-smi`); Apple Silicon is treated as
unified memory. Detection is best-effort and never fails: anything unknown is reported as unknown and
the advice becomes conservative.

### Default setup

Picks a model tier for your hardware and shows exactly what it will do before saving anything.

| Hardware | Recommended |
| --- | --- |
| No GPU (any amount of RAM) | **Light**: Gemma 4 E2B. On a CPU even small models answer in seconds, so larger ones mostly make things slower |
| GPU or Apple Silicon with roughly 10 GB or more usable | **Balanced**: Gemma 4 E4B |
| 24 GB or more usable | **Heavy**: GPT-OSS 20B |

Embeddings (`nomic-embed-text`) are included for accurate tool search. A separate routing model is only
recommended with real acceleration and 16 GB or more, because it costs resident memory and is
consulted rarely; otherwise the main model also does routing.

### Advanced setup

Choose from curated sets (`src/assistant/setup/catalog.yaml`):

| Step | Choices |
| --- | --- |
| Main model | Light, balanced and heavy models, each with download size, memory need and a marker for the recommendation, large models and models that may not fit |
| Routing model | Reuse the main model, or a small dedicated one |
| Embeddings | None (keyword search) or one of two embedding models |
| Context size | 4096, 8192, 16384, 32768 tokens, with the total memory each implies |
| Keep loaded | 5 minutes, 30 minutes, 2 hours, until Ollama stops |
| Approval rules | Default, strict (ask before every tool) or relaxed (not recommended) |
| Speed | Fast path, direct output |
| Command log | On or off |

**Resource warnings.** The wizard warns up front that larger models use much more memory, and again
whenever a choice matters:

- estimated memory against the memory this machine can actually use, as a heads-up or a serious
  "likely to swap, freeze or fail to load" warning;
- large models, which also need an explicit "use it anyway" confirmation;
- larger models without a GPU, large context sizes, models held in memory while idle;
- relaxed approval rules, which also need explicit confirmation.

Memory figures are estimates (weights plus an approximate context cache), meant to show relative cost.

### What it changes

- Writes only the values that differ from the built-in defaults to `config.yaml`, so future default
  improvements still apply to you.
- If a configuration already exists, your choices are **merged** into it and the previous file is kept as
  `config.yaml.bak`.
- Offers to download missing models (it shows the total size first). With `--yes` it never starts a large
  download unless you also pass `--pull`; `--no-pull` prints the manual `ollama pull` commands.
- Re-checks everything at the end and lists anything that still needs attention. `tala doctor` gives the
  full report at any time.

### Options

| Option | Meaning |
| --- | --- |
| `--default` / `--advanced` | Skip the first question (mutually exclusive) |
| `--yes`, `-y` | Accept the default answer to every question (advanced setup is interactive and rejects it) |
| `--pull` / `--no-pull` | Download missing models / do not (default: ask) |
| `--check` | Show hardware and recommendation only |
| `--config PATH` | Write to another config file |

## Changing the model list

`src/assistant/setup/catalog.yaml` is plain data: add a model, change a tier or a size estimate, or mark
a different default per tier. A test guards that the application defaults still exist in the catalog.
