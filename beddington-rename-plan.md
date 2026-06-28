# Beddington rename plan

**Goal:** rename the project from its accumulated names — **Lullaby**, **Paddington**, **Labie/labie** — to a single canonical name: **Beddington**. Cover code, packaging, tests, config, deploy, docs, the GitHub repo, and the local working folder.

**Author:** Claude (planning + inventory). **Executor:** Codex. **Approver:** Mo.
**Status:** Verified by Codex (APPROVE-WITH-FIXES) — all 5 fixes folded in. Pending Mo sign-off, then execution. See §10.
**Date:** 2026-06-28.

---

## 0. Decisions locked (from Mo, 2026-06-28)

1. **Scope = everything, including repo + folder.** Rename the GitHub repo `moelzek/Labie → moelzek/Beddington`, the local folder `~/Code/Labie → ~/Code/Beddington`, the Python package, the distribution name, and the console command — plus all code and docs.
2. **Wake word = Beddington, keep Paddington as a working alias.** The spoken default becomes **"Hi Beddington"**, but the voice assistant still wakes to **"Paddington"** (kept in `WAKE_WORDS`). The **physical plush stays a "Paddington bear"** — that literal hardware wording is preserved wherever it describes the real toy.
3. **Scrub current files including `Archive/`; no git history rewrite.** Past commit messages are left untouched. In-file name references in current files (incl. `Archive/`) are updated, with the historical-record caveats in §8.

---

## 1. Canonical name mapping (the spec)

| Old | New | Surface |
|---|---|---|
| `Lullaby` | `Beddington` | product name, page titles, persona, prose |
| `lullaby` | `beddington` | package, command, paths, lowercase identifiers |
| `LULLABY_` | `BEDDINGTON_` | environment-variable prefix |
| `lullaby-monitor` | `beddington-monitor` | Python distribution name |
| `src/lullaby/` | `src/beddington/` | package directory (import root) |
| `lullaby.cli:main` | `beddington.cli:main` | console entry point |
| `Labie` / `labie` | `Beddington` / `beddington` | repo, folder, slug, Pi path |
| `github.com/moelzek/Labie` | `github.com/moelzek/Beddington` | GitHub slug |
| `~/Code/Labie` | `~/Code/Beddington` | local working folder |
| `/home/lab/Labie`, `~/Labie` | `/home/lab/Beddington`, `~/Beddington` | Pi deploy paths |
| `lullaby-liveview.service` | `beddington-liveview.service` | systemd unit |
| `paddington.service` | `beddington-assistant.service` | systemd unit |
| `~/.config/lullaby/` | `~/.config/beddington/` | config + token dir |
| `~/.local/share/lullaby/` | `~/.local/share/beddington/` | sensors.db / state |
| `~/.cache/lullaby/` | `~/.cache/beddington/` | model cache |
| `lullabyRotate` | `beddingtonRotate` | dashboard localStorage key |
| `LullabyLiveView/1` | `BeddingtonLiveView/1` | HTTP Server header |
| `lullaby-radar` | `beddington-radar` | radar device name |
| `lullaby/0.1` (User-Agent) | `beddington/0.1` | HTTP User-Agent |
| `lullaby-*` temp prefixes | `beddington-*` | tempfile prefixes |
| Wake word default `Paddington` | `Beddington` (Paddington kept as alias) | voice assistant |

**Counts found (case-insensitive):** `lullaby` ≈ 246 lines across ~15 `.py` + 21 test files + 13 docs; `paddington` ≈ 32 (wake word / service / persona); `labie` ≈ 25 (folder/slug/Pi path, none inside `.py`); `beddington` ≈ 6 already present (wake-word migration was started).

---

## 2. DO NOT CHANGE — explicit exceptions

These look like hits but must be left alone (a blind find-replace will break them):

