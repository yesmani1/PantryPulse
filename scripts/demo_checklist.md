# PantryPulse demo verification checklist

Run this checklist from the activated `.venv` before recording a demo or
proposing a merge to `main`. Keep the bot process running in one terminal and
use a fresh Telegram chat in another.

## Automated preflight

```powershell
python -m pytest -q
python scripts/verify_demo.py
python scripts/run_evaluations.py
python scripts/verify_inventory_roundtrip.py --apply
```

The inventory round-trip is disposable: it creates, reads, updates, and removes
one uniquely named UAT record. Do not run it unless the ignored `.env` contains
the intended UAT credentials.

## Telegram walkthrough

1. Send `/start`, then `/demo`; verify the keyboard and 30-item sample pantry.
2. Send `/today` and `/expiring`; confirm Use By guidance is firm, a passed Best
   Before date is reassuring, and Sell By is not presented as a consumer alert.
3. Exercise `/recipe` then **Cook This** and **Another Recipe**; exercise
   `/shopping` then **Approve**, **Edit**, and **Ignore**.
4. Exercise `/decision`: Cook, Shop, Ignore, and—if shown—Donate Eligible Food
   followed by mock-recipient Accept and Reject. Confirm a stale button reports
   an expiry message rather than raising an error.
5. Send a receipt and a package photo. Confirm preview, cancel, confirm, and
   **Set date**. Verify an accepted item appears in `/pantry` with its source
   label and a correction is visible after refresh.
6. Re-send the same image; verify logs show a cache hit/no additional provider
   invocation. Send more photos than the documented per-chat limit and confirm
   the safe rate-limit message.
7. Use `/remove` for an intentionally wrong item, and use each expiry feedback
   button. Confirm `/today` shows the resulting rescue counter change.

## Evidence to retain

Record the command output of the automated preflight and screenshots of the
date-safety contrast, ingestion confirmation/correction, one combined decision,
and the public endpoint once deployed. Never include tokens, AWS identifiers,
or real household data in committed evidence.
