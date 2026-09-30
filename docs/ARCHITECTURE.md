# Architecture: Codebox AI

## Principles

1. **Voice in, voice out.** The spoken summary is the primary interface.
2. **Local-first.** The repository is indexed and searched on your machine; only the few relevant files per request go to Gemini.
3. **Names first.** Voice requests mention functions and files, so exact/spoken-form matching beats a vector database here.
4. **Never mutate without consent.** Dry run -> narrate -> spoken "apply" -> backup -> write -> undo available.

## Pipeline

```
 Microphone (16 kHz PCM, 50 ms chunks)
      |                                  ^ muted (silence sent) while Codebox speaks
      v
 AssemblyAI streaming STT  <-- keyterms: wake/close phrases + spoken names from the repo index
      |  finished utterance ("turn")
      v
 Assistant (state machine)
   asleep: ignore everything except the wake phrase
   awake : close phrase? -> sleep/exit
           control word?  apply | reject | details | read it again | undo | help
           otherwise      -> request pipeline
      |
      v  request pipeline
 RepoIndex.refresh()  (incremental: only changed files re-parsed)
      -> retrieve(): symbols + path + content scoring over the WHOLE folder
      -> build_prompt(): tree + symbols + top files (excerpts for big files) + recent conversation
      -> Gemini -> JSON {kind: answer|change|clarify, spoken, edits[]}
      -> plan_changes(): dry-run every edit against the real files (1 retry with the error fed back)
      -> summary + details text  -> Text-to-speech
      |
      v  user says "apply"
 apply_changes(): backup originals -> atomic writes (rollback on failure)   ("undo" restores)
```

## Modules (`codebox/`)

| Module | Responsibility |
| --- | --- |
| `cli.py` | Commands: `run` (voice), `chat` (typed), `check`, `devices`, `index` |
| `assistant.py` | Wake/sleep state machine, voice commands, request pipeline, pending change |
| `stt.py` | AssemblyAI v3 WebSocket client: streaming, dedupe of turns, echo suppression, auto-reconnect, keyterm fallback |
| `audio.py` | Microphone capture via `sounddevice` |
| `tts.py` | Speech via the OS voice (macOS `say`, Windows SAPI, Linux `espeak-ng`); reports when it is talking |
| `wake.py` | Forgiving phrase matching ("wake up, code box A.I." matches "wakeup codebox AI") |
| `indexer.py` | Incremental symbol index. Python via `ast`; JS/TS, Go, Rust, Java/C#/Kotlin, PHP, Ruby, C/C++ via regex |
| `search.py` | Retrieval and scoring; builds keyterms for speech recognition |
| `llm.py` | Gemini call, prompt building, strict JSON parsing |
| `edits.py` | Edit planning (dry run), unified diff, apply with backup, undo with tamper check |
| `summary.py` | Spoken summary and per-edit details |
| `safety.py` | Ignored/protected folders, secret-file detection |
| `config.py` | Settings from `.env` (pydantic-settings) |

## Design decisions

- **Exact-text edits instead of model-written diffs.** LLMs get diff line numbers wrong. Gemini returns `{path, old, new}` replacements; Codebox verifies `old` exists exactly (once, unless `replace_all`) and produces the unified diff itself. Bad edits are caught before anything is shown.
- **Search without vectors.** Scoring combines symbol-name match (including spoken forms such as "get user" -> `getUser`), path match, and content term frequency. Optional local embeddings (Chroma/FAISS) could be added as a fallback for meaning-based queries.
- **`ast` + regex instead of Tree-Sitter.** No native compilation on any OS; Python is parsed exactly, other languages approximately. The `extract_symbols()` function is the single place to swap in Tree-Sitter.
- **No echo.** While the assistant speaks, silence replaces microphone audio and transcripts arriving during/just after speech are dropped.
- **Sleeping is cheap and safe.** While asleep, only the wake phrase is acted on; all other speech is ignored.

## Safety model

See `docs/RULES.md`. In short: consent required, dry run first, backup + undo, protected paths, secrets never read or sent, no path escapes.

## Not included

A VS Code extension and a hosted web demo were dropped from this version to keep the local voice experience solid. `.codebox/last_change.patch` provides the diff for any editor or `git apply`.
