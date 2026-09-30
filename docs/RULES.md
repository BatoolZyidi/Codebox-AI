# Engineering Rules: Codebox AI

## Safety
- Never write to a source file without an explicit spoken (or typed) "apply".
- Every change is dry-run validated first; a failed validation changes nothing.
- Every apply is backed up under `.codebox/backups/`; writes are atomic with rollback.
- Undo refuses to overwrite files the user changed after Codebox wrote them.
- Edits may not escape the project folder or touch `.git`, `.codebox`, `node_modules`, virtualenvs, `.env*`, key or credential files.
- Control words (apply, reject, undo...) only count when they are the *whole* utterance.

## Privacy
- API keys live only in `.env` (git-ignored). Never log or print them.
- Only files relevant to the current request are sent to Gemini; secrets and git-ignored files are never indexed.
- Microphone audio goes to AssemblyAI only while the program runs.

## Accessibility
- All functionality must work by voice alone; any information shown on screen must also be spoken.
- Keep spoken replies short (answers under ~80 words); details are available on request.
- Never rely on color or layout to convey meaning.

## Code
- Python 3.11+, `asyncio` for I/O; blocking calls (Gemini, disk scans) run in threads.
- Type hints throughout; format with `black`, lint with `ruff`.
- Every behavior change needs a test in `tests/`. Run `python -m pytest` before committing.
- Verify AssemblyAI and Gemini parameter/model names against their current documentation when upgrading.
