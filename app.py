import os
import sqlite3
from flask import Flask, render_template

app = Flask(__name__, template_folder='templates', static_folder='static')
DATABASE = 'expenses.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS users")
    cursor.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
    conn.commit()
    conn.close()

@app.route('/')
def index():
    return "Spreetail Shared Expenses Skeleton Server"

if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        init_db()
    app.run(debug=True, port=5000)
