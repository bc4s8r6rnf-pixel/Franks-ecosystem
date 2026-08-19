# Frozen releases

Files in this folder are **never edited**. They are point-in-time copies kept so
any version can be recovered exactly as it was, however far the working copy
drifts. Ongoing work happens in `Pine/RXWLES_DirectionCall.pine`; when a
version is worth keeping, it gets copied here under a new number and tagged.

To restore a frozen version, copy it back over the working file. Never edit a
file in this folder, and never renumber one.

### A note on tags

Annotated tags were the intended second anchor, but this sandbox's git proxy
accepts branch refs only — every tag push returns "the remote end hung up
unexpectedly" while the branch push succeeds. The tag therefore exists in local
history and not on GitHub.

That costs nothing important. The frozen file is committed and pushed, so it is
recoverable from the remote by path or by commit SHA. If you want the tag on
GitHub as well, create it once from the web UI: **Releases → Draft a new
release → Choose a tag → create `direction-call-v1.0` → target the freeze
commit above**. A future session on a normal remote can push tags directly.

---

## v1.0 — RXWLES Direction Call

| | |
|---|---|
| File | `RXWLES_DirectionCall_v1.0.pine` |
| Freeze commit | `9b9871e` — `git show 9b9871e:Pine/releases/RXWLES_DirectionCall_v1.0.pine` |
| Git tag | `direction-call-v1.0` — **exists locally only, see note below** |
| Lines | 356 |
| SHA-256 | `8589ccd405da5f8f74b06b02ba5e433f54ce82e4c1a3d803cfe9bd541cb9be14` |
| Frozen | 2026-08-19 |
| Status | **Not yet compiled in TradingView.** First version to be coded, not first version to be verified. |

### The method it implements

    R      = height of the 21:00 New York candle
    Read   = 04:00 New York, every day, no gap filter
    Call   = whichever inner zone edge (2.0 R) is closer
    Trade  = enter at the read, stop and target both 1.5 R, flat at midnight

### What it measured on 111 XAUUSD sessions

| setup | record | accuracy | split halves |
|---|---|---|---|
| 04:00, 1.5 R | 59W / 31L / 21 flat | 65.6% | 67.4% / 63.6% |
| 04:00, 2.0 R | 56W / 22L / 33 flat | 71.8% | 75.6% / 67.6% |
| 09:00, 1.0 R | 63W / 38L / 10 flat | 62.4% | 64.7% / 60.0% |

40 of 55 hour-by-target cells tested positive, median 56.8%.

### Tested and rejected before these defaults were set

- **VWAP/TWAP**, alone and in every combination — proximity already agrees with
  move-since-midnight 83.8% of the time, so it adds noise, not information.
- **A minimum-gap filter** — cut winning days from 63 to 37 and bought no accuracy.
- **Pullback entries** — 0.5 R lifts accuracy to 63.8% but misses 64 of 111 days
  and halves total R.
- **Holding past midnight** — missed days score −0.27 R held one more day, −0.43 R
  held two.

### Known limits

- Gold only. NAS100 reaches 59% at its best cell but only 27 of 55 cells are
  positive and the median is exactly 50.0%.
- 111 sessions is a small sample; roughly five months.
- Costs are not modelled in any of the figures above.
- Never run against live data or a compiler.

### Reproducing the numbers

    python3 analysis/vwap_direction.py "XAUUSD=analysis/data_XAUUSD_H1.csv"
    python3 analysis/direction.py      "XAUUSD=analysis/data_XAUUSD_H1.csv"
    python3 analysis/stops_targets.py  "XAUUSD=analysis/data_XAUUSD_H1.csv"

Raw exports are in `analysis/`, saved reports in `analysis/results/`.
