#!/usr/bin/env bash
# One trading/website-update cycle. Called repeatedly by the looping blocks
# in Signal.yml. Designed NOT to abort the loop on a single failure — every
# step swallows its own error and logs it, so the next cycle still runs.
set -uo pipefail

echo "============================================================"
echo "=== Cycle start: $(date -u) ==="
echo "============================================================"

# 1) Always refresh signals / website data ---------------------------------
python Signal.py || echo "WARN: Signal.py failed this cycle, continuing"

# 2) Trading logic ONLY during market hours (Mon-Fri 5:30am-2pm PT) ---------
#    10# forces base-10 so values like "08"/"09" don't break arithmetic.
ch=$(TZ=America/Los_Angeles date +%H)
cm=$(TZ=America/Los_Angeles date +%M)
dow=$(TZ=America/Los_Angeles date +%u)          # 1=Mon ... 7=Sun
mins=$((10#$ch * 60 + 10#$cm))                  # minutes since midnight PT

if [ "$dow" -ge 1 ] && [ "$dow" -le 5 ] && [ "$mins" -ge 330 ] && [ "$mins" -le 840 ]; then
  echo "Trading hours: running NishantMean.py"
  python NishantMean.py || echo "WARN: NishantMean.py failed, continuing"
else
  echo "Outside trading hours: skipping NishantMean.py"
fi

# 3) Telegram notifications --------------------------------------------------
python BullishSpreadsTelegramNotifs.py || echo "WARN: Telegram step failed, continuing"

# 4) Commit + push generated data, with retry + merge-ours on collision ------
git add data/*.json 2>/dev/null || true

if git diff --cached --quiet; then
  echo "No changes to commit this cycle."
else
  git commit -m "Update signals and logs: $(date -u)"
  pushed=0
  for attempt in 1 2 3 4 5; do
    if git push origin main; then
      echo "Push succeeded on attempt $attempt"
      pushed=1
      break
    fi
    echo "Push rejected (attempt $attempt) — syncing with remote..."
    git fetch origin main
    # Always keep OUR freshly generated data on conflict; never stop on it.
    git merge -X ours origin/main --no-edit || true
    sleep $((RANDOM % 6 + 2))
  done
  [ "$pushed" -eq 1 ] || echo "WARN: could not push this cycle; will retry next cycle"
fi

echo "=== Cycle end: $(date -u) ==="
