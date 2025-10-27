document.addEventListener('DOMContentLoaded', () => {
    const transactionForm = document.getElementById('transaction-form');
    const transactionList = document.getElementById('transaction-list');
    const balanceDisplay = document.getElementById('balance');

    // Fetch and display transactions on page load
    fetchTransactions();

    // Handle form submission
    transactionForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const description = document.getElementById('description').value;
        const amount = document.getElementById('amount').value;

        if (description.trim() === '' || amount.trim() === '') {
            alert('Please enter both description and amount.');
            return;
        }

        const newTransaction = {
            description,
            amount: parseFloat(amount)
        };

        try {
            const response = await fetch('/transactions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(newTransaction)
            });

            if (response.ok) {
                // Clear form fields
                document.getElementById('description').value = '';
                document.getElementById('amount').value = '';
                // Refresh the transactions list
                fetchTransactions();
            } else {
                const errorData = await response.json();
                alert(`Error: ${errorData.error}`);
            }
        } catch (error) {
            console.error('Error adding transaction:', error);
            alert('An error occurred while adding the transaction.');
        }
    });

    // Function to fetch and display transactions
    async function fetchTransactions() {
        try {
            const response = await fetch('/transactions');
            const data = await response.json();

            // Clear the current list
            transactionList.innerHTML = '';

            // Update the balance
            balanceDisplay.textContent = data.balance.toFixed(2);

            // Populate the transactions list
            data.transactions.forEach(transaction => {
                const li = document.createElement('li');

                const descriptionSpan = document.createElement('span');
                descriptionSpan.textContent = transaction.description;

                const amountSpan = document.createElement('span');
                amountSpan.textContent = `R$${transaction.amount.toFixed(2)}`;

                // Add class for styling based on amount
                amountSpan.classList.add(transaction.amount >= 0 ? 'income' : 'expense');

                li.appendChild(descriptionSpan);
                li.appendChild(amountSpan);

                transactionList.appendChild(li);
            });
        } catch (error) {
            console.error('Error fetching transactions:', error);
        }
    }
});
