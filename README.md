# Siphon

**Grab any video in real 4K.** A tiny, focused desktop app that downloads
YouTube (and other yt-dlp-supported) video at up to 4K — defeating YouTube's
SABR gating that quietly caps most downloaders at 360p — and hands you a clean
video file plus a separate audio track. No editor, no account, no cloud.

<!-- TODO: screenshot -->

## Why it exists

Most "4K downloaders" silently give you 360p right now, because YouTube gates
HD/4K streams behind a per-video **PO token** (the "SABR" experiment). Siphon
solves that end-to-end:

- uses a JavaScript runtime + yt-dlp's challenge solver,
- runs a local **PO-token provider** to unlock HD/4K stream URLs, and
- insists on the resolution you asked for (retrying on a token miss) instead of
  silently falling back to 360p.

## Quick start (from source)

```bash
git clone https://github.com/tehironclad/siphon.git
cd siphon
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
python -m siphon.setup_pot     # one-time: installs the PO-token provider
python -m siphon               # launches the app
```

Then paste a link and hit **Siphon**. Files land in `~/.siphon/downloads`.

### Prerequisites

| Tool | Why | Install |
|------|-----|---------|
| **Node.js 18+** | PO-token server + JS challenge solver | `winget install OpenJS.NodeJS.LTS` · `brew install node` · `apt install nodejs npm` |
| **ffmpeg** | Merge the separate 4K video + audio streams | Siphon can **auto-install** it from the app, or: `winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg` |

## A note on 4K codecs

YouTube has **no 4K H.264** — 4K is served as AV1 (mp4) or VP9 (mkv), both very
efficient (a 26-min 4K clip is only ~3 GB). Both are heavy to edit; transcode to
H.264/ProRes if you're dropping the file into Premiere/Final Cut.

## Environment knobs

| Variable | Effect |
|----------|--------|
| `SIPHON_HOME` | Data root (default `~/.siphon`) |
| `SIPHON_BIN_DIR` | Where an auto-downloaded ffmpeg lives |
| `SIPHON_POT_SERVER_HOME` | Location of the built PO-token server |
| `SIPHON_NO_REMOTE_COMPONENTS=1` | Disable the GitHub-fetched JS solver (HD/4K may become unavailable) |

## Legal

Siphon is a thin front end over [yt-dlp](https://github.com/yt-dlp/yt-dlp).
Download only content you have the right to, and respect the source site's
terms. Bundled components (yt-dlp, FFmpeg) retain their own licenses; Siphon's
own code is MIT (see [LICENSE](LICENSE)).