- **`src/lullaby/assistant.py:290`** — `_mentions(q, "music","song","melody","lullaby")`. Here `lullaby` is the **common noun** for a soothing song (a soothe-preset trigger). Renaming it breaks "play a lullaby" voice matching.
- **`baby-monitor-evaluation.md:28` and `:57`** — `lullaby` used as the ordinary word for a soothe sound ("Lullaby / white-noise / parent voice"). Not the product.
- **"Paddington bear" plush** — wherever text describes the **physical toy** the device lives in (e.g. `memory.md` ~L188 "the companion lives in a Paddington bear"). Keep per Decision 2.
- **Kept wake-word alias** — the literal `"paddington"` (and its fuzzy variants) stays in `src/.../ears.py` `WAKE_WORDS` so the assistant still wakes to the old word.
- **Generic infra** — `?token=…`, `127.0.0.1`, ports (8088, 11434), `http://127.0.0.1:11434` / `ollama.local` hosts. Not name-derived.
- **Generic data filenames** — `events.json`, `night-log.txt`, `morning-digest.txt`. No name embedded.
- **Third-party links** — e.g. `github.com/karolpiczak/ESC-50` and other non-`moelzek` URLs in docs / `sample_data/README.md`.
- **`pyproject.toml:30`** `pythonpath = ["src"]` — points at `src/`, not the package; unaffected.
- **`src/lullaby/ears.py:74`** comment "(e.g. \"lullaby\")" — a stale example, not a product-name hit. Optional comment tidy (→ "beddington"); not required.
- **git commit history** — not rewritten (Decision 3).

After execution, the only `lullaby`/`labie` strings that may remain are the items in this list plus preserved historical changelog lines (§8).

---

## 3. Execution order (one commit per phase)

Phases 1–2 are a **single atomic change set** — do not commit Phase 1 without Phase 2, or the suite breaks. Run `python -m pytest` after every phase.

### Phase 1 — Python package + in-code identifiers (load-bearing)

1. `git mv src/lullaby src/beddington` (moves all 26 modules; their filenames carry no old name).
2. **Verify imports are relative** before trusting this: `git grep -nE '^\s*(from|import)\s+lullaby'` must return **nothing** (discovery found all intra-package imports use `from .x`). If any absolute import exists, rewrite it to `beddington.*`.
3. `pyproject.toml` — three coupled edits:
   - L6 `name = "lullaby-monitor"` → `"beddington-monitor"`
   - L22 `lullaby = "lullaby.cli:main"` → `beddington = "beddington.cli:main"`
   - L25 `packages = ["src/lullaby"]` → `["src/beddington"]`
   - (Leave L30 `pythonpath = ["src"]`.)
4. **In-code string literals** (now under `src/beddington/`):
   - `__init__.py:1` docstring `Lullaby` → `Beddington`.
   - `config.py:208–216` env vars `LULLABY_LLM_ENABLED/BASE_URL/MODEL/API_KEY`, `LULLABY_SOOTHE_ENABLED/PLAYER` → `BEDDINGTON_*`.
   - `detector.py` — `LULLABY_YAMNET_MODEL` (L109), cache dir `~/.cache/lullaby/models` (L113), User-Agent `lullaby/0.1` (L124), tempfile prefix `lullaby-yamnet-` (L125).
   - `llm.py:16–17,56` — `LULLABY_LLM_*` in error string + User-Agent.
   - `autosoothe.py:20` — `~/.config/lullaby/autosoothe.json`.
   - `cli.py` — `prog='lullaby'` (L49), `~/.local/share/lullaby/sensors.db` (L260/278/581), `~/.config/lullaby/liveview.token` (L1254/1281), `lullaby ask` example (L735), `Lullaby` comment (L720), `Lullaby live view` banner (L1490).
   - `liveview.py` — docstring (L1), `lullabyRotate` localStorage (L278/280), page title `Lullaby live view` (L337/697), server header `LullabyLiveView/1` (L531).
   - `digest.py:13,28,30,35` — "Lullaby …" digest sentences.
   - `narrator.py` — persona "You are Lullaby…" (L66), User-Agent (L106), tempfile prefix `lullaby-voice-` (L132).
   - `pipeline.py:94,163` — notification source/title `"Lullaby"` (mirrored by 3 tests — change together in Phase 2).
   - `logging.py:52` — "Lullaby night log" header.
   - `sensors.py:179` — `name='lullaby-radar'`.
   - `video.py:210,334` — tempfile prefixes `lullaby-camera-*`.
   - **`.env.example` (lines 1–8)** — env-var prefix `LULLABY_* → BEDDINGTON_*`. **Folded into THIS commit** so the committed template and the `os.getenv` reads above never disagree (closes the split the risk register warns about). Keep the placeholder host `https://example.invalid/v1` (rename the key only).
5. **Wake word / persona (Decision 2):**
   - `ears.py` `WAKE_WORDS` — **reorder so `beddington` is index `[0]`** (it drives the printed default and the `.title()` live hint), **keep `paddington` + the fuzzy variants** as aliases. Update the L21 comment.
   - `assistant.py:3` docstring "Paddington voice assistant" → "Beddington voice assistant".
   - `cli.py` — help `Hi Paddington…` (L148) → `Hi Beddington…`; `--wake-word` help `(default: Paddington)` (L165) → `(default: Beddington)`; Whisper `initial_prompt` (L527–530) keep **both** names (e.g. "Hey Beddington. Hi Paddington."); live hint uses `wake_words[0]` (now Beddington).

