# Fix: Bash 3.2 Compatibility for start.sh, setup.sh, stop.sh

macOS ships with bash 3.2. Our scripts use `set -euo pipefail` (strict mode) and have Unicode characters that bash 3.2 misparses as part of variable names.

## Known issue
Line 177 had `$label…` where the UTF-8 ellipsis (U+2026) was parsed as part of the variable name. We fixed that one instance but the SAME problem likely exists elsewhere.

## Your task

1. **Audit ALL three scripts** (`start.sh`, `setup.sh`, `stop.sh`) for bash 3.2 incompatibilities:
   - ANY `$variable` immediately followed by a UTF-8/Unicode character (ellipsis `…`, em-dash, etc.) — bash 3.2 parses the multibyte chars as part of the var name. Fix by using `${variable}` braces.
   - ANY `${var,,}` or `${var^^}` (case modification) — bash 4+ only. Use `tr` instead.
   - ANY associative arrays (`declare -A`) — bash 4+ only.
   - ANY `|&` pipe syntax — bash 4+ only.
   - ANY `readarray` or `mapfile` — bash 4+ only.
   - ANY `${!prefix@}` indirect expansion edge cases.

2. **Replace ALL Unicode characters in echo strings** that appear immediately after `$var` references with ASCII equivalents or ensure variables are brace-wrapped `${var}`.

3. **Specifically audit for these Unicode chars touching variables:**
   - `…` (U+2026 ellipsis) → replace with `...` or brace-wrap the var
   - `–` (U+2013 en-dash) → replace with `-`
   - `—` (U+2014 em-dash) → replace with `--`
   - `·` (U+00B7 middle dot) → replace with `*` or `-`
   - Any other non-ASCII chars adjacent to `$var` references

4. **Test each script**: `bash -n script.sh` (syntax check) AND try to run with `/bin/bash` (macOS default 3.2)

5. **When done:**
   - `bash -n start.sh && bash -n setup.sh && bash -n stop.sh && echo "All validate"`
   - `git add start.sh setup.sh stop.sh && git commit -m "fix: Full bash 3.2 compatibility audit — brace-wrap all vars near Unicode, replace bash 4+ syntax" && git push`
   - `openclaw system event --text "Done: Bash 3.2 compat fix for all scripts" --mode now`
