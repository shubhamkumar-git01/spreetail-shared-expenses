import sqlite3
import os
from app import import_csv_data, calculate_net_balances, get_db_connection, init_db

def run_tests():
    print("=== Starting Shared Expenses App Test Suite ===")
    
    # 1. Initialize and import
    csv_path = 'expenses_export.csv'
    if not os.path.exists(csv_path):
        print(f"ERROR: {csv_path} not found in workspace!")
        return
        
    print(f"Found CSV at: {csv_path}. Running ingestion pipeline...")
    count, anomalies = import_csv_data(csv_path)
    print(f"Pipeline finished. Imported {count} rows. Detected {len(anomalies)} anomaly logs.")
    
    import json
    with open('import_report.json', 'w', encoding='utf-8') as f_out:
        json.dump(anomalies, f_out, indent=2)
    print("Saved import_report.json to scratch folder.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 2. Test duplicates detection
    cursor.execute("SELECT count(*) FROM expenses WHERE description LIKE '%Marina Bites%'")
    marina_bites_count = cursor.fetchone()[0]
    print(f"Total Marina Bites records in DB: {marina_bites_count} (should be 2)")
    
    cursor.execute("SELECT status FROM expenses WHERE description = 'dinner - marina bites'")
    res = cursor.fetchone()
    marina_bites_status = res[0] if res else None
    print(f"Marina Bites duplicate row status: '{marina_bites_status}' (should be 'duplicate_hidden')")
    assert marina_bites_status == 'duplicate_hidden', "Marina Bites duplicate check failed!"
    
    # 3. Test Thalassa Dinner conflict detection
    cursor.execute("SELECT status FROM expenses WHERE description LIKE '%Thalassa%'")
    thalassa_statuses = [row[0] for row in cursor.fetchall()]
    print(f"Thalassa dinner statuses: {thalassa_statuses} (should both be 'pending_resolution')")
    assert all(status == 'pending_resolution' for status in thalassa_statuses), "Thalassa conflict check failed!"
    
    # 4. Test Missing Payer
    cursor.execute("SELECT count(*) FROM expenses WHERE paid_by_id IS NULL AND description = 'House cleaning supplies'")
    missing_payer_count = cursor.fetchone()[0]
    print(f"House cleaning supplies (missing payer) record paid_by_id is NULL count: {missing_payer_count} (should be 1)")
    assert missing_payer_count == 1, "Missing payer check failed!"
    
    # 5. Test Guest split absorption
    cursor.execute("""
    SELECT u.name, s.calculated_amount_inr FROM expense_splits s
    JOIN users u ON s.user_id = u.id
    JOIN expenses e ON s.expense_id = e.id
    WHERE e.description = 'Parasailing'
    """)
    parasail_splits = {row[0]: row[1] for row in cursor.fetchall()}
    print(f"Parasailing splits: {parasail_splits}")
    assert 'Dev\'s friend Kabir' not in parasail_splits, "Kabir should be removed from splits!"
    assert abs(parasail_splits['Dev'] - 4980.0) < 0.1, f"Dev should absorb Kabir's share! Got {parasail_splits.get('Dev')}"
    assert abs(parasail_splits['Aisha'] - 2490.0) < 0.1, f"Aisha share should be 2490. Got {parasail_splits.get('Aisha')}"
    
    # 6. Test membership over time - Meera's April Groceries exclusion
    cursor.execute("""
    SELECT u.name, s.calculated_amount_inr FROM expense_splits s
    JOIN users u ON s.user_id = u.id
    JOIN expenses e ON s.expense_id = e.id
    WHERE e.date = '2026-04-02' AND e.description = 'Groceries BigBasket'
    """)
    groceries_splits = {row[0]: row[1] for row in cursor.fetchall()}
    print(f"April 2 Groceries splits: {groceries_splits}")
    assert 'Meera' not in groceries_splits, "Meera should not be in April 2 Groceries split!"
    assert abs(groceries_splits['Aisha'] - 880.0) < 0.1, "April 2 Groceries split was not redistributed correctly!"
    
    # 7. Test Sam March Electricity exclusion
    cursor.execute("""
    SELECT count(*) FROM expense_splits s
    JOIN users u ON s.user_id = u.id
    JOIN expenses e ON s.expense_id = e.id
    WHERE e.description = 'Electricity Mar' AND u.name = 'Sam'
    """)
    sam_march_elec = cursor.fetchone()[0]
    print(f"Sam's March Electricity records in DB: {sam_march_elec} (should be 0)")
    assert sam_march_elec == 0, "Sam was retroactively charged for March electricity!"
    
    # 8. Check balance calculations output
    calc_res = calculate_net_balances()
    print("\nCalculated Net Balances:")
    for bal in calc_res['balances']:
        print(f"  {bal['name']}: net balance = Rs. {bal['net_balance']}")
        
    print("\nSimplified Debts (Who pays whom):")
    for debt in calc_res['debts']:
        print(f"  {debt['debtor_name']} pays {debt['creditor_name']}: Rs. {debt['amount']}")
        
    conn.close()
    print("\n=== All Tests Passed Successfully! ===")

if __name__ == '__main__':
    run_tests()
