# KAKIS reference: data-analysis runs

Load this when a KAKIS goal is a data analysis — econometrics, policy
analysis, anything producing numeric tables and reports from source
data. Keep it in mind through execution, not just at plan time.

Part A is generic to the class of data-analysis run. Part B comes from
one specific production design (a causal EV-rebate econometric study):
apply it when the run has that structure (scope-split outputs, negative
controls, dual estimation/interpretation windows).

## Part A — Pre-loop: verify the data before Dory starts

- Probe the source data read-only BEFORE the loop: row counts, actual
  date ranges, when each series/label/value first appears, what each
  category actually means. Inject the verified facts into the
  subplanner's Reference section, with instructions to confirm rather
  than assume.
- Require the plan to verify that the variable of interest VARIES
  within its estimation window: a treatment variable that is flat over
  a sub-window makes estimation on that sub-window rank-deficient.
  Estimation window ≠ interpretation window — estimate where the
  variable varies; interpret on the relevant sub-period.
- Why: unverified data assumptions burn iterations re-deriving window
  ends, label onsets, and category meanings, and an unexamined
  identification scope silently produces undefined coefficients that
  fail at execution time.

## Part B — Verification discipline (with study-design lessons)

- **Scope splits across files** — downstream modules may write
  full-window results to one file (e.g. `price_equation.csv`) and
  era/scope results to a scope-suffixed sibling
  (e.g. `price_equation_2022plus_robustness.csv`). Always check for
  files with scope indicators in the name when verifying
  scope-specific results.
- **Dual scope naming convention** — when the pipeline supports
  dual-scope (full window + interpretation/era window), expect:
  (1) main tables contain full-window specs; (2) separate
  `*_2022plus*` / `*_era_*` files contain the secondary scope;
  (3) the report must cite numbers from both scopes. Do not assume
  one file has everything.
- **Negative-control verdicts must be cross-checked** — a subagent may
  report a NC "PASS"/"FAIL" from its own logic. Read the
  negative-control data, compute the sign/direction yourself, and
  compare against the verdict. A sign flip in the control category
  invalidates the causal claim regardless of what the subagent says.
- **Figure tracing: verify every cited number** — a subagent claims to
  copy numbers "from tables at runtime." Pick 3-5 key coefficients
  (price-equation dose, mediation indirect effect, negative-control
  %), read the raw table value, and confirm the report matches
  (allowing for rounding). If one number is wrong, the rest are
  suspect.
- **String matching on numbers must handle Unicode** — reports and
  tables may use the Unicode minus (U+2212, −) instead of the ASCII
  hyphen-minus (-); grepping or Python-`in`ing for "-0.016" silently
  misses "−0.016", which reads as a missing/fabricated figure when the
  value is present. Normalize before comparing:
  `text.replace('\u2212', '-')` (or `tr -d '\u2212'`) and check the
  ASCII form once.
