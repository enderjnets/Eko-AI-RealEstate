# The render worker

Turns a clip into a publishable video on the machine that has the media stack,
and hands it back. It is a separate program on purpose: transcription needs a
speech model, and assembly needs minutes of CPU, and neither belongs in the
container a lead is waiting on.

**It reaches in; nothing reaches out to it.** The worker polls the panel over
HTTPS and no port is opened on the render machine. That is the only direction
that works through the tunnel and the only one that needs no firewall change.

**It cannot approve anything.** The finished video lands in the approval queue,
where a licensed agent still has to look at it. The worst a broken — or
compromised — worker can do is waste render time and put a bad video in front
of a person.

## Install (on the render machine)

```bash
python3 -m venv ~/.venvs/eko-render
~/.venvs/eko-render/bin/pip install -r ~/eko-render/app/requirements.txt
install -m 600 /dev/null ~/.eko-render.env      # then fill it in, see below
mkdir -p ~/.config/systemd/user
cp ~/eko-render/app/eko-render-worker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now eko-render-worker
systemctl --user status eko-render-worker
```

`systemctl --user`, never cron: the crontab on that machine is rewritten from a
backup every fifteen minutes by another project's self-heal, so a line added
there disappears without warning.

## `~/.eko-render.env` (mode 600, never printed, never committed)

```
EKO_API_BASE=https://inmo-demo.ekoaiautomation.com
RENDER_WORKER_TOKEN=…            # must match the panel's
RENDER_WORKER_NAME=rog-1
RENDER_WORKER_HOURS=13,15,16,17,21,23,1,2
```

`RENDER_WORKER_HOURS` are local hours on this machine, and they are checked on
every tick rather than declared to systemd. `OnCalendar=` with `Persistent=true`
fires a missed run late — after a power cut, that is a render starting in the
middle of somebody else's window.

Lane B adds:

```
MINIMAX_API_KEY=…               # the narrator
MINIMAX_GROUP_ID=…
RENDER_TTS_VOICE_ID=…           # pick one from three sampled voices
KLING_ACCESS_KEY=…              # images only — the video package of that
KLING_SECRET_KEY=…              # account is reserved for another project
PEXELS_API_KEY=…                # the free fallback
RENDER_KLING_IMAGES_PER_DAY=8   # real money, and the balance is SHARED with
                                # two other projects on this machine
```

Going over that cap does not degrade our video — it stops somebody else's
publishing. The ledger lives in `RENDER_CACHE_DIR` and the cache key is the
prompt itself, checked before the request rather than after it.

## Requirements on the machine

`ffmpeg` and `ffprobe` on PATH. Whisper runs on the **CPU** deliberately. The
GPU on that machine is shared with two other projects, and the free VRAM was
measured at 3.4 GB one afternoon and 6.0 GB the next — it depends on what a
model server happens to be holding. Any number written here would be wrong by
the time somebody read it, which is the argument for not needing one.
