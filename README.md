# Codebox AI

**A voice-first coding assistant that explains proposed changes before applying them.**

Codebox AI helps blind and motor-impaired developers explore and edit a codebase by voice. It indexes and searches a selected project locally, sends relevant context to Google Gemini, and speaks its answers and proposed changes. It never applies a proposed edit until you say **apply**.

Built for the AssemblyAI Voice Agent Hackathon (lablab.ai, September 2026).

## What it does

- Listen for a configurable wake phrase, then accept spoken questions and coding requests.
- Search project files, symbols, paths, and code content. Python symbols are parsed with `ast`; other supported languages use regular-expression extraction, so their symbol results are approximate.
- Use AssemblyAI streaming speech-to-text and Google Gemini for responses and edit proposals.
- Read responses aloud with the operating system's speech engine.
- Preview changes before applying them. Applying creates backups; the last applied change can be undone.
- Provide typed `chat` mode for testing or use without a microphone.

Typical voice flow:

1. Say `wakeup codebox AI` after the ready announcement.
2. Ask a question or request a change, for example, “where is login handled?”
3. For a proposed change, say `details`, `apply`, or `reject`. Say `undo` after applying to restore the previous files.
4. Say `close yourself codebox AI` to put the assistant to sleep, or press Ctrl+C to stop it.

Other voice commands include `read it again` and `help`. The wake phrase can be changed in `.env`.

## Requirements

- Windows, macOS, or Linux.
- Python 3.11 or newer.
- A working microphone and speakers or headphones for voice mode.
- API keys for [AssemblyAI](https://www.assemblyai.com/) (speech recognition) and [Google AI Studio](https://aistudio.google.com/) (Gemini).
- Linux: install PortAudio and a speech engine, for example `sudo apt install libportaudio2 espeak-ng` on Debian/Ubuntu.

API usage may incur charges or be subject to provider quotas. Check the current terms and limits for your accounts.

## Install on a new machine

Clone this repository, then open a terminal in the cloned `codebox-ai` directory.

**Windows (PowerShell or Command Prompt):**

```powershell
setup.bat
```

**macOS or Linux:**

```bash
./setup.sh
```

The setup script creates a `.venv` environment, installs dependencies, and creates `.env` from `.env.example` if needed. Open `.env` and set both required keys:

```dotenv
ASSEMBLYAI_API_KEY=your_assemblyai_key
GEMINI_API_KEY=your_gemini_key
```

Keep `.env` private; it is excluded by `.gitignore`. Do not put real API keys in source files or commit them.

Run the setup check from the `codebox-ai` directory:

```powershell
.\run.bat check
```

```bash
./run.sh check
```

The check tests configured keys, microphone and speech-engine availability, Gemini, and AssemblyAI. A successful check confirms the services respond, but voice recognition still depends on your OS microphone permissions and selected input device.

## Run against a project

Pass the target repository path to the runner. The assistant indexes that folder, not the folder containing Codebox AI.

**Windows voice mode:**

```powershell
.\run.bat run "C:\path\to\your\project"
```

To launch it while PowerShell is in any directory, call the runner by its full path:

```powershell
& "C:\path\to\codebox-ai\run.bat" "C:\path\to\your\project"
```

**macOS or Linux voice mode:**

```bash
./run.sh run /path/to/your/project
```

**Typed mode (Windows):**

```powershell
.\run.bat chat "C:\path\to\your\project"
```

**Typed mode (macOS or Linux):**

```bash
./run.sh chat /path/to/your/project
```

In chat mode, type a question or request at the prompt; enter `quit` to leave. Add `--speak` when invoking the Python CLI directly if you also want chat replies spoken.

Other useful commands are `check` (test setup), `devices` (list audio devices), and `index` (show indexed files and symbols). For example, use `run.bat devices` on Windows or `./run.sh devices` on macOS/Linux.

## Configuration

Settings are read from `.env` in the Codebox AI installation directory. Command-line `--repo` selects the target project; alternatively, set `CODEBOX_REPO`.

| Setting | Purpose | Default |
| --- | --- | --- |
| `ASSEMBLYAI_API_KEY` | Required speech-to-text key | unset |
| `GEMINI_API_KEY` | Required Gemini key | unset |
| `WAKE_PHRASE` | Phrase that wakes the assistant | `wakeup codebox AI` |
| `CLOSE_PHRASE` | Phrase that puts it to sleep or exits | `close yourself codebox AI` |
| `CLOSE_ACTION` | `sleep` keeps listening; `exit` quits | `sleep` |
| `MIC_DEVICE` | Input device name or number; list with `devices` | system default |
| `TTS_ENABLED` | Enable spoken responses | `true` |
| `GEMINI_MODEL` | Gemini model name | `gemini-3.5-flash-lite` |
| `IDLE_TIMEOUT_SECONDS` | Sleep after inactivity; `0` disables timeout | `0` |

See [`.env.example`](.env.example) for all optional settings and [SETUP_GUIDE.md](SETUP_GUIDE.md) for detailed installation and troubleshooting.

## Privacy and change safety

- Repository indexing and retrieval happen locally. Only selected relevant file contents and context are sent to Gemini when you make a request; the full repository is not uploaded for indexing.
- Microphone audio is streamed to AssemblyAI while voice mode is running, including while the assistant is asleep. Stop the program with Ctrl+C when finished.
- Secret files and ignored/protected paths are excluded from retrieval and edits. Review [docs/RULES.md](docs/RULES.md) for the safety rules.
- Proposed edits are checked against the current files and shown before application. Nothing is written until you approve. Backups and undo data are stored under `.codebox/` in the target project.

## Development and tests

Install development dependencies and run the test suite:

```powershell
python -m pip install -r requirements.txt
python -m pytest
```

The tests use local fakes for service-dependent behavior; the `check` command separately tests live API connectivity.

## Project structure

| Path | Purpose |
| --- | --- |
| `codebox/` | Application modules: CLI, audio, streaming STT, assistant, Gemini, search, edits, and safety |
| `tests/` | Automated tests for voice flow, STT, search, edits, wake matching, and TTS |
| `docs/ARCHITECTURE.md` | Processing pipeline and design decisions |
| `docs/PRD.md` | Product requirements |
| `docs/RULES.md` | Safety and editing rules |
| `SETUP_GUIDE.md` | Detailed setup and troubleshooting |
| `.env.example` | Configuration template; contains no API keys |

