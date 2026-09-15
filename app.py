import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# --- DATABASE SETUP ---
DB_PATH = "budget.db" # In production on PikaPods, change this to "data/budget.db" to use persistent volume

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS Accounts (
            id INTEGER PRIMARY KEY, name TEXT, balance REAL
        );
        CREATE TABLE IF NOT EXISTS Envelopes (
            id INTEGER PRIMARY KEY, name TEXT
        );
        CREATE TABLE IF NOT EXISTS Transactions (
            id INTEGER PRIMARY KEY, date TEXT, payee TEXT, 
            amount REAL, account_id INTEGER, envelope_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS Budget_Months (
            month_year TEXT, envelope_id INTEGER, assigned_amount REAL,
            PRIMARY KEY (month_year, envelope_id)
        );
    ''')
    conn.commit()
    conn.close()

def run_query(query, params=()):
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(query, conn, params=params)

def execute_query(query, params=()):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(query, params)
        conn.commit()

# --- CORE LOGIC ---
def calculate_rta(current_month):
    # Total Cash (Simplified: Sum of initial balances + inflow transactions)
    # Note: In a full build, differentiate between income and transfers.
    accounts_df = run_query("SELECT SUM(balance) as total FROM Accounts")
    total_cash = accounts_df['total'].iloc[0] if not accounts_df.empty and pd.notna(accounts_df['total'].iloc[0]) else 0.0
    
    # Total Budgeted (Money placed into envelopes up to this month)
    budgeted_df = run_query("SELECT SUM(assigned_amount) as total FROM Budget_Months")
    total_budgeted = budgeted_df['total'].iloc[0] if not budgeted_df.empty and pd.notna(budgeted_df['total'].iloc[0]) else 0.0
    
    return total_cash - total_budgeted

def auto_suggest_envelope(payee_name):
    if not payee_name:
        return None
    # Query last 5 transactions for this payee to find most common envelope
    query = '''
        SELECT envelope_id, COUNT(envelope_id) as freq 
        FROM Transactions 
        WHERE payee LIKE ? 
        GROUP BY envelope_id 
        ORDER BY freq DESC LIMIT 1
    '''
    result = run_query(query, (f"%{payee_name}%",))
    if not result.empty:
        return result['envelope_id'].iloc[0]
    return None

# --- STREAMLIT UI ---
st.set_page_config(page_title="Envelope Budget", layout="wide")
init_db()

current_month = datetime.now().strftime("%Y-%m")
rta = calculate_rta(current_month)

# Header
col1, col2 = st.columns([3, 1])
with col1:
    st.title("Envelope Budgeting")
with col2:
    st.metric(label="Ready to Assign", value=f"${rta:,.2f}")
    if rta < 0:
        st.error("You have assigned more money than you have!")

tab1, tab2, tab3 = st.tabs(["Budget", "Transactions", "Settings"])

with tab1:
    st.subheader(f"Budget for {current_month}")
    envelopes = run_query("SELECT * FROM Envelopes")
    
    if not envelopes.empty:
        for index, row in envelopes.iterrows():
            env_id = row['id']
            # Get assigned amount
            assigned = run_query("SELECT assigned_amount FROM Budget_Months WHERE month_year=? AND envelope_id=?", (current_month, env_id))
            assigned_val = assigned['assigned_amount'].iloc[0] if not assigned.empty else 0.0
            
            # Get spent amount
            spent = run_query("SELECT SUM(amount) as total FROM Transactions WHERE envelope_id=? AND strftime('%Y-%m', date)=?", (env_id, current_month))
            spent_val = spent['total'].iloc[0] if not spent.empty and pd.notna(spent['total'].iloc[0]) else 0.0
            
            col_name, col_assigned, col_activity, col_available = st.columns(4)
            col_name.write(row['name'])
            
            # Form to assign money
            with col_assigned:
                new_assigned = st.number_input("Assign", value=float(assigned_val), key=f"assign_{env_id}", step=10.0, label_visibility="collapsed")
                if new_assigned != assigned_val:
                    execute_query('''
                        INSERT INTO Budget_Months (month_year, envelope_id, assigned_amount) 
                        VALUES (?, ?, ?) 
                        ON CONFLICT(month_year, envelope_id) 
                        DO UPDATE SET assigned_amount=excluded.assigned_amount
                    ''', (current_month, env_id, new_assigned))
                    st.rerun()
            
            col_activity.write(f"${spent_val:,.2f}")
            col_available.write(f"${(assigned_val + spent_val):,.2f}") # Spent is usually negative outflow
    else:
        st.info("Go to Settings to add your first envelope.")

with tab2:
    st.subheader("Add Manual Transaction")
    
    with st.form("transaction_form", clear_on_submit=True):
        t_date = st.date_input("Date")
        t_payee = st.text_input("Payee")
        t_amount = st.number_input("Amount (Negative for outflow)", step=1.0)
        
        accounts = run_query("SELECT * FROM Accounts")
        envelopes = run_query("SELECT * FROM Envelopes")
        
        account_dict = dict(zip(accounts.name, accounts.id)) if not accounts.empty else {}
        env_dict = dict(zip(envelopes.name, envelopes.id)) if not envelopes.empty else {}
        
        t_account = st.selectbox("Account", options=list(account_dict.keys()))
        t_envelope = st.selectbox("Envelope", options=list(env_dict.keys()))
        
        submitted = st.form_submit_button("Record Transaction")
        if submitted:
            if t_account and t_envelope:
                execute_query('''
                    INSERT INTO Transactions (date, payee, amount, account_id, envelope_id)
                    VALUES (?, ?, ?, ?, ?)
                ''', (t_date, t_payee, t_amount, account_dict[t_account], env_dict[t_envelope]))
                st.success("Transaction recorded!")
                st.rerun()

with tab3:
    st.subheader("Setup")
    col_acc, col_env = st.columns(2)
    
    with col_acc:
        st.write("Add Account")
        with st.form("account_form"):
            acc_name = st.text_input("Account Name")
            acc_bal = st.number_input("Starting Balance", step=100.0)
            if st.form_submit_button("Add"):
                execute_query("INSERT INTO Accounts (name, balance) VALUES (?, ?)", (acc_name, acc_bal))
                st.rerun()
                
    with col_env:
        st.write("Add Envelope")
        with st.form("envelope_form"):
            env_name = st.text_input("Envelope Category")
            if st.form_submit_button("Add"):
                execute_query("INSERT INTO Envelopes (name) VALUES (?)", (env_name,))
                st.rerun()
              
