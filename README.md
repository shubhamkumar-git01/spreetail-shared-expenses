# Spreetail Shared Expenses Hub

A premium, interactive web application to track shared expenses, settle debts, resolve CSV data anomalies, and audit individual balances over time. Built as a Software Developer take-home assignment.

---

## 1. Features
1. **Interactive Import Ingestion**: Ingests `expenses_export.csv` programmatically, detecting and reporting 13+ distinct data anomalies (duplicates, currency issues, missing payers, guest splits, membership date changes).
2. **Anomalies Resolution Center**: Provides an approval flow for Meera's request, letting users approve duplicate deletions and choose which row wins in conflicting logs.
3. **Dynamic Membership periods**: Excludes Sam from March expenses and redistributes April splits to exclude Meera automatically after her move-out.
4. **Multi-currency Support**: Automatically converts USD transactions to base INR (1 USD = 83 INR).
5. **Aisha's Simplified Debts View**: One-click summary of who owes whom, how much, and simple settle actions.
6. **Rohan's Detailed Audit Ledger**: Let's Rohan drill down into his balance to see every transaction and split contributing to his final net total.
7. **Premium Glassmorphism Dashboard**: Fully responsive dark mode dashboard with Outfit/Inter typography and micro-animations.

---

## 2. Tech Stack
* **Backend**: Python 3.11 (Flask)
* **Database**: SQLite (relational)
* **Frontend**: Vanilla HTML5, CSS3, ES6 JavaScript

---

## 3. Project Structure
```
/
├── app.py                 # Core Flask backend server & balance engine
├── verify.py              # Automated test suite
├── expenses_export.csv    # Source data file
├── import_report.json     # Generated anomaly report
├── SCOPE.md               # Database schema & anomaly log
├── DECISIONS.md           # Product & engineering decision log
├── AI_USAGE.md            # AI collaboration log
├── templates/
│   └── index.html         # Frontend Single Page Application
```

---

## 4. Setup & Running Locally

### Prerequisites
- Python 3.11.x
- `pip` package manager

### Steps
1. **Navigate to the project directory**:
   ```bash
   cd C:\Users\Shubham\.gemini\antigravity\scratch
   ```

2. **Install Flask**:
   ```bash
   pip install flask
   ```

3. **Run the application**:
   ```bash
   python app.py
   ```
   *The server will start at `http://127.0.0.1:5000`.*

4. **Verify the installation**:
   - Open `http://127.0.0.1:5000` in your browser.
   - Go to the **Import CSV** tab and drag-and-drop or select `expenses_export.csv` from your system (or workspace).
   - Once uploaded, click on different flatmate cards in the sidebar to simulate user sessions and view balances, settle debts, and inspect Rohan's ledger.

---

## 5. Running Tests

We have written an automated test suite (`verify.py`) to validate all CSV parser anomalies and math engine formulas:
```bash
python verify.py
```
This runs assertions for duplicates, conflicts, guest absorption, membership-time exclusions, and outputs the final net balances and debt simplification ledger.

---

## 6. AI Collaboration
This project was developed in partnership with **Antigravity** (AI Coding Assistant by Google DeepMind) using Gemini 3.5 Flash. Details of prompt traces and error corrections can be found in [AI_USAGE.md](AI_USAGE.md).
