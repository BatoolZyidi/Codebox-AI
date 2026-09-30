# Setup Guide (local)

Everything runs on your own computer. Follow the steps in order. Total time: about 10 minutes.

## 1. What you need

- **Python 3.11 or newer** - check with `python --version` (or `python3 --version`).
- A **microphone** (a headset is best) and speakers/headphones.
- Two API keys:
  - **AssemblyAI** - create a free account at assemblyai.com, then copy the key from your dashboard.
  - **Google Gemini** - create a key in Google AI Studio (aistudio.google.com) -> "Get API key".
- **Linux only:** `sudo apt install libportaudio2 espeak-ng` (microphone library and a voice).
  macOS and Windows already include a voice, and the pip package includes the microphone library.

## 2. Install

**Windows** (Command Prompt or PowerShell, inside the `codebox-ai` folder):
```
setup.bat
```
**macOS / Linux** (Terminal, inside the `codebox-ai` folder):
```
./setup.sh
```
This creates a private Python environment in `.venv`, installs everything, and creates a `.env` file.

<details><summary>Prefer doing it by hand?</summary>

```
python -m venv .venv
# Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
# copy .env.example to .env
```
</details>

## 3. Add your keys

Open the file named **`.env`** (in the `codebox-ai` folder) in any text editor and fill in:

```
ASSEMBLYAI_API_KEY=paste_your_assemblyai_key_here
GEMINI_API_KEY=paste_your_gemini_key_here
```
Save it. No quotes and no spaces around `=`. Never share this file.

## 4. Check everything works

```
run.bat check          (Windows)
./run.sh check         (macOS / Linux)
```
You should see `[PASS]` for both keys, the microphone, the speech engine, Gemini, and AssemblyAI, and you will hear "Codebox AI speech test." Any `[FAIL]` line tells you what to fix (see Troubleshooting below).

## 5. Try it by typing first (no microphone needed)

```
run.bat chat "C:\path\to\your\project"
./run.sh chat /path/to/your/project
```
Type questions like `where is the main function?`. This confirms Gemini and your project folder work before adding voice. Add `--speak` to hear the replies (`python -m codebox chat --repo ... --speak`).

## 6. Run with your voice

```
run.bat run "C:\path\to\your\project"
./run.sh run /path/to/your/project
```
(If you run it from inside your project folder, you can leave the path off.)

Wait for: **"Codebox AI is ready. Say wakeup codebox AI to begin."** Then:

| You say | What happens |
| --- | --- |
| **wakeup codebox AI** | Wakes it up. You can add a request in the same breath: "wakeup codebox AI, where is login handled?" |
| any question or request | It searches your whole folder and answers or proposes a change |
| **apply** / **reject** | Accept or discard a proposed change |
| **details** | Hear each edit one by one |
| **read it again** | Repeat the last message |
| **undo** | Reverse the last applied change |
| **help** | Hear what you can say |
| **close yourself codebox AI** | Puts it to sleep (it keeps listening only for the wake phrase) |

Stop the program completely with **Ctrl+C**, or set `CLOSE_ACTION=exit` in `.env` so the close phrase quits it.

## Good to know

- **Nothing changes without "apply".** The last proposed change is also saved as `.codebox/last_change.patch` inside your project, so a sighted colleague can review it.
- **Backups:** every applied change is backed up in `.codebox/backups/`, which `undo` uses. Codebox adds a `.gitignore` inside `.codebox/` so it never gets committed.
- **Cost and privacy:** while the program runs, microphone audio streams to AssemblyAI (billed by session time, also while "asleep"). Stop the program when you're not using it. For each request, only the few relevant files are sent to Gemini; `.env`, key files, and everything in `.gitignore` are excluded.
- **While it talks it cannot hear you.** Wait for it to finish before speaking.
- **Best results:** name things the way you'd say them ("get user"), and keep requests to one change at a time.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `Missing ASSEMBLYAI_API_KEY` | `.env` is missing or empty. It must be in the `codebox-ai` folder (not `.env.example`). |
| `[FAIL] Microphone found - PortAudio library not found` | Linux: `sudo apt install libportaudio2`. |
| Microphone found but nothing is heard | Run `run.bat devices`, then set `MIC_DEVICE=` in `.env` to the number of your microphone. On macOS/Windows, allow microphone access for your terminal in system privacy settings. |
| No speech output | Linux: `sudo apt install espeak-ng`. Also check `TTS_ENABLED=true`. |
| `AssemblyAI refused the connection (HTTP 401)` | The AssemblyAI key is wrong or has no credit. |
| Gemini check fails with 404 / model not found | Set `GEMINI_MODEL=` in `.env` to a model your key can use (see Google AI Studio). |
| It wakes up by itself or never wakes up | Run in typed `chat` mode to confirm the rest works; try a quieter room or a headset; adjust `WAKE_PHRASE` in `.env` to a phrase you can say clearly. |
| It misses a code name | Say it as separate words ("get user by id"). Names from your project are auto-boosted at each start, so restart after adding many new names. |
| `I couldn't prepare a safe change` | The AI suggested text that doesn't match your file exactly. Nothing was changed; rephrase and try again. |

Run the tests any time (needs `pip install -r requirements.txt`): `python -m pytest`
