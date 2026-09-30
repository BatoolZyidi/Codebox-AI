# Product Requirements: Codebox AI

## Summary
A voice-driven coding assistant for blind, low-vision, and motor-impaired developers. The user speaks; Codebox AI searches the whole project folder, answers or proposes a change, narrates it, and applies it only after spoken approval.

## Problem
- Screen readers make multi-file code exploration and refactoring slow.
- AI coding tools assume you can visually review diffs and use a keyboard and mouse.
- Generic speech-to-text mangles identifiers such as `getUserByID`.

## Users
Blind and low-vision developers; developers with RSI or motor impairments; anyone who wants hands-free code exploration.

## Requirements (all implemented)

| ID | Requirement | Status |
| --- | --- | --- |
| FR-01 | Continuous streaming transcription via AssemblyAI | Done |
| FR-02 | Project names boosted in recognition (keyterms) | Done |
| FR-03 | Search across the entire project folder | Done (symbols + paths + contents) |
| FR-04 | Gemini proposes answers and exact edits | Done |
| FR-05 | Every change narrated in plain language | Done |
| FR-06 | Voice commands: apply, reject, details, read again, undo, help | Done |
| FR-07 | Safe patching: dry run, backup, atomic write, undo | Done |
| FR-08 | Wake by "wakeup codebox AI"; sleep/close by "close yourself codebox AI" | Done |
| FR-09 | Own voice never triggers commands | Done |

## Non-goals
Running/debugging code by voice; hosting user source in the cloud; a graphical UI.

## Success criteria
A user can, by voice alone: wake it, ask where something is, request a multi-file rename, hear it described, apply it, undo it, and put it to sleep.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Wrong or unsafe edit | Exact-match validation, spoken approval, backup, undo |
| Misheard command | Control words must be the entire utterance; anything else is treated as a request, never as "apply" |
| Model/API changes | Model names and endpoint are settings in `.env`; `check` command diagnoses quickly |
| Large repositories | Incremental index; only top-ranked files (or excerpts) sent per request |
