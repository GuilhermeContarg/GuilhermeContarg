import json
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

TRANSACTIONS_FILE = 'data/transactions.json'

def read_transactions():
    """Reads transactions from the JSON file."""
    try:
        with open(TRANSACTIONS_FILE, 'r') as f:
            # Check if the file is empty
            content = f.read()
            if not content:
                return []
            return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def write_transactions(transactions):
    """Writes transactions to the JSON file."""
    with open(TRANSACTIONS_FILE, 'w') as f:
        json.dump(transactions, f, indent=4)

@app.route('/')
def index():
    """Serves the main HTML page."""
    return render_template('index.html')

@app.route('/transactions', methods=['GET'])
def get_transactions():
    """Returns all transactions and the current balance."""
    transactions = read_transactions()
    balance = sum(t['amount'] for t in transactions)
    return jsonify({'transactions': transactions, 'balance': balance})

@app.route('/transactions', methods=['POST'])
def add_transaction():
    """Adds a new transaction."""
    new_transaction = request.json
    if not new_transaction or 'description' not in new_transaction or 'amount' not in new_transaction:
        return jsonify({'error': 'Invalid transaction data'}), 400

    try:
        # Ensure amount is a float
        new_transaction['amount'] = float(new_transaction['amount'])
    except ValueError:
        return jsonify({'error': 'Invalid amount format'}), 400

    transactions = read_transactions()
    transactions.append(new_transaction)
    write_transactions(transactions)

    return jsonify(new_transaction), 201

if __name__ == '__main__':
    app.run(debug=True, port=5000)
