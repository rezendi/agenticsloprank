
document.addEventListener('DOMContentLoaded', function() {
    const messagesContainer = document.getElementById('messages-container');
    if (messagesContainer) {
        messagesContainer.addEventListener('click', function(event) {
            if (event.target.classList.contains('dismiss-message')) {
                const messageElement = event.target.closest('.message');
                if (messageElement) {
                    messageElement.remove();
                }
                if (messagesContainer.children.length === 0) {
                    messagesContainer.remove();
                }
            }
        });
    }
});
