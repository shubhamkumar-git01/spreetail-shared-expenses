# DECISIONS.md - Decision Log

This document details the key product, architectural, and design decisions made while building the Shared Expenses App, listing the options considered and the rationale behind the chosen paths.

---

## 1. Technology Stack: Python Flask, SQLite, and Vanilla HTML/CSS/JS
* **Context**: We needed to build a relational-database-backed web app that is easy to run, visually appealing, and highly robust.
* **Options considered**:
  1. *Node.js + Express + React + PostgreSQL*: Rejected because Node.js was not installed on the host machine.
  2. *Next.js (App Router) + Drizzle + Vercel + Neon*: Rejected due to lacking Node.js environment.
  3. *Python (Flask) + SQLite + Vanilla CSS/JS*: **Chosen**. Python 3.11.9 is pre-installed on the host system. SQLite is part of Python's standard library (requires zero configuration or setup) and is a robust relational database. Flask easily serves static files and provides API routes.
* **Decision**: We built a Flask server to host the APIs and serve a modern, responsive Single Page Application (SPA) using HTML, Vanilla CSS, and ES6 Javascript.

---

## 2. Ingestion Pipeline: Non-Destructive Ingest with "Resolution Status"
* **Context**: The CSV contained malformed, conflicting, and duplicate entries. Meera explicitly requested that nothing be deleted or changed without her approval.
* **Options considered**:
  1. *Discard duplicates and fix errors during CSV parse*: Rejected because it violates Meera's requirement for manual approval and does not preserve the source data.
  2. *Reject/crash on malformed rows*: Rejected because a crashed import is a failing answer according to the assignment instructions.
  3. *Import all data but flag anomalies as 'Pending Resolution'*: **Chosen**. All rows are loaded into the database. Duplicates and conflicts are stored with statuses like `duplicate_hidden` or `pending_resolution`. The UI provides an **Anomaly Resolution Center** where users can approve recommendations.
* **Decision**: Non-destructive ingestion allows the application to ingest the CSV completely without crashing, surfaces anomalies as a report, and enables a clean manual approval flow.

---

## 3. Date Parsing & Ambiguity Resolution (Row 34)
* **Context**: Row 34 is dated `04-05-2026` with note "is this April 5 or May 4? format is a mess".
* **Options considered**:
  1. *Strict parsing*: Parse as May 4 because the format of other dates is `DD-MM-YYYY`.
  2. *Ask user on import*: Slows down the automated ingestion.
  3. *Contextual heuristic parsing*: **Chosen**. If the date was May 4, Sam (who joined mid-April) would be a member of the flat. However, the split list in Row 34 only contains `Aisha;Rohan;Priya` (excluding Sam and Meera). On April 5, Meera had left (end of March) and Sam had not yet moved in (mid-April), making this exact split list active. 
* **Decision**: We resolve the date contextually as April 5, 2026 (`2026-04-05`), avoiding charging Sam for a pre-move-in service and matching the active group structure.

---

## 4. Guest splits: Host Absorption (Row 23)
* **Context**: Row 23 (Parasailing) includes `Dev's friend Kabir` who is not a flatmate.
* **Options considered**:
  1. *Create Kabir as a permanent user*: Unnecessary and cluttering, since Kabir was just a weekend guest.
  2. *Let Dev absorb Kabir's share*: **Chosen**. The pipeline maps Kabir directly to Dev during participant resolution. Dev is charged for 2 shares (his own + Kabir's) while other members split the remaining shares equally.
* **Decision**: Dev absorbs his guest's share, keeping flatmate balances clean and fair.

---

## 5. Rohan's Request: Detailed Ledger Breakdowns
* **Context**: Rohan: "No magic numbers. If the app says I owe ₹2,300, I want to see exactly which expenses make that up."
* **Options considered**:
  1. *Static text summary*: Text descriptions can get long and messy.
  2. *Dynamic Interactive Ledger*: **Chosen**. Clicking on Rohan's balance pulls up a detailed audit trail (ledger). The ledger lists each transaction, the total amount, Rohan's share, who paid, and the net effect (positive credit if Rohan paid, negative debit if someone else paid and Rohan was in the split).
* **Decision**: An interactive transaction ledger that sums up exactly to Rohan's net balance, allowing him to audit every single rupee.

---

## 6. Currency Management: Base Currency Consolidation (INR)
* **Context**: Priya: "Half the trip was in dollars. The sheet pretends a dollar is a rupee. That can't be right."
* **Options considered**:
  1. *Dual currency balances (USD and INR)*: Confusing for settlements, as flatmates would need to settle in two currencies.
  2. *Base currency conversion (convert USD to INR)*: **Chosen**. We use a standard exchange rate (1 USD = 83 INR). All USD transactions are converted to INR splits during ingestion, allowing a single unified settlement list in INR.
* **Decision**: Convert all foreign currency amounts to a base currency (INR) at the time of transaction, which simplifies calculations and makes "Aisha's settlement list" clean and actionable.