**Commit:** `feat: rename Python package and runtime identifiers Lullaby→Beddington`

### Phase 2 — Tests (same change set as Phase 1)

- All 21 `tests/test_*.py`: `from lullaby.X` → `from beddington.X`.
- **Monkeypatch target strings** (silently no-op if missed — highest risk): `"lullaby.cli.…"`, `"lullaby.sensors.subprocess.run"`, `"lullaby.narrator.…"`, etc. → `"beddington.…"` (test_cli.py L147–150,265; test_narrator.py L81,111,122,136,287,288,308; test_sensors.py L264,272,286).
- **Name assertions:** `assert title == "Lullaby"` → `"Beddington"` in `test_narrator.py:67`, `test_pipeline.py:55`, `test_sensors.py:59` (lockstep with `pipeline.py` title literal).
- **Leave** the Paddington wake-word test inputs (`test_ears.py`, `test_assistant.py:21,274`) — they still pass via the kept alias; `test_extract_question_beddington_wake` already covers the new default.
- Gate: `python -m pytest` → all green (~198 tests).

**Commit:** folded into Phase 1's commit (atomic), or `test: update imports/monkeypatch targets to beddington`.

### Phase 3 — Config comments

- `config/default.toml` — L19 comment "Lullaby" → "Beddington"; L92 example `lullaby radar-vitals` → `beddington radar-vitals`. (`config/tier1-demo.toml` has **no** hits.)
- (`.env.example` is renamed in **Phase 1**, in the same commit as the source env-var reads, so the template and the `os.getenv` calls never disagree — do not also touch it here.)

**Commit:** `chore: rename config comments to Beddington`

### Phase 4 — Deploy / systemd units

- `git mv deploy/lullaby-liveview.service deploy/beddington-liveview.service`
- `git mv deploy/paddington.service deploy/beddington-assistant.service`
- Edit **both** unit bodies: `Description=…`, `ExecStart … -m lullaby …` → `-m beddington …`, `WorkingDirectory`/paths `/home/lab/Labie` & `~/Labie` → `…/Beddington`, token dir `~/.config/lullaby/` → `~/.config/beddington/`, the install/enable comment lines (`systemctl --user enable lullaby-liveview` / `… paddington`) → new unit names, log path `~/paddington.log` → `~/beddington-assistant.log`, the "(Lullaby)" parenthetical and "Paddington assistant" cross-reference → Beddington. Port `8088` unchanged.

**Commit:** `chore: rename systemd units and deploy paths to Beddington`

### Phase 5 — Docs (markdown)

