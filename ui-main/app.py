from flask import Flask, render_template, request, redirect, url_for
app = Flask(__name__)

# sample visitors
VISITORS = [
    {'id': 1, 'name': 'John Doe',   'checkin_time': '10:30 AM', 'status': 'waiting'},
    {'id': 2, 'name': 'Jane Smith', 'checkin_time': '10:45 AM', 'status': 'waiting'},
]

# sample activity / insights (unchanged)
ACTIVITY = {
    1: ["Deposited $2,500 to Savings", "Checked account balance", "Issued new debit card"],
    2: ["Opened a new checking account", "Made a loan payment", "Updated contact info"]
}
INSIGHTS = {
    1: ["High savings growth (+5%)", "Low checking balance – consider alert", "Credit score is excellent"],
    2: ["New account funded promptly", "On-time loan payments", "Contact info up-to-date"]
}

# NEW: sample accounts & transactions
ACCOUNTS = {
    1: ["Checking", "Savings"],
    2: ["Checking", "Auto Loan"]
}
TRANSACTIONS = {
    (1, "Checking"): [
        "- $50.00 Grocery", "+ $1,200.00 Payroll", "- $120.00 Utilities",
        "- $30.00 Coffee", "- $75.00 Gas", "+ $200.00 Refund",
        "- $60.00 Dining", "- $15.00 Parking", "+ $500.00 Transfer", "- $10.00 ATM Fee"
    ],
    (1, "Savings"): [
        "+ $300.00 Transfer", "+ $500.00 Interest", "+ $100.00 Gift",
        "+ $50.00 Bonus", "+ $20.00 Interest"
    ],
    (2, "Checking"): [
        "+ $2,000.00 Payroll", "- $75.00 Grocery", "- $150.00 Electronics",
        "- $25.00 Coffee"
    ],
    (2, "Auto Loan"): [
        "- $250.00 Payment", "- $2.00 Late Fee", "- $250.00 Payment"
    ]
}

@app.route('/')
def dashboard():
    sel_id = request.args.get('selected', type=int)
    selected = None
    recent = []
    insights = []
    accounts = []
    transactions = {}

    if sel_id:
        # find the visitor
        selected = next((v for v in VISITORS if v['id'] == sel_id), None)
        if selected:
            selected['status'] = 'done'
            recent = ACTIVITY.get(sel_id, [])
            insights = INSIGHTS.get(sel_id, [])
            accounts = ACCOUNTS.get(sel_id, [])
            # build a dict mapping account -> txn list
            for acct in accounts:
                transactions[acct] = TRANSACTIONS.get((sel_id, acct), [])

    return render_template(
        'visitors.html',
        visitors=VISITORS,
        selected=selected,
        recent_activity=recent,
        ai_insights=insights,
        accounts=accounts,
        transactions=transactions
    )

@app.route('/pickup/<int:visitor_id>')
def pickup(visitor_id):
    return redirect(url_for('dashboard', selected=visitor_id))

if __name__ == '__main__':
    app.run(debug=True)