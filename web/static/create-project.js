document.addEventListener('DOMContentLoaded', function() {
    const createButton = document.getElementById('create-project-button');
    const overlay = document.getElementById('create-project-overlay');
    const cancelButton = document.getElementById('cancel-create-project');
    const form = document.getElementById('create-project-form');

    createButton.addEventListener('click', function() {
        overlay.style.display = 'flex';
    });

    cancelButton.addEventListener('click', function() {
        overlay.style.display = 'none';
    });

    form.addEventListener('submit', function(e) {
        e.preventDefault();
        const formData = new FormData(form);

        fetch('/config/create_project/', {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                window.location.href = data.redirect_url;
            } else {
                alert(data.message);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('An error occurred. Please try again.');
        });
    });
});