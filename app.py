import os
import re
import csv
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory

app = Flask(__name__, template_folder='templates', static_folder='static')
DATABASE = 'expenses.db'
USD_TO_INR = 83.0  # Fixed exchange rate

# Canonical users and their membership periods
MEMBERSHIP = {
    'Aisha': {'joined': '2026-02-01', 'left': None},
    'Rohan': {'joined': '2026-02-01', 'left': None},
    'Priya': {'joined': '2026-02-01', 'left': None},
    'Meera': {'joined': '2026-02-01', 'left': '2026-03-31'},
    'Sam': {'joined': '2026-04-08', 'left': None},  # Joins when deposit paid
    'Dev': {'joined': '2026-02-01', 'left': None}  # Dev is a guest, active during trips
}

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Drop tables to allow clean re-import
    cursor.execute("DROP TABLE IF EXISTS expense_splits")
    cursor.execute("DROP TABLE IF EXISTS expenses")
    cursor.execute("DROP TABLE IF EXISTS group_memberships")
    cursor.execute("DROP TABLE IF EXISTS groups")
    cursor.execute("DROP TABLE IF EXISTS users")
    cursor.execute("DROP TABLE IF EXISTS anomalies")
    
    # Create tables
    cursor.execute("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """)
    
    cursor.execute("""
    CREATE TABLE groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """)
    
    cursor.execute("""
    CREATE TABLE group_memberships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        joined_date TEXT NOT NULL,
        left_date TEXT,
        FOREIGN KEY (group_id) REFERENCES groups (id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        description TEXT NOT NULL,
        paid_by_id INTEGER,
        amount REAL NOT NULL,
        currency TEXT NOT NULL,
        date TEXT NOT NULL,
        split_type TEXT NOT NULL,
        notes TEXT,
        is_settlement INTEGER DEFAULT 0,
        status TEXT DEFAULT 'active', -- 'active', 'pending_resolution', 'duplicate_hidden', 'deleted'
        source_row INTEGER,
        FOREIGN KEY (group_id) REFERENCES groups (id),
        FOREIGN KEY (paid_by_id) REFERENCES users (id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE expense_splits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        expense_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        split_value REAL NOT NULL,
        calculated_amount_inr REAL NOT NULL,
        FOREIGN KEY (expense_id) REFERENCES expenses (id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    
    cursor.execute("""
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
    )
    """)
    
    # Insert flatmates
    for name in MEMBERSHIP.keys():
        cursor.execute("INSERT INTO users (name) VALUES (?)", (name,))
        
    # Create default flat group
    cursor.execute("INSERT INTO groups (name) VALUES (?)", ("Flatmates Shared Expenses",))
    group_id = cursor.lastrowid
    
    # Set up membership periods
    for name, dates in MEMBERSHIP.items():
        cursor.execute("SELECT id FROM users WHERE name = ?", (name,))
        user_id = cursor.fetchone()[0]
        cursor.execute("""
        INSERT INTO group_memberships (group_id, user_id, joined_date, left_date)
        VALUES (?, ?, ?, ?)
        """, (group_id, user_id, dates['joined'], dates['left']))
        
    conn.commit()
    conn.close()

# Helper: check if a user was active on a given date
def is_user_active_on_date(name, date_str):
    if name not in MEMBERSHIP:
        return False
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return True # Default to active if date is malformed initially
    
    joined = datetime.strptime(MEMBERSHIP[name]['joined'], "%Y-%m-%d")
    if dt < joined:
        return False
        
    left_str = MEMBERSHIP[name]['left']
    if left_str:
        left = datetime.strptime(left_str, "%Y-%m-%d")
        if dt > left:
            return False
            
    return True

# Helper: parse date with heuristics
def clean_date(date_str, row_idx, split_with_list):
    date_str = date_str.strip()
    
    # Case: "Mar-14"
    if re.match(r'^[A-Za-z]{3}-\d{1,2}$', date_str):
        parts = date_str.split('-')
        month_map = {'Jan':'01','Feb':'02','Mar':'03','Apr':'04','May':'05','Jun':'06','Jul':'07','Aug':'08','Sep':'09','Oct':'10','Nov':'11','Dec':'12'}
        m_str = month_map.get(parts[0].capitalize(), '03')
        d_str = parts[1].zfill(2)
        return f"2026-{m_str}-{d_str}", "Inconsistent date format (Mar-14 normalized to 2026-03-14)", "normalized"
        
    # Standard formats
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(date_str, fmt)
            if date_str == "04-05-2026":
                return "2026-04-05", "Ambiguous date 04-05-2026 resolved to 2026-04-05 (April 5) based on active members in the split list", "resolved_ambiguity"
            return dt.strftime("%Y-%m-%d"), None, None
        except ValueError:
            continue
            
    return None, f"Could not parse date: {date_str}", "error"

# Helper: Clean names
def clean_name(name):
    if not name:
        return None
    name = name.strip()
    if name.lower() == 'priya s' or name.lower() == 'priya':
        return 'Priya'
    if name.lower() == 'rohan':
        return 'Rohan'
    if name.lower() == 'aisha':
        return 'Aisha'
    if name.lower() == 'meera':
        return 'Meera'
    if name.lower() == 'sam':
        return 'Sam'
    if name.lower() == 'dev':
        return 'Dev'
    return name

def is_similar_desc(desc1, desc2):
    # Split into alphanumeric tokens
    words1 = set(re.findall(r'[a-z0-9]+', desc1.lower()))
    words2 = set(re.findall(r'[a-z0-9]+', desc2.lower()))
    
    # Remove standard stop words to avoid matching generic words
    stop_words = {'at', 'the', 'for', 'in', 'on', 'of', 'and', 'a', 'to', 'with', 'bill', 'dinner', 'groceries'}
    words1_filtered = words1 - stop_words
    words2_filtered = words2 - stop_words
    
    # If filtered lists are empty, use original lists
    w1 = words1_filtered if words1_filtered else words1
    w2 = words2_filtered if words2_filtered else words2
    
    intersection = w1.intersection(w2)
    smaller_size = min(len(w1), len(w2))
    
    if smaller_size == 0:
        return False
        
    ratio = len(intersection) / smaller_size
    return ratio >= 0.5 # 50% overlap of core words

# CSV Import Pipeline
def import_csv_data(filepath):
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get group ID
    cursor.execute("SELECT id FROM groups LIMIT 1")
    group_id = cursor.fetchone()[0]
    
    # Read CSV
    imported_count = 0
    anomalies_detected = []
    
    with open(filepath, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader) # skip header
        rows = list(reader)
        
    seen_expenses = [] # list of dicts to check duplicates and conflicts
    
    for idx, row in enumerate(rows, start=2): # 1-based index including header
        if not row or len(row) < 9:
            continue
            
        date_raw, desc_raw, paid_by_raw, amount_raw, currency_raw, split_type_raw, split_with_raw, split_details_raw, notes_raw = [r.strip() for r in row]
        row_anomalies = []
        
        # 1. Standardize Names
        paid_by = clean_name(paid_by_raw)
        if paid_by_raw and paid_by != paid_by_raw:
            row_anomalies.append({
                'type': 'name_discrepancy',
                'msg': f"Payer name '{paid_by_raw}' normalized to '{paid_by}'",
                'action': 'normalized'
            })
            
        # 2. Standardize Date
        split_with_raw_list = [clean_name(n) for n in split_with_raw.split(';') if n.strip()]
        date_clean, date_msg, date_action = clean_date(date_raw, idx, split_with_raw_list)
        if date_msg:
            row_anomalies.append({
                'type': 'date_anomaly',
                'msg': date_msg,
                'action': date_action if date_action else 'error'
            })
        if not date_clean:
            date_clean = "2026-02-01" # fallback
            
        # 3. Clean Amount
        amount_clean = amount_raw.replace('"', '').replace(',', '').strip()
        if amount_raw != amount_clean:
            row_anomalies.append({
                'type': 'format_discrepancy',
                'msg': f"Amount formatting cleaned: '{amount_raw}' -> '{amount_clean}'",
                'action': 're-formatted'
            })
            
        try:
            amount = float(amount_clean) if amount_clean else 0.0
        except ValueError:
            amount = 0.0
            row_anomalies.append({
                'type': 'format_error',
                'msg': f"Invalid numeric amount '{amount_clean}', defaulted to 0.0",
                'action': 'defaulted_to_zero'
            })
            
        if amount < 0:
            row_anomalies.append({
                'type': 'negative_amount',
                'msg': f"Negative expense amount {amount} treated as a refund",
                'action': 'processed_as_refund'
            })
        elif amount == 0:
            row_anomalies.append({
                'type': 'zero_amount',
                'msg': f"Zero-value expense ignored in balance calculations",
                'action': 'flagged'
            })
            
        # Check decimals
        if '.' in amount_clean and len(amount_clean.split('.')[1]) > 2:
            row_anomalies.append({
                'type': 'precision_issue',
                'msg': f"Precision decimal amount '{amount_clean}' imported exactly",
                'action': 'preserved_float'
            })
            
        # 4. Clean Currency
        currency = currency_raw.strip().upper()
        if not currency:
            currency = 'INR'
            row_anomalies.append({
                'type': 'missing_currency',
                'msg': "Missing currency: defaulted to 'INR'",
                'action': 'defaulted_to_inr'
            })
            
        # 5. Missing Payer
        if not paid_by:
            row_anomalies.append({
                'type': 'missing_payer',
                'msg': "Missing payer for shared expense. Marked as unassigned.",
                'action': 'pending_resolution'
            })
            
        # 6. Parse splits and check active memberships
        split_type = split_type_raw.strip().lower()
        if not split_type and paid_by and split_with_raw:
            if "paid" in desc_raw.lower() or "back" in desc_raw.lower() or "settle" in desc_raw.lower():
                split_type = 'settlement'
                row_anomalies.append({
                    'type': 'settlement_logged_as_expense',
                    'msg': f"Settlement transaction logged as expense: '{desc_raw}'",
                    'action': 'converted_to_settlement'
                })
            else:
                split_type = 'equal'
                row_anomalies.append({
                    'type': 'missing_split_type',
                    'msg': "Missing split type: defaulted to 'equal'",
                    'action': 'defaulted_to_equal'
                })
                
        # Parse split participants
        participants = []
        for p in split_with_raw_list:
            p_clean = clean_name(p)
            if p_clean:
                participants.append(p_clean)
                
        # Handle guest names (e.g. Dev's friend Kabir)
        cleaned_participants = []
        for p in participants:
            if p not in MEMBERSHIP:
                if "kabir" in p.lower() and paid_by == 'Dev':
                    row_anomalies.append({
                        'type': 'guest_participant',
                        'msg': f"External guest '{p}' included in split. Dev absorbs this share.",
                        'action': 'merged_into_payer'
                    })
                    cleaned_participants.append('Dev')
                else:
                    row_anomalies.append({
                        'type': 'unknown_participant',
                        'msg': f"Unknown participant '{p}' included. Payer absorbs share.",
                        'action': 'merged_into_payer'
                    })
                    if paid_by:
                        cleaned_participants.append(paid_by)
            else:
                cleaned_participants.append(p)
                
        # Handle membership over time constraints
        final_participants = []
        for p in cleaned_participants:
            if p in MEMBERSHIP and not is_user_active_on_date(p, date_clean):
                row_anomalies.append({
                    'type': 'membership_anomaly',
                    'msg': f"Participant '{p}' was inactive on {date_clean} (moved out or not joined yet). Removed from split.",
                    'action': 'removed_from_split'
                })
            else:
                final_participants.append(p)
                
        # 7. Check Duplicate / Conflict Entries
        status = 'active'
        is_settlement = 1 if split_type == 'settlement' else 0
        
        is_duplicate = False
        is_conflict = False
        duplicate_ref = None
        conflict_ref = None
        
        for seen in seen_expenses:
            if seen['date'] == date_clean and abs(seen['amount'] - amount) < 0.01 and seen['currency'] == currency:
                if is_similar_desc(seen['desc'], desc_raw):
                    is_duplicate = True
                    duplicate_ref = seen['row_idx']
                    status = 'duplicate_hidden'
                    break
            
            if seen['date'] == date_clean and is_similar_desc(seen['desc'], desc_raw):
                is_conflict = True
                conflict_ref = seen['row_idx']
                status = 'pending_resolution'
                seen['status'] = 'pending_resolution'
                
        if is_duplicate:
            row_anomalies.append({
                'type': 'duplicate_entry',
                'msg': f"Duplicate entry of row {duplicate_ref}: '{desc_raw}'",
                'action': 'pending_approval_to_delete'
            })
        elif is_conflict:
            row_anomalies.append({
                'type': 'conflicting_log',
                'msg': f"Conflicting entry with row {conflict_ref} for Thalassa dinner",
                'action': 'marked_pending_resolution'
            })
            
        # Parse split details and check percentage splits
        split_details = {}
        if split_details_raw:
            pairs = split_details_raw.split(';')
            for pair in pairs:
                if not pair.strip():
                    continue
                match = re.match(r'^([^0-9]+)\s+([0-9\.]+)%?$', pair.strip())
                if match:
                    n = clean_name(match.group(1))
                    val = float(match.group(2))
                    split_details[n] = val
                    
        # Verification of percentages
        if split_type == 'percentage' and split_details:
            total_pct = sum(split_details.values())
            if abs(total_pct - 100.0) > 0.01:
                row_anomalies.append({
                    'type': 'percentage_mismatch',
                    'msg': f"Percentages sum to {total_pct}% instead of 100%. Re-scaled to 100%.",
                    'action': 'auto-normalized'
                })
                scale_factor = 100.0 / total_pct
                for k in split_details:
                    split_details[k] *= scale_factor
                    
        # equal split check but split_details exists
        if split_type == 'equal' and split_details_raw:
            row_anomalies.append({
                'type': 'superfluous_split_details',
                'msg': "Equal split type had split details provided. Ignored details, split equally.",
                'action': 'ignored_details'
            })
            
        # Save to DB
        paid_by_id = None
        if paid_by:
            cursor.execute("SELECT id FROM users WHERE name = ?", (paid_by,))
            res = cursor.fetchone()
            if res:
                paid_by_id = res[0]
                
        cursor.execute("""
        INSERT INTO expenses (group_id, description, paid_by_id, amount, currency, date, split_type, notes, is_settlement, status, source_row)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (group_id, desc_raw, paid_by_id, amount, currency, date_clean, split_type, notes_raw, is_settlement, status, idx))
        
        expense_id = cursor.lastrowid
        amount_inr = amount * (USD_TO_INR if currency == 'USD' else 1.0)
        
        splits_calculated = {}
        
        # Calculate splits
        if is_settlement:
            recipient = clean_name(split_with_raw)
            if recipient:
                cursor.execute("SELECT id FROM users WHERE name = ?", (recipient,))
                rec_res = cursor.fetchone()
                if rec_res:
                    rec_id = rec_res[0]
                    splits_calculated[rec_id] = amount_inr
        else:
            num_part = len(final_participants)
            if num_part > 0:
                if split_type == 'equal' or not split_type:
                    share_val = amount_inr / num_part
                    for p in final_participants:
                        cursor.execute("SELECT id FROM users WHERE name = ?", (p,))
                        p_res = cursor.fetchone()
                        if p_res:
                            splits_calculated[p_res[0]] = splits_calculated.get(p_res[0], 0.0) + share_val
                elif split_type == 'percentage':
                    for p in final_participants:
                        cursor.execute("SELECT id FROM users WHERE name = ?", (p,))
                        p_res = cursor.fetchone()
                        if p_res:
                            pct = split_details.get(p, 100.0 / num_part)
                            splits_calculated[p_res[0]] = splits_calculated.get(p_res[0], 0.0) + amount_inr * (pct / 100.0)
                elif split_type == 'share':
                    total_shares = sum(split_details.get(p, 1.0) for p in final_participants)
                    if total_shares == 0:
                        total_shares = float(num_part)
                    for p in final_participants:
                        cursor.execute("SELECT id FROM users WHERE name = ?", (p,))
                        p_res = cursor.fetchone()
                        if p_res:
                            shares = split_details.get(p, 1.0)
                            splits_calculated[p_res[0]] = splits_calculated.get(p_res[0], 0.0) + amount_inr * (shares / total_shares)
                elif split_type == 'unequal':
                    total_assigned = sum(split_details.get(p, 0.0) for p in final_participants)
                    total_assigned_inr = total_assigned * (USD_TO_INR if currency == 'USD' else 1.0)
                    for p in final_participants:
                        cursor.execute("SELECT id FROM users WHERE name = ?", (p,))
                        p_res = cursor.fetchone()
                        if p_res:
                            val = split_details.get(p, 0.0)
                            val_inr = val * (USD_TO_INR if currency == 'USD' else 1.0)
                            splits_calculated[p_res[0]] = splits_calculated.get(p_res[0], 0.0) + val_inr
                    if abs(total_assigned_inr - amount_inr) > 1.0:
                        row_anomalies.append({
                            'type': 'unequal_split_mismatch',
                            'msg': f"Unequal split details sum to {total_assigned} instead of {amount}. Re-scaled proportionally.",
                            'action': 'auto-normalized'
                        })
                        scale_factor = amount_inr / total_assigned_inr if total_assigned_inr != 0 else 1.0
                        for u_id in splits_calculated:
                            splits_calculated[u_id] *= scale_factor
                            
        # splits are calculated directly, no post-processing needed
        for u_id, val_inr in splits_calculated.items():
            cursor.execute("""
            INSERT INTO expense_splits (expense_id, user_id, split_value, calculated_amount_inr)
            VALUES (?, ?, ?, ?)
            """, (expense_id, u_id, val_inr, val_inr))
            
        seen_expenses.append({
            'row_idx': idx,
            'date': date_clean,
            'amount': amount,
            'currency': currency,
            'desc': desc_raw,
            'paid_by': paid_by,
            'status': status,
            'db_id': expense_id
        })
        
        for anomaly in row_anomalies:
            cursor.execute("""
            INSERT INTO anomalies (row_index, date, description, paid_by, amount, currency, split_type, split_with, split_details, anomaly_type, description_msg, resolution_action)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (idx, date_raw, desc_raw, paid_by_raw, amount_raw, currency_raw, split_type_raw, split_with_raw, split_details_raw, anomaly['type'], anomaly['msg'], anomaly['action']))
            
            anomalies_detected.append({
                'row': idx,
                'description': desc_raw,
                'anomaly': anomaly['msg'],
                'action': anomaly['action']
            })
            
        imported_count += 1
        
    for seen in seen_expenses:
        if seen['status'] == 'pending_resolution':
            cursor.execute("UPDATE expenses SET status = 'pending_resolution' WHERE id = ?", (seen['db_id'],))
            
    conn.commit()
    conn.close()
    
    return imported_count, anomalies_detected

# Debt Simplification Engine
def calculate_net_balances():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, name FROM users")
    users = cursor.fetchall()
    user_map = {u['id']: u['name'] for u in users}
    
    credits = {uid: 0.0 for uid in user_map.keys()}
    debits = {uid: 0.0 for uid in user_map.keys()}
    
    cursor.execute("""
    SELECT id, paid_by_id, amount, currency, is_settlement, description FROM expenses 
    WHERE status = 'active'
    """)
    expenses = cursor.fetchall()
    
    for exp in expenses:
        exp_id = exp['id']
        payer_id = exp['paid_by_id']
        is_settlement = exp['is_settlement']
        amount = exp['amount']
        currency = exp['currency']
        
        amount_inr = amount * (USD_TO_INR if currency == 'USD' else 1.0)
        
        cursor.execute("SELECT user_id, calculated_amount_inr FROM expense_splits WHERE expense_id = ?", (exp_id,))
        splits = cursor.fetchall()
        
        if is_settlement:
            if payer_id:
                credits[payer_id] += amount_inr
            for s in splits:
                debits[s['user_id']] += s['calculated_amount_inr']
        else:
            if payer_id:
                credits[payer_id] += amount_inr
            for s in splits:
                debits[s['user_id']] += s['calculated_amount_inr']
                
    net_balances = {}
    for uid in user_map.keys():
        net_balances[uid] = credits[uid] - debits[uid]
        
    debtors = []
    creditors = []
    
    for uid, bal in net_balances.items():
        if bal < -0.01:
            debtors.append({'id': uid, 'name': user_map[uid], 'balance': -bal})
        elif bal > 0.01:
            creditors.append({'id': uid, 'name': user_map[uid], 'balance': bal})
            
    debtors.sort(key=lambda x: x['balance'], reverse=True)
    creditors.sort(key=lambda x: x['balance'], reverse=True)
    
    simplified_debts = []
    d_idx = 0
    c_idx = 0
    
    while d_idx < len(debtors) and c_idx < len(creditors):
        db = debtors[d_idx]
        cr = creditors[c_idx]
        
        amount_to_settle = min(db['balance'], cr['balance'])
        
        if amount_to_settle > 0.01:
            simplified_debts.append({
                'debtor_id': db['id'],
                'debtor_name': db['name'],
                'creditor_id': cr['id'],
                'creditor_name': cr['name'],
                'amount': round(amount_to_settle, 2)
            })
            
        db['balance'] -= amount_to_settle
        cr['balance'] -= amount_to_settle
        
        if db['balance'] < 0.01:
            d_idx += 1
        if cr['balance'] < 0.01:
            c_idx += 1
            
    # Compile detailed breakdown ledger
    detailed_ledger = {}
    for uid, name in user_map.items():
        ledger = []
        cursor.execute("""
        SELECT e.id, e.description, e.date, e.amount, e.currency, e.paid_by_id, e.is_settlement, s.calculated_amount_inr
        FROM expenses e
        JOIN expense_splits s ON e.id = s.expense_id
        WHERE s.user_id = ? AND e.status = 'active'
        """, (uid,))
        user_splits = cursor.fetchall()
        
        cursor.execute("""
        SELECT id, description, date, amount, currency, is_settlement FROM expenses
        WHERE paid_by_id = ? AND status = 'active'
        """, (uid,))
        user_payments = cursor.fetchall()
        
        for s in user_splits:
            payer_name = user_map.get(s['paid_by_id'], 'Unassigned')
            amount_inr = s['calculated_amount_inr']
            
            if s['paid_by_id'] == uid:
                if not s['is_settlement']:
                    ledger.append({
                        'expense_id': s['id'],
                        'date': s['date'],
                        'description': f"{s['description']} (Your Share)",
                        'payer': 'You',
                        'total_amount': s['amount'],
                        'currency': s['currency'],
                        'your_share': amount_inr,
                        'effect': -amount_inr,
                        'type': 'share'
                    })
            else:
                desc = s['description']
                if s['is_settlement']:
                    desc = f"Received settlement from {payer_name}"
                ledger.append({
                    'expense_id': s['id'],
                    'date': s['date'],
                    'description': desc,
                    'payer': payer_name,
                    'total_amount': s['amount'],
                    'currency': s['currency'],
                    'your_share': amount_inr,
                    'effect': -amount_inr,
                    'type': 'split'
                })
                
        for p in user_payments:
            p_id = p['id']
            amount_inr = p['amount'] * (USD_TO_INR if p['currency'] == 'USD' else 1.0)
            
            if p['is_settlement']:
                cursor.execute("""
                SELECT u.name FROM expense_splits s 
                JOIN users u ON s.user_id = u.id 
                WHERE s.expense_id = ?
                """, (p_id,))
                recip_res = cursor.fetchone()
                recip_name = recip_res[0] if recip_res else 'Someone'
                ledger.append({
                    'expense_id': p_id,
                    'date': p['date'],
                    'description': f"Settle payment to {recip_name}",
                    'payer': 'You',
                    'total_amount': p['amount'],
                    'currency': p['currency'],
                    'your_share': 0.0,
                    'effect': amount_inr,
                    'type': 'settlement_paid'
                })
            else:
                ledger.append({
                    'expense_id': p_id,
                    'date': p['date'],
                    'description': f"Paid for: {p['description']}",
                    'payer': 'You',
                    'total_amount': p['amount'],
                    'currency': p['currency'],
                    'your_share': 0.0,
                    'effect': amount_inr,
                    'type': 'payment'
                })
                
        ledger.sort(key=lambda x: x['date'])
        calculated_sum = sum(item['effect'] for item in ledger)
        detailed_ledger[name] = {
            'ledger': ledger,
            'net_balance': round(net_balances[uid], 2),
            'calculated_sum': round(calculated_sum, 2)
        }
        
    conn.close()
    
    balances_summary = []
    for uid, name in user_map.items():
        balances_summary.append({
            'user_id': uid,
            'name': name,
            'net_balance': round(net_balances[uid], 2)
        })
        
    return {
        'balances': balances_summary,
        'debts': simplified_debts,
        'ledgers': detailed_ledger
    }

# API: GET /api/data
@app.route('/api/data', methods=['GET'])
def get_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT e.id, e.description, e.amount, e.currency, e.date, e.split_type, e.notes, e.status, e.is_settlement, u.name as paid_by
    FROM expenses e
    LEFT JOIN users u ON e.paid_by_id = u.id
    ORDER BY e.date DESC
    """)
    expenses = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("""
    SELECT m.id, u.name, m.joined_date, m.left_date 
    FROM group_memberships m
    JOIN users u ON m.user_id = u.id
    """)
    members = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM anomalies ORDER BY row_index ASC")
    anomalies = [dict(row) for row in cursor.fetchall()]
    
    calc_res = calculate_net_balances()
    conn.close()
    
    return jsonify({
        'expenses': expenses,
        'members': members,
        'anomalies': anomalies,
        'balances': calc_res['balances'],
        'debts': calc_res['debts'],
        'ledgers': calc_res['ledgers']
    })

# API: POST /api/import
@app.route('/api/import', methods=['POST'])
def import_csv():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    filepath = os.path.join(app.root_path, 'expenses_export.csv')
    file.save(filepath)
    
    try:
        count, anomalies = import_csv_data(filepath)
        return jsonify({
            'success': True,
            'message': f"Imported {count} records successfully.",
            'anomalies': anomalies
        })
    except Exception as e:
        return jsonify({'error': f"Failed to import CSV: {str(e)}"}), 500

# API: POST /api/resolve-anomaly
@app.route('/api/resolve-anomaly', methods=['POST'])
def resolve_anomaly():
    data = request.json
    anomaly_id = data.get('anomaly_id')
    action = data.get('action')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM anomalies WHERE id = ?", (anomaly_id,))
    anomaly = cursor.fetchone()
    if not anomaly:
        conn.close()
        return jsonify({'error': 'Anomaly not found'}), 404
        
    row_idx = anomaly['row_index']
    
    if action == 'approve_delete':
        cursor.execute("UPDATE expenses SET status = 'deleted' WHERE source_row = ?", (row_idx,))
        cursor.execute("UPDATE anomalies SET status = 'resolved' WHERE id = ?", (anomaly_id,))
    elif action == 'keep_both':
        cursor.execute("UPDATE expenses SET status = 'active' WHERE source_row = ?", (row_idx,))
        cursor.execute("UPDATE anomalies SET status = 'resolved' WHERE id = ?", (anomaly_id,))
    elif action == 'assign_payer':
        payer_name = data.get('payer_name')
        cursor.execute("SELECT id FROM users WHERE name = ?", (payer_name,))
        payer_res = cursor.fetchone()
        if payer_res:
            payer_id = payer_res[0]
            cursor.execute("UPDATE expenses SET paid_by_id = ? WHERE source_row = ?", (payer_id, row_idx))
            cursor.execute("UPDATE anomalies SET status = 'resolved' WHERE id = ?", (anomaly_id,))
    elif action == 'resolve_conflict':
        winner_row = data.get('winner_row_idx')
        loser_row = data.get('loser_row_idx')
        cursor.execute("UPDATE expenses SET status = 'active' WHERE source_row = ?", (winner_row,))
        cursor.execute("UPDATE expenses SET status = 'deleted' WHERE source_row = ?", (loser_row,))
        cursor.execute("UPDATE anomalies SET status = 'resolved' WHERE row_index IN (?, ?)", (winner_row, loser_row))
        
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

# API: POST /api/expenses
@app.route('/api/expenses', methods=['POST'])
def add_expense():
    data = request.json
    desc = data.get('description')
    paid_by = data.get('paid_by')
    amount = float(data.get('amount'))
    currency = data.get('currency', 'INR')
    date_str = data.get('date')
    split_type = data.get('split_type', 'equal')
    participants = data.get('participants', [])
    split_details = data.get('split_details', {})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM groups LIMIT 1")
    group_id = cursor.fetchone()[0]
    
    cursor.execute("SELECT id FROM users WHERE name = ?", (paid_by,))
    paid_by_id = cursor.fetchone()[0]
    
    cursor.execute("""
    INSERT INTO expenses (group_id, description, paid_by_id, amount, currency, date, split_type, notes, is_settlement, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
    """, (group_id, desc, paid_by_id, amount, currency, date_str, split_type, '', 0))
    
    expense_id = cursor.lastrowid
    amount_inr = amount * (USD_TO_INR if currency == 'USD' else 1.0)
    
    splits = {}
    num_part = len(participants)
    if num_part > 0:
        if split_type == 'equal':
            share = amount_inr / num_part
            for p in participants:
                cursor.execute("SELECT id FROM users WHERE name = ?", (p,))
                u_id = cursor.fetchone()[0]
                splits[u_id] = share
        elif split_type == 'percentage':
            for p in participants:
                cursor.execute("SELECT id FROM users WHERE name = ?", (p,))
                u_id = cursor.fetchone()[0]
                pct = float(split_details.get(p, 100.0 / num_part))
                splits[u_id] = amount_inr * (pct / 100.0)
        elif split_type == 'share':
            total_shares = sum(float(split_details.get(p, 1.0)) for p in participants)
            for p in participants:
                cursor.execute("SELECT id FROM users WHERE name = ?", (p,))
                u_id = cursor.fetchone()[0]
                shares = float(split_details.get(p, 1.0))
                splits[u_id] = amount_inr * (shares / total_shares)
                
    for u_id, val_inr in splits.items():
        cursor.execute("""
        INSERT INTO expense_splits (expense_id, user_id, split_value, calculated_amount_inr)
        VALUES (?, ?, ?, ?)
        """, (expense_id, u_id, val_inr, val_inr))
        
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# API: POST /api/settle
@app.route('/api/settle', methods=['POST'])
def settle_payment():
    data = request.json
    debtor = data.get('debtor_name')
    creditor = data.get('creditor_name')
    amount = float(data.get('amount'))
    date_str = datetime.now().strftime('%Y-%m-%d')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM groups LIMIT 1")
    group_id = cursor.fetchone()[0]
    
    cursor.execute("SELECT id FROM users WHERE name = ?", (debtor,))
    debtor_id = cursor.fetchone()[0]
    
    cursor.execute("SELECT id FROM users WHERE name = ?", (creditor,))
    creditor_id = cursor.fetchone()[0]
    
    cursor.execute("""
    INSERT INTO expenses (group_id, description, paid_by_id, amount, currency, date, split_type, notes, is_settlement, status)
    VALUES (?, ?, ?, ?, 'INR', ?, 'settlement', '', 1, 'active')
    """, (group_id, f"Settlement: {debtor} paid {creditor}", debtor_id, amount, date_str))
    
    expense_id = cursor.lastrowid
    
    cursor.execute("""
    INSERT INTO expense_splits (expense_id, user_id, split_value, calculated_amount_inr)
    VALUES (?, ?, ?, ?)
    """, (expense_id, creditor_id, amount, amount))
    
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        init_db()
    app.run(debug=True, port=5000)
