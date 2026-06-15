# SCOPE.md - Anomaly Log & Database Schema

This document outlines all data anomalies identified in the `expenses_export.csv` file, our resolution policies for each, and the relational database schema implemented for the Spreetail Shared Expenses App.

---

## 1. Relational Database Schema (SQLite)

We use SQLite as our relational database engine. Below is the physical schema implementation:

```sql
-- Represents users/flatmates
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

-- Represents expense sharing groups
CREATE TABLE groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

-- Tracks membership periods over time (Sam joins, Meera leaves, etc.)
CREATE TABLE group_memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    joined_date TEXT NOT NULL, -- Format: YYYY-MM-DD
    left_date TEXT,            -- Format: YYYY-MM-DD (NULL if still active)
    FOREIGN KEY (group_id) REFERENCES groups (id),
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- Represents logged expenses and payments
CREATE TABLE expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    paid_by_id INTEGER,        -- ID of the user who paid (NULL if missing)
    amount REAL NOT NULL,
    currency TEXT NOT NULL,    -- 'INR' or 'USD'
    date TEXT NOT NULL,        -- Format: YYYY-MM-DD
    split_type TEXT NOT NULL,  -- 'equal', 'unequal', 'percentage', 'share', 'settlement'
    notes TEXT,
    is_settlement INTEGER DEFAULT 0, -- 1 if this is a payment to settle debts, 0 otherwise
    status TEXT DEFAULT 'active',    -- 'active', 'pending_resolution', 'duplicate_hidden', 'deleted'
    source_row INTEGER,        -- Traces back to the CSV row index
    FOREIGN KEY (group_id) REFERENCES groups (id),
    FOREIGN KEY (paid_by_id) REFERENCES users (id)
);

-- Tracks individual splits for each expense
CREATE TABLE expense_splits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    split_value REAL NOT NULL,           -- Ratio value (percentage, share, etc.)
    calculated_amount_inr REAL NOT NULL, -- Calculated split share in base currency (INR)
    FOREIGN KEY (expense_id) REFERENCES expenses (id),
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- Stores detected anomalies during CSV import for auditing and resolution
CREATE TABLE anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    row_index INTEGER NOT NULL,
    date TEXT,
    description TEXT,
    paid_by TEXT,
    amount TEXT,
    currency TEXT,
    split_type TEXT,
    split_with TEXT,
    split_details TEXT,
    anomaly_type TEXT NOT NULL,
    description_msg TEXT NOT NULL,
    resolution_action TEXT NOT NULL,
    status TEXT DEFAULT 'pending' -- 'pending', 'resolved'
);
```

---

## 2. Ingested Anomaly Log (expenses_export.csv)

We discovered and handled **13 distinct types of anomalies** across **19 occurrences** in the CSV file. 

| Row | Date | Description | Payer | Amount | Anomaly Type | Resolution & Handling Policy |
|---|---|---|---|---|---|---|
| **5 & 6** | 08-02-2026 | Dinner at Marina Bites / dinner - marina bites | Dev | 3200 INR | **Duplicate Entries** | Row 6 is flagged as a duplicate of Row 5 (same date, amount, currency, and overlapping descriptions). Imported both but marked Row 6 as `duplicate_hidden`. Meera can approve its deletion in the UI. |
| **24 & 25**| 11-03-2026 | Dinner at Thalassa / Thalassa dinner | Aisha / Rohan | 2400 / 2450 INR | **Conflicting Ingestion** | Same event double-logged by different people with different amounts. Both imported but marked as `pending_resolution`. The UI prompts Meera to approve the winning record. |
| **13** | 22-02-2026 | House cleaning supplies | *Blank* | 780 INR | **Missing Payer** | Payer left empty in CSV. Imported with `paid_by_id = NULL`. Marked as `pending` in the Resolution Center for Meera to assign. |
| **15** | 28-02-2026 | Pizza Friday | Aisha | 1440 INR | **Invalid Percentages** | Percentages in details sum to 110%. Automatically normalized details proportionally down to sum to 100%. |
| **32** | 25-03-2026 | Weekend brunch | Meera | 2200 INR | **Invalid Percentages** | Percentages in details sum to 110%. Automatically normalized details proportionally down to sum to 100%. |
| **28** | 15-03-2026 | Groceries DMart | Priya | 2105 *Blank* | **Missing Currency** | Defaulted to base currency `INR` and flagged in report. |
| **34** | 04-05-2026 | Deep cleaning service | Rohan | 2500 INR | **Ambiguous Date** | `04-05-2026` could mean April 5 or May 4. Since Meera (left end of March) and Sam (joined mid-April) are both excluded from the split list, it matches the active group of April 5. Resolved as `2026-04-05`. |
| **27** | Mar-14 | Airport cab | Rohan | 1100 INR | **Inconsistent Date Format** | Normalized `Mar-14` to standard date `2026-03-14`. |
| **9, 11, 27**| Various | Movie snacks / DMart / Cab | Priya/Rohan | Various | **Name Discrepancies** | Cleaned and standardized names: `priya` -> `Priya`, `Priya S` -> `Priya`, `rohan ` (trailing space) -> `Rohan`. |
| **23** | 11-03-2026 | Parasailing | Dev | 150 USD | **External Guest** | `Dev's friend Kabir` is not a flatmate. Dev absorbs Kabir's share. The parser mapped Kabir to Dev, resulting in Dev taking 2 shares of the split. |
| **26** | 12-03-2026 | Parasailing refund | Dev | -30 USD | **Negative Amount** | Treated as a refund, creating negative splits that reduce everyone's net balance. |
| **31** | 22-03-2026 | Dinner order Swiggy | Priya | 0 INR | **Zero-value Expense** | Imported but ignored in balance calculations. |
| **14** | 25-02-2026 | Rohan paid Aisha back | Rohan | 5000 INR | **Settlement Logged as Expense** | Split type is blank. Converted to a direct `settlement` record, reducing Rohan's debt to Aisha instead of treating it as a shared expense. |
| **7** | 10-02-2026 | Electricity Feb | Aisha | "1,200" INR | **Formatting Discrepancy** | Strip quotes and commas, convert to numeric float `1200.0`. |
| **36** | 02-04-2026 | Groceries BigBasket | Priya | 2640 INR | **Inactive Member in Split** | Meera is included in the split but she moved out on March 31. Meera was automatically removed from the split, and her share redistributed equally to Aisha, Rohan, and Priya. |
| **Sam's exclusion** | March | Electricity Mar, Rent Mar | Various | Various | **Retroactive Billing** | Sam joined April 8. The membership engine excludes Sam from March expenses (e.g. March electricity on March 18) preventing retroactive charges. |