Rename product-name prose **and** the now-renamed CLI examples (they're valid again because the command is `beddington` after Phase 1). Per file:

- `README.md` — H1, tagline, ~18 prose + `lullaby …` command examples, `~/.cache/lullaby/models/`, `src/lullaby/`, `cd ~/Code/Labie`.
- `memory.md` — **(a)** update the identity line L8 `**Repository:** ~/Code/Labie (GitHub: moelzek/labie)` → `~/Code/Beddington (GitHub: moelzek/Beddington)`; the Name/header/present-tense prose → Beddington. **(b)** Add a **new dated changelog line** (cardinal rule): `2026-06-28 — Renamed Lullaby/Paddington/Labie → Beddington across code, packaging, tests, deploy, docs, repo, and folder. Wake word default now "Beddington" (still wakes to "Paddington"); plush remains a Paddington bear.` **(c)** Apply the §8 history rule to dated entries.
- `CLAUDE.md` — title L1, "This repository is **Lullaby**" L3, "Working repository: `~/Code/Labie`" L5 → Beddington.
- `DEVLOG.md` — title L1; apply §8 to dated journal entries; `~/Labie` Pi path.
- `ROADMAP.md`, `context.md`, `skills.md`, `baby-monitor-build-plan.md`, `AGENTS.md` — clean product-name prose swaps.
- `hardware-guide.md`, `tier2-video-gate.md`, `camera-mount-plan.md` — product name + `lullaby …` CLI examples + `/tmp/lullaby-camera-*` temp paths.
- `baby-monitor-evaluation.md` — product name on L1/3/7 only; **keep** the song-noun `lullaby` on L28 & L57 (§2).
- `assets/soothe/README.md:1` — `# Lullaby soothe assets` → `# Beddington soothe assets`. (The one name-bearing file outside the root `*.md` set — Codex caught this; `sample_data/` has no hits.)

**Commit:** `docs: rename project to Beddington across all docs`

### Phase 6 — Archive/ contents sweep (Decision 3)

`Archive/` has **no** name-bearing file/dir names, but may contain old-name **text**. Codex: `git grep -niE 'lullaby|labie|paddington' -- Archive/`, then apply the §1 mapping with the §2 exceptions (keep "Paddington bear" plush, song-noun "lullaby", third-party links, dated history). Flag any naming-history sentences for Mo rather than rewriting.

**Commit:** `docs: scrub old names from Archive/ historical material`

### Phase 7 — External: GitHub repo + local folder (Mo-driven, Codex-assisted)

These **cannot be done by editing files** and need Mo's hands / approval:

1. **GitHub repo:** rename `moelzek/Labie → moelzek/Beddington` (Settings → Rename, or `gh repo rename Beddington -R moelzek/Labie`). GitHub auto-redirects the old slug, but still update the remote:
   `git remote set-url origin https://github.com/moelzek/Beddington.git` (affects this worktree and all siblings sharing the `.git`).
2. **Local folder:** `mv ~/Code/Labie ~/Code/Beddington`. Cascades:
   - the linked worktrees under `…/.claude/worktrees/` and their gitdir pointers (re-run from the new path; if any worktree's `.git` pointer breaks, `git worktree repair`);
   - hard-coded `~/Code/Labie` strings in docs are already handled in Phase 5;
   - the **Claude project memory dir** `~/.claude/projects/-Users-elzekmo-Code-Labie/` is **auto-derived from the path** — it re-derives to a new name on the next session. **Do NOT hand-rename it.** Old transcripts stay under the old derived dir (harmless). Note: `~/.claude/CLAUDE.md` has **zero** Labie/Lullaby refs — nothing to change there.

**Sequencing:** do the in-repo phases (1–6) and push first; do Phase 7 last so the rename lands on an already-consistent tree.

### Phase 8 — Deployed-device migration (only if a Pi is live)

Renaming env vars, state dirs, and unit names is **breaking** for an already-deployed device. On the Pi:
- `mv ~/.config/lullaby ~/.config/beddington` (preserves `liveview.token` → same phone URL), `mv ~/.local/share/lullaby ~/.local/share/beddington` (preserves `sensors.db` history), `mv ~/.cache/lullaby ~/.cache/beddington` (avoids re-downloading YAMNet).
- `mv ~/Labie ~/Beddington` (or `/home/lab/Labie`), update the private `.env` to `BEDDINGTON_*` keys.
- Re-install **then** re-enable units (the old plan enabled before copying — Codex P1 fix):
  `systemctl --user disable --now lullaby-liveview paddington` →
  `cp deploy/beddington-liveview.service deploy/beddington-assistant.service ~/.config/systemd/user/` →
  `rm -f ~/.config/systemd/user/lullaby-liveview.service ~/.config/systemd/user/paddington.service` →
  `systemctl --user daemon-reload` →
  `systemctl --user enable --now beddington-liveview beddington-assistant`.
- If you'd rather start clean, skip the `mv`s and accept a fresh token/history/model re-download.

### Phase 9 — Verify & acceptance gate

- `python -m pytest` → all green.
- `python -m build` (or `pip install -e .`) succeeds with `name = "beddington-monitor"`; `beddington --help` works; `python -m beddington --help` works.
- **Grep-clean:** `git grep -niE 'lullaby|labie' -- . ':!beddington-rename-plan.md' ':!agents/'` returns **only** the §2 allowlist + preserved history lines. `git grep -ni 'paddington'` returns only the kept wake-word alias + "Paddington bear" plush refs. (Leave `agents/openai.yaml` alone — it's tooling config, not project code.)
- Live-view smoke: `beddington live-view …` serves on `:8088`, tab title reads "Beddington live view", rotate button persists under `beddingtonRotate`.
- Voice smoke: "Hi Beddington …" wakes the assistant; "Paddington …" still wakes it (alias).

---

## 4. Rollback

Each phase is its own commit. To undo before Phase 7: `git revert` the phase commits (or reset the branch). Phase 7 is reversible too — GitHub keeps redirecting the old slug, and `mv ~/Code/Beddington ~/Code/Labie` + `git remote set-url` back restores the old layout. Take the rename on a branch; only fast-forward `main` once Phase 9 is green.

---

## 5. Risk register

| Item | Risk | Mitigation |
|---|---|---|
| Monkeypatch target strings in tests | High — silently no-op, suite "passes" testing nothing | Phase 2 explicit list; grep `"lullaby\.` in tests must be 0 after |
| `pyproject` 3-axis + dir rename | High — build/import breaks if out of sync | Do as one commit; run pytest + build |
| Env-var prefix `LULLABY_*` | High — breaks deployed `.env` | Rename source reads + `.env.example` together; Phase 8 device note |
| systemd unit renames | High — orphans enabled units on Pi | Phase 8 disable-old/enable-new sequence |
| State dirs `~/.config|.local|.cache/lullaby` | Med — orphans token/history/model | Phase 8 `mv`, or accept fresh |
| GitHub repo + folder rename | High — breaks clones/paths/worktrees | Phase 7 last; `git worktree repair`; GitHub auto-redirect |
| Rewriting dated changelog history | Med — falsifies timeline | §8 rule: preserve entries, add forward note |
| Blind find-replace | Med — hits song-noun / plush / 3rd-party | §2 allowlist |

---

## 6. What stays the same

Ports (8088, 11434), the `events.json`/`night-log.txt`/`morning-digest.txt` filenames, all generic auth/network strings, third-party model/dataset links, `pyproject` `pythonpath`, and the **physical Paddington-bear plush** identity.

---

## 7. Notes for Codex (executor)

- One logical change per commit, Conventional Commit prefixes (`feat:`/`test:`/`chore:`/`docs:`), per `CLAUDE.md`. Phases 1+2 may be one commit.
- Push per project rule: in a worktree use `git push origin HEAD:main`; if rejected, `git fetch` + rebase once, then retry; never force-push `main`.
- Never commit secrets or generated night logs.
- Phase 7 (GitHub + folder) and Phase 8 (device) **need Mo's hands** — prepare the exact commands but don't assume you can run the `mv`/`gh` steps unattended.
- End with the project sign-off line: `✅ Done & committed — <hash> "<message>"`.

---

## 8. History-rewrite rule (memory.md / DEVLOG.md dated entries)

Default (recommended, consistent with "no history rewrite"): **preserve the wording of past dated changelog/journal entries** as the factual record of when the project was called Lullaby/Paddington, and instead **add one forward-dated rename entry**. Update only present-tense identity/status fields (Name, Repository, current descriptions) and product-name prose outside dated entries.

If Mo prefers a total scrub, the alternative is to also rewrite the product-name token inside past entries — but **keep dates, keep "wake word changed to Paddington" naming-history facts, and keep "Paddington bear" plush references**. Codex should flag the naming-history entries for Mo rather than deciding alone.

> Open question for Mo to confirm at sign-off: total-scrub vs preserve-history-with-forward-note. This plan assumes **preserve + forward note**.

---

## 10. Codex verification record (2026-06-28)

Codex (`gpt`, read-only) reviewed this plan against the live repo. **Verdict: APPROVE-WITH-FIXES.** All 5 fixes are now folded in above:

1. **[P1]** Phase 8 enabled the new systemd units before copying them into `~/.config/systemd/user/`. → Fixed: added the `cp` (install) step before `daemon-reload`/`enable`.
2. **[P2]** Module count was "27"; the package has **26** `.py` files. → Fixed in Phase 1.
3. **[P2]** Missed `assets/soothe/README.md:1` (`# Lullaby soothe assets`). → Added to Phase 5.
4. **[P2]** `.env.example` rename was split from the source env-var reads across phases. → Folded into the Phase 1 atomic commit.
5. **[P2]** Grep-clean should exclude the tooling `agents/` path. → Added `':!agents/'` and a leave-`agents/openai.yaml`-alone note.

**Codex independently confirmed:** pyproject line refs (L6/22/25/30); **no absolute intra-package imports** (`git grep -nE '(import|from)\s+lullaby' -- src/` is clean — all relative); config.py / detector.py / cli.py / liveview.py and the test monkeypatch target lines match the real files; the 21 `tests/test_*.py` and the monkeypatch-silent-no-op risk; the Phase 1+2 atomicity; the §2 DO-NOT-CHANGE exceptions (song-noun `lullaby`, "Paddington bear" plush, third-party links, `pythonpath`); and the state-dir migration targets.

Plan is ready for Mo's sign-off, then Codex to execute phase by phase.
