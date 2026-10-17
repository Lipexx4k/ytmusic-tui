# 🎧 YouTube Music TUI

A **minimalist, fast TUI client** for YouTube Music, right in your terminal: search, playback (mpv), music and album downloads (yt-dlp + ffmpeg) and a local library — **no Google account needed**.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-545%20passing-brightgreen)
![CI](https://github.com/pr0sthetics/ytmusic-tui/actions/workflows/ci.yml/badge.svg)
![Vibe-coded](https://img.shields.io/badge/vibe--coded-~80%25-ff69b4)

> ## ⚠️ Honesty warning: this project is ~80% "vibe-coded"
>
> Most of this code was written in **vibe coding** — talking to an AI assistant, with review, tweaks and manual testing by the author along the way. It has **545 automated tests** and real daily use, so it **actually works** — but expect rough edges: the occasional bug, "AI-looking" code here and there and missing features (see **Limitations**).
> Found a bug? Open an [issue](https://github.com/pr0sthetics/ytmusic-tui/issues). PRs are very welcome! 💜

---

## ✨ Features

- 🎵 **Music playback** via mpv (direct streaming, selectable quality)
- 🔍 **Search** for songs (25) and albums (15) in parallel, with type and year on albums (`💿 My Dear Melancholy, — The Weeknd  (EP, 2018)`)
- 💿 **Album tab**: open an album from the search and see tracks, artist and year — `Enter` plays (with a continuous queue) and `A` downloads the whole album, **skipping tracks already downloaded**
- 📥 **Download** via yt-dlp + ffmpeg: best stream available → MP3 320 kbps (or opus/m4a/flac), with ID3 tags and **embedded cover art**
- 📚 **Local library** in SQLite (no cloud): downloaded tracks, local likes and playback from the local file
- 📊 **Downloads** tab with real-time progress and configurable simultaneous downloads
- 🚫 **No login**: search, playback and download all operate anonymously
- ⌨️ Responsive **Textual** interface, with mouse support (tabs, lists, buttons) and vim-style shortcuts
- ⚡ **Lightweight**: no Electron, no browser — just Python + mpv

## 📸 Screenshots

### Search — songs and albums in separate sections

```text
 ⭘                                      YouTube Music TUI                                  04:43:20
  🏠 Início    🔍 Busca    📚 Biblioteca    📥 Downloads    ⚙️ Config
━━━━━━━━━━━━━━╸━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 ┌────────────────────────────────────────────────────────────────────────────────────────────────┐
 │  my dear melancholy                                                                            │
 └────────────────────────────────────────────────────────────────────────────────────────────────┘

 ┌────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                                                                                                │
 │  🎵 Músicas                                                                                    │
 │ ┌────────────────────────────────────────────────────────────────────────────────────────────┐ │
 │ │ I Was Never There — The Weeknd, Gesaffelstein  (4:02)                                      │ │
 │ │ Try Me — The Weeknd  (3:42)                                                                │ │
 │ │ my dear melancholy — msht  (2:16)                                                          │ │
 │ │ Wasted Times — The Weeknd  (3:41)                                                        ▆▆│ │
 │ │ Hurt You — The Weeknd, Gesaffelstein  (3:51)                                               │ │
 │ │ TMJ (Acoustic Version) — MOHXSIN  (2:22)                                                   │ │
 │ │ Privilege — The Weeknd  (2:51)                                                             │ │
 │ │ my dear melancholy (slowed) — msht  (2:33)                                                 │ │
 │ │ Rockstar without guitar (Remix) — MOHXSIN  (3:10)                                          │ │
 │ └────────────────────────────────────────────────────────────────────────────────────────────┘ │
 │  💿 Álbuns                                                                                     │
 │ ┌────────────────────────────────────────────────────────────────────────────────────────────┐ │
 │ │ 💿 My Dear Melancholy, — The Weeknd  (EP, 2018)                                            │ │
 │ │ 💿 my dear melancholy — msht  (EP, 2026)                                                   │ │
 │ └────────────────────────────────────────────────────────────────────────────────────────────┘ │
 │                                                                                                │
 └────────────────────────────────────────────────────────────────────────────────────────────────┘

────────────────────────────────────────────────────────────────────────────────────────────────────
                                             ┌───┐ ┌───┐ ┌───┐            0:00   ━━━━━━━━━━━━━━━━━
                                             │ ⏮ │ │ ⏯ │ │ ⏭ │
                                             └───┘ └───┘ └───┘
```

### Album tab — `Enter` on a search result opens it here; `A` downloads the whole album

```text
 ⭘                                      YouTube Music TUI                                  04:43:21
  🏠 Início    🔍 Busca    💿 My Dear Melancholy    📚 Biblioteca    📥 Downloads    ⚙️ Config
━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 💿 My Dear Melancholy, — The Weeknd · 2018 · 6 faixas

 ┌────────────────────────────┐
 │ ⬇ Baixar álbum inteiro (a) │
 └────────────────────────────┘

 ┌────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ Call Out My Name — The Weeknd  (3:49)                                                          │
 │ Try Me — The Weeknd  (3:42)                                                                    │
 │ Wasted Times — The Weeknd  (3:41)                                                              │
 │ I Was Never There — The Weeknd, Gesaffelstein  (4:02)                                          │
 │ Hurt You — The Weeknd, Gesaffelstein  (3:51)                                                   │
 │ Privilege — The Weeknd  (2:51)                                                                 │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 └────────────────────────────────────────────────────────────────────────────────────────────────┘

────────────────────────────────────────────────────────────────────────────────────────────────────
                                             ┌───┐ ┌───┐ ┌───┐            0:00   ━━━━━━━━━━╺━━━━━━
                                             │ ⏮ │ │ ⏯ │ │ ⏭ │
                                             └───┘ └───┘ └───┘
```

*(Screenshots of the real app, with live API data; colors vary with your terminal theme.)*

## 📋 Requirements

- **Python 3.11+**
- **mpv** (with libmpv) — it's the player. On most distros the `mpv` package already includes libmpv (if the app won't open, see *Common installation problems*)
- **ffmpeg** — conversion and tagging of downloads
- Python dependencies (ytmusicapi, textual, yt-dlp, sqlalchemy…) are installed via pip/pipx along with the app
- A terminal with colors (256/true color) and Unicode — **minimum 80×24**, 100×30+ recommended

## 🖥️ Compatibility

| Platform | Status |
|------------|--------|
| **Linux** | ✅ **Tested** — developed and used on LMDE 7 (Debian 13 base). Any distro with Python 3.11+ and mpv should work |
| **macOS** | 🟡 Untested — should work with `brew install mpv ffmpeg` |
| **Windows (WSL2)** | 🟡 Untested — works inside WSL following the Linux instructions |
| **Windows (native)** | ❌ Not officially supported — would require configuring the libmpv DLL manually |

## ✅ Known-good versions

Validated combinations (the exact Python dependency set used in CI is in [`uv.lock`](uv.lock); the floors are in `pyproject.toml`):

| Component | Validated version | How to check |
|---|---|---|
| **Python** | 3.11–3.13 (CI runs on 3.11 and 3.13; author's development on 3.13.5) | `python3 --version` |
| **mpv / libmpv** | mpv 0.40.0 with libmpv.so.2 (LMDE 7 / Debian 13) | `mpv --version \| head -n1` · `ldconfig -p \| grep libmpv` |
| **ffmpeg** | 7.1.5 (Debian 13) | `ffmpeg -version \| head -n1` |
| **yt-dlp** | floor `>=2024.1.0` in pyproject; 2026.8.19 in the author's environment | `yt-dlp --version` · in the venv: `python -c "import yt_dlp; print(yt_dlp.version.__version__)"` |
| **ytmusicapi** | floor `>=1.8.0` in pyproject; 1.12.3 in the author's environment (checked at runtime on the ⚙️ Config tab, T10) | in the venv: `pip show ytmusicapi \| head -n2` |

**yt-dlp** changes often (YouTube keeps changing the rules of the game): keep it up to date — Dependabot already opens a weekly PR, and an update that breaks playback shows up in CI before the merge.

## 📦 Installation

### 1. System dependencies

```bash
# Ubuntu / Debian / Linux Mint / LMDE
sudo apt install mpv ffmpeg python3-venv

# Arch / Manjaro / EndeavourOS
sudo pacman -S mpv ffmpeg python

# Fedora
sudo dnf install mpv ffmpeg python3

# openSUSE
sudo zypper install mpv ffmpeg python3

# macOS (Homebrew)
brew install mpv ffmpeg python
```

### 2. Install the app

**Option A — pipx (recommended, isolated environment):**

```bash
pipx install git+https://github.com/pr0sthetics/ytmusic-tui
```

**Option B — pip:**

```bash
pip install --user git+https://github.com/pr0sthetics/ytmusic-tui
```

**Option C — from source (for development):**

```bash
git clone https://github.com/pr0sthetics/ytmusic-tui
cd ytmusic-tui
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/ytmusic-tui    # or: .venv/bin/python main.py
```

### 3. Configuration (optional)

The app **works with no configuration at all**. If you want to tweak the player, downloads and interface:

```bash
mkdir -p ~/.config/ytmusic-tui
cp config.example.toml ~/.config/ytmusic-tui/config.toml
```

### Common installation problems

- **`Cannot find libmpv in the usual places`** (or a similar python-mpv message) when opening the app: Python couldn't find libmpv. On Ubuntu/Debian also install `sudo apt install libmpv-dev` — it provides the `libmpv.so` symlink Python looks for (on Ubuntu 24.04, for example, the `mpv` package alone is not always enough).
- **Music doesn't play / the stream fails**: it's almost always yt-dlp out of date with some YouTube change — update the app and yt-dlp in the same install environment (`pip install -U yt-dlp` in the venv, or `pipx upgrade` + `pipx runpip ytmusic-tui install -U yt-dlp`).

## 🚀 Usage

```bash
ytmusic-tui              # installed via pip/pipx
python -m ytmusic_tui    # as a module
python main.py           # straight from the source tree (uses src/, no install)
```

### Basic flow

1. `Ctrl+S` to go to the search → type and press `Enter`
2. `Enter` on a song plays it; `→` / `←` move through the queue
3. `Enter` on an album opens the 💿 tab with its tracks; `A` (or the button) downloads the whole album
4. `Ctrl+D` downloads the track now playing — follow it on the 📥 Downloads tab
5. `Ctrl+L` opens the local library: play straight from the downloaded files

### Keyboard shortcuts

| Key | Action |
|-------|------|
| `Ctrl+S` | Go to the search |
| `Enter` | Play track / open selected album |
| `Space` | Play/Pause |
| `→` / `←` | Next / previous |
| `Ctrl+D` | Download the track now playing |
| `A` | Download the whole album (album tab) |
| `Esc` | Back from the album to the search |
| `L` | Like / unlike (local, for downloaded tracks) |
| `Ctrl+L` | Go to the library |
| `F1` | Help |
| `Ctrl+Q` | Quit |

The mouse works too: click on tabs, results and buttons.

## ⚙️ Configuration

File: `~/.config/ytmusic-tui/config.toml` (every key is optional).
The app's **Config** tab edits the main options and writes to that same file right away.

| Key | Default | Description |
|-------|--------|-----------|
| `mpv_volume` | `50` | Initial volume (0–100) |
| `mpv_audio_quality` | `"high"` | Stream used by mpv: `low`, `medium`, `high`, `best` |
| `download_dir` | `"~/Music/YouTube Music"` | Downloads directory |
| `download_format` | `"mp3"` | Format: `mp3`, `opus`, `m4a` or `flac` |
| `download_quality` | `"320"` | Bitrate in kbps (mp3/opus) or `"best"` |
| `download_concurrent` | `3` | Simultaneous downloads (1–10) |
| `embed_metadata` | `true` | ID3 tags + embedded cover art in the files |
| `show_notifications` | `true` | Toast notifications |
| `auto_play_next` | `true` | Automatically play the next track in the queue |
| `library_db_name` | `"library.db"` | SQLite file name of the local library |
| `config_dir`, `data_dir`, `cache_dir` | XDG | Internal directories (advanced, usually don't touch) |

Environment variables prefixed with `YTMUSIC_` take priority over the TOML (handy for isolated testing):

```bash
YTMUSIC_DOWNLOAD_DIR=/tmp/teste YTMUSIC_DATA_DIR=/tmp/teste ytmusic-tui
```

### Where the files live (Linux)

| What | Path |
|-------|---------|
| Configuration | `~/.config/ytmusic-tui/config.toml` |
| Library (SQLite) | `~/.local/share/ytmusic-tui/library.db` |
| Cache | `~/.cache/ytmusic-tui/` |
| Downloads | `~/Music/YouTube Music/` |
| Log | `~/.local/state/ytmusic-tui/log/ytmusic-tui.log` |

*(On macOS/Windows the equivalent `platformdirs` paths are used.)*

Internal errors (for example, failing to reach the library database) show up
in the interface itself **and** in the app log — check the two sections below
before opening an issue.

### Logs (`~/.local/state/ytmusic-tui/log/ytmusic-tui.log`)

The log is **JSON Lines**: each line is a JSON object with fixed fields (`ts`,
`level`, `component`, `operation_id`, `event`, `error_code`, `message` and, on
errors, `detail` with the traceback). Important events — app start/stop (with
the versions), download started/finished/failed, API retries, database
migrations, database errors, quarantine and recovery — carry their own `event`
and `error_code`, which makes diagnosis greppable:

```bash
jq -c 'select(.event != null)' ~/.local/state/ytmusic-tui/log/ytmusic-tui.log | tail
```

Privacy is enforced by the app itself when writing: HOME becomes `~`, URLs
lose query/token and credential headers become `[REDACTED]` — none of that
stays raw in the file. The log is 0600, with 1 MB × 3 backups rotation
(4 MB maximum in total).

### Diagnostics (`ytmusic-tui doctor`)

The `ytmusic-tui doctor` command (or `python -m ytmusic_tui doctor`) checks
the environment **without opening the interface** — the checks do not create,
change or download any files: versions (app, Python, ytmusicapi, yt-dlp),
libmpv and the `mpv`/`ffmpeg` binaries, directories (existence, writability,
mode), the library database read-only (`integrity_check` + schema version ×
app) and maintenance leftovers (quarantine, backups, log).

```bash
ytmusic-tui doctor
```

The output is masked (same rules as the log) and made to be pasted into an
issue — still, review it before sharing. Exit code `0` = nothing essential
broken; `1` = something essential (libmpv or a dependency missing, a
directory without write access, a database unreadable/corrupted or newer
than the app).

## 🔧 How it works (under the hood)

- **[ytmusicapi](https://github.com/sigma67/ytmusicapi)** (unofficial) in **anonymous mode** for search and metadata — the search fires requests in parallel and takes ~2s
- **[mpv](https://mpv.io/)** (via libmpv/python-mpv) plays the streams; mpv uses the **yt-dlp installed alongside the app** as its extractor (`ytdl_hook-ytdl_path`), so playback follows the up-to-date yt-dlp instead of mpv's old built-in extractor
- **[yt-dlp](https://github.com/yt-dlp/yt-dlp) + ffmpeg** download the best audio stream and convert it to the configured format, with cover art and tags
- **SQLAlchemy + SQLite** hold the local library (downloaded tracks, likes)

> **Why no login?** Google turned off ytmusicapi's OAuth authentication in 2025 — tokens started being rejected with HTTP 400 ([sigma67/ytmusicapi#813](https://github.com/sigma67/ytmusicapi/issues/813)). Since search, playback and download work anonymously, this client chose to operate **without an account**: no synchronization, everything local.
>
> ⚙️ Technical detail: libmpv requires `LC_NUMERIC=C`, but ytmusicapi switches the locale to `en_US.UTF-8` (and mpv aborted because of that). The app restores the locale before starting the player.

## ⚠️ Limitations

**Account and library:**
- No login: likes, playlists and recommendations **from your account** don't show up; the `L` "like" is **local** and only works for tracks already downloaded
- There's no synchronization with YouTube Music — the library lives only in your `library.db`

**Search and catalog:**
- Up to **25 songs + 15 albums** per query
- No advanced filters (search by artist, playlist, sorting etc.)
- Playlists are not supported yet (see the Roadmap)

**Downloads and quality:**
- The real quality depends on the source: YouTube Music typically serves **~128–256 kbps** audio (AAC/Opus); the "MP3 320" is a conversion — it doesn't create quality, but it standardizes the files
- Downloads depend on yt-dlp; when YouTube changes something, updating yt-dlp in the same environment (or reinstalling/updating the app) usually fixes it

**Young project:**
- Interface and messages **in Portuguese**
- **~80% vibe-coded** (warning at the top 🙂): the 545 tests cover the main flow, but the occasional bug is expected
- No MPRIS, lyrics, equalizer, automatic radio or themes (Roadmap)

## 🆘 When something breaks (and it's not the app)

Not every failure is a bug here: the app depends on external services and
tools that change all the time. Short checklist, from the cheapest step to
the most specific:

1. **First step: `ytmusic-tui doctor`.** It checks versions, libmpv,
   `mpv`/`ffmpeg`, directories and the library database read-only, and the
   output is already masked to paste into an issue. Exit `0` = nothing
   essential broken; exit `1` = something essential is off (the report says
   what). More in *Logs* and *Diagnostics* above.
2. **The YouTube Music contract changed.** Symptoms: structure/field errors
   when searching or opening an album, or a red contract run (the weekly
   `contract.yml` workflow). From a source checkout, run the real-integration
   tests and attach the per-field/per-item report to the issue:
   `YTMUSIC_INTEGRATION=1 .venv/bin/python -m pytest tests/test_integration.py -v -s`.
   A green `doctor` with a red contract run points outside: the service
   changed, not your install.
3. **yt-dlp extraction broke** (YouTube changed the rules of the game).
   Symptoms: downloads fail, or the log shows a yt-dlp error or an
   `FFMPEG_EXIT_N` error code. Update yt-dlp in the same install environment
   (`pip install -U yt-dlp` in the venv, or
   `pipx runpip ytmusic-tui install -U yt-dlp`) and watch for the Dependabot
   PR; yt-dlp's own issue tracker usually tells whether it's a known YouTube
   change.
4. **Network, rate limit, block or service down.** Timeouts, 5xx, 403, "are
   you a robot", rate limiting, region restrictions: try again later —
   inconclusive is neither corrupted data nor a bug.
5. **mpv/libmpv or ffmpeg missing.** Symptoms: the player doesn't open, or
   the downloads' conversion fails. `doctor` flags it; install the system
   packages from *Installation* above (`mpv` — plus `libmpv-dev` on
   Ubuntu/Debian — and `ffmpeg`).
6. **How to report:** the `doctor` output + a log excerpt + the versions
   involved. The log is already masked (no tokens, signed URLs or
   credentials), so you don't need to censor it by hand.

And a reminder: the contract check runs **every Monday** (`contract.yml`) —
a red run there is an external problem, not your installation.

## 🗂️ Project structure

```text
ytmusic-tui/
├── main.py                    # Shortcut to run from source (uses src/ directly)
├── pyproject.toml             # Metadata and dependencies (pip/pipx)
├── config.example.toml        # Commented configuration template
├── src/ytmusic_tui/
│   ├── main.py                # Entry point of the `ytmusic-tui` console script
│   ├── config/                # Configuration (pydantic-settings + TOML persistence)
│   ├── api/                   # Anonymous ytmusicapi (search, albums)
│   ├── player/                # mpv player (libmpv) + yt-dlp integration
│   ├── download/              # yt-dlp download queue (progress, concurrency)
│   ├── library/               # SQLite library (SQLAlchemy)
│   ├── log.py                 # File logging (with rotation)
│   └── tui/                   # Textual interface
│       ├── app.py             # App lifecycle + main() (app.tcss next to it)
│       ├── screens.py         # MainScreen: tabs, shortcuts and navigation
│       ├── widgets.py         # Custom widgets (lists, player bar)
│       └── *_controller.py    # Playback, downloads and library (mixins)
└── tests/                     # 545 tests in layers (L1 mocks + L2 local) + opt-in integration
```

## 🛠️ Development

```bash
git clone https://github.com/pr0sthetics/ytmusic-tui
cd ytmusic-tui
uv sync --locked --extra dev    # creates/updates .venv from uv.lock

# Tests (offline, everything mocked — L1 + L2)
.venv/bin/python -m pytest tests/ -q

# Branch coverage for download/library/player (informative, no threshold)
.venv/bin/python -m pytest tests/ -q \
  --cov=ytmusic_tui.download --cov=ytmusic_tui.library --cov=ytmusic_tui.player \
  --cov-branch --cov-report=term

# Lint
.venv/bin/ruff check src/ tests/

# Formatting
.venv/bin/ruff format src/ tests/

# Real integration tests (they talk to the real YouTube Music; disabled by default)
YTMUSIC_INTEGRATION=1 .venv/bin/python -m pytest tests/test_integration.py -v -s

# Vulnerability audit of the locked set (the same one CI audits)
uv export --frozen --no-emit-project --extra dev --no-hashes -o /tmp/ytm-locked.txt
.venv/bin/pip-audit -r /tmp/ytm-locked.txt
```

**[uv](https://docs.astral.sh/uv/)** is the development/CI tool: `uv.lock` pins the exact runtime + dev versions and CI installs from it (`uv sync --locked`). If `pyproject.toml` and `uv.lock` drift apart, `--locked` fails on purpose — after editing dependencies, run `uv lock`. No uv? `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"` still works (without the lockfile — CI is what uses it).

The tests cover the TUI (via Textual's `run_test`), API, player, downloads and library, in two offline layers: **L1** (unit/behavior, with thin mocks) and **L2** (`tests/integration_local/` — local integration with the worker, reservation/temporary files and a real database, plus "real" fakes: yt-dlp stubbed at the late import and an **executable** ffmpeg on PATH). **No test in the standard suite touches the network or the real player** — L2 blocks `socket` on purpose, so any connection fails immediately with a clear message; branch coverage (command above) is informative, with no threshold.

Two more test layers are **opt-in**, never run in CI:

- **L3 — real integration** (`tests/test_integration.py`): talks to the real YouTube Music and compares the raw service response with the contract the adapters consume, producing a per-field and per-item report when the format changes (run with `-s` to see the report). It also runs **every Monday at 06:00 UTC** in the `contract.yml` workflow (`workflow_dispatch` runs it on demand). Zero-noise rule: **inconclusive** (offline, service down, runner blocked) makes the tests skip with an explicit reason and the run stays green; a **contract break** fails with the report and the run turns red — the useful signal.
- **L4 — controlled end-to-end** (`tests/e2e/`, opt-in with `YTMUSIC_E2E=1`): builds the wheel, installs it in a clean venv and runs the real flow (doctor → search → album → player → download) fully isolated in tmp. Runbook in `tests/e2e/README.md`.

The **CI (GitHub Actions)** runs `ruff` + the offline suite on Python 3.11 and 3.13 on every push, **installing from `uv.lock`** (`uv sync --locked` — the job fails if the lockfile is missing or out of sync with `pyproject.toml`), a security job that exports the locked set and runs `pip-audit` (fails on a known vulnerability) and a package job that checks the wheel/sdist contents and installs the wheel in a clean environment. Branch coverage (download, library and player) runs in the test job as an **informative** step — no threshold and no CI blocking —, on a single leg (Python 3.13).

Dependencies are updated by **Dependabot** (weekly PRs, dev/runtime groups — with the lockfile, it updates `uv.lock` and `pyproject.toml` together): CI runs on every PR, so an update that breaks the app is visible there before it lands — handy for a project that depends on external services that change often (YouTube, mpv, yt-dlp).

### Releases and updates

Each release corresponds to a **traceable commit** with the version in `pyproject.toml` and an entry in `CHANGELOG.md`, an annotated tag (`vX.Y.Z`) and a **green CI on the commit** (e.g.: `v0.1.2` → commit `84b6d80`). Releases are **manual** — nothing is published automatically; artifact hashes (SHA-256) and process automation are a future step.

Dependency updates follow a single path: **Dependabot opens the PR → mandatory CI (3.11/3.13 + lockfile + pip-audit + package) → manual merge**. Merging is not releasing: no update goes straight into a stable release.

## 🗺️ Roadmap

- [ ] Local playlists
- [ ] Automatic radio/mix (infinite autoplay)
- [ ] Synced lyrics
- [ ] MPRIS control (desktop integration)
- [ ] Equalizer
- [ ] Custom themes
- [ ] Last.fm / ListenBrainz integration

## 📄 License

MIT — see [LICENSE](LICENSE) for details. © 2026 Eeyore.

## 💜 Credits

- [ytmusicapi](https://github.com/sigma67/ytmusicapi) — unofficial YouTube Music API
- [Textual](https://github.com/Textualize/textual) — TUI framework
- [mpv](https://mpv.io/) — media player
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — audio download
- [ffmpeg](https://ffmpeg.org/) — conversion and metadata
- [Rich](https://github.com/Textualize/rich), [SQLAlchemy](https://www.sqlalchemy.org/) and [pydantic](https://docs.pydantic.dev/) — the rest of the stack
