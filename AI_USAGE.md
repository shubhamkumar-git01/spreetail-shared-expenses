# AI_USAGE.md - AI Collaboration Log

This document details the AI tools used, key prompts, and concrete instances where the AI generated incorrect code or architecture, how those errors were caught, and how they were corrected.

---

## 1. AI Tools & Key Prompts

* **AI Tool**: Antigravity, an agentic AI coding assistant designed by the Google DeepMind team.
* **Model**: Gemini 3.5 Flash (Medium).
* **Key Prompts & Interaction Style**:
  * *Prompt 1 (Ingestion Strategy)*: "Analyze `expenses_export.csv` and identify all deliberate anomalies. Formulate a policy for resolving them programmatically without human intervention."
  * *Prompt 2 (Database Design)*: "Design a relational SQLite database schema that tracks memberships over time, duplicate records, conflicts, and transaction splits."
  * *Prompt 3 (Balance Simplification)*: "Write a debt simplification engine in Python that matches debtors with creditors greedily to minimize transactions, and compile Rohan's transaction audit ledger."

---

## 2. Concrete Cases of AI Errors and Resolutions

### Case 1: Substring duplicate check failed on minor text differences
* **What the AI did wrong**: The AI initially wrote a substring-matching condition for duplicate descriptions:
  ```python
  if normalized_desc == seen_norm_desc or (seen_norm_desc in normalized_desc) or (normalized_desc in seen_norm_desc):
  ```
  This failed to match `"Dinner at Marina Bites"` (normalized: `dinneratmarinabites`) with `"dinner - marina bites"` (normalized: `dinnermarinabites`) because of the stop word `"at"`.
* **How it was caught**: We wrote an automated verification script (`verify.py`) which asserted that row 6 (Marina Bites) was marked as `duplicate_hidden`. The assertion failed.
* **What we changed**: We refactored description matching in `app.py` to use a token-set overlap heuristic (`is_similar_desc`). We split descriptions into words, removed common English stop words, and calculated the intersection ratio. If $\ge 50\%$ of the core words overlap, it is treated as a match. This resolved both the Marina Bites duplicates and Thalassa dinner conflicts.

---

### Case 2: Missing guest split calculation (Payer absorption)
* **What the AI did wrong**: The AI calculated split shares for all users, including the guest `Dev's friend Kabir`. At the end of split calculations, it attempted to find Kabir's user ID in the database to transfer his share to Dev. However, since Kabir was not a registered user, he was never added to the database `users` table, and querying his ID returned `None`. This caused Kabir's split to be silently dropped, leaving Dev with only a single share (2,490 INR instead of 4,980 INR).
* **How it was caught**: The test suite `verify.py` asserted that Dev's share of the Goa parasailing trip was 4,980 INR. The assertion failed, outputting: `"Dev should absorb Kabir's share! Got 2490.0"`.
* **What we changed**: We moved the guest mapping logic to the *initial participant parsing phase* in `app.py`. We mapped `Dev's friend Kabir` to `'Dev'` directly. We then refactored the split engine to *accumulate* split values (using `+=` instead of `=`) so that if a user appears multiple times (representing absorbing a guest's share), their shares are summed correctly.

---

### Case 3: Windows Console encoding error on rupee symbol
* **What the AI did wrong**: The AI printed the Unicode rupee character `₹` directly in the test suite print statements. 
* **How it was caught**: In the sandboxed Windows PowerShell environment, the script crashed with a `UnicodeEncodeError`:
  ```
  UnicodeEncodeError: 'charmap' codec can't encode character '\u20b9' in position 23: character maps to <undefined>
  ```
* **What we changed**: We edited the console output logs in `verify.py` to use `Rs.` instead of the raw Unicode `₹` symbol. This ensured cross-platform printing compatibility across all Windows and Unix terminals regardless of active CP1252/UTF-8 locale pages.
