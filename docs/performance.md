# Time to first output

Where the time goes for a request, and what each setting trades. Measured on a CPU-only machine
(no GPU) with `gemma4:e2b`; on a GPU every number shrinks, but the *order* of the costs is the same.

```
embed query -> [executor model: pick tool + args] -> run tool -> [summarizer model] -> first token
   ~0.05 s            ~5-10 s on CPU                   ~1 s          ~4-6 s on CPU
```

## What the assistant does for you

| Optimisation | Effect | Setting |
| --- | --- | --- |
| **Warm-up**: the embedding model and the chat/executor/summarizer model are loaded in the background when `chat`/`ask` starts, with the same `num_ctx` the agents use (a different value would force a reload) | Removes 2-10 s of model loading from the first request | automatic |
| **No "are you done?" round trip**: after the first tool results the answer is written immediately. A second executor round only happens when the request sounds sequential ("... then ...") | Saves one full model call (about 3-5 s on CPU) per tool request | `runtime.followups: auto` |
| **Fast path**: when retrieval is decisive, the tool needs no arguments and is read-only (`disk_free`, `current_time`, `git_status`), the executor model is skipped and the tool runs straight away | Saves the whole tool-selection call (about 5-10 s on CPU). Precision on the golden set: 16/16 | `runtime.fast_path: true` |
| **Fewer tools in the prompt**: the executor sees 4 tools instead of 6 | Shorter prompt, faster prompt evaluation; recall@4 0.98 vs recall@6 1.00 | `retrieval.top_k: 4` |
| **Chit-chat costs no routing call** | Greetings go straight to the chat model | automatic |
| **Embedding failures degrade, not stall**: a failing embedding backend is skipped for 30 s | No repeated timeouts | automatic |

## Optional: fastest first output

`runtime.direct_output_chars: 600` shows a single small, successful, read-only tool result verbatim
instead of asking the model to summarise it. First output then arrives as soon as the tool finishes.
You trade a natural-language sentence for the raw command output, so it is off by default.

## Measured (CPU-only, cold models)

| Request | Before | Now | With `direct_output_chars` |
| --- | --- | --- | --- |
| "how much disk space do I have?" | 25.8 s | 8.8 s | 2.8 s |
| Same, models already warm | 8.7-13.7 s | about 6 s | about 1.5 s |

Requests that need arguments ("ping example.com") still pay for the executor call; that is the
remaining cost and is bounded by your hardware and model size.

## What else moves the needle

- **A GPU, or a smaller/faster executor model.** Prompt evaluation and token generation dominate.
  Tuning cannot beat hardware; `gemma4:e2b` is already the small option.
- **`num_ctx`.** A smaller context (for example 4096) makes every call cheaper if you do not need long
  histories. Keep it identical across agents that share a model.
- **Keep models loaded** (`keep_alive`, default 30 min) and avoid mixing many different models.
- **Tune with data**: `tala eval retrieval --embeddings -v` shows whether fewer tools or a stricter
  fast path would cost accuracy before you change a default.
