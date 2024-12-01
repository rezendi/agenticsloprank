document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('customer-name-form');
    const messageDiv = document.getElementById('customer-name-message');
    const messageContainer = document.getElementById('customer-name-message-container');

    form.addEventListener('submit', function(e) {
        e.preventDefault();
        const formData = new FormData(form);

        fetch('/config/update_customer_name/', {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': '{{ csrf_token }}'
            }
        })
        .then(response => response.json())
        .then(data => {
            messageDiv.textContent = data.message;
            messageDiv.className = data.status === 'success' ? 'success-message' : 'error-message';
            messageContainer.style.display = 'block';
            setTimeout(() => {
                messageContainer.style.display = 'none';
            }, 3000);
        })
        .catch(error => {
            console.error('Error:', error);
            messageDiv.textContent = 'An error occurred. Please try again.';
            messageDiv.className = 'error-message';
            messageContainer.style.display = 'block';
        });
    });
});