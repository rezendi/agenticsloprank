
function updateMissionStatus() {
// Check for updates to the mission status after the dashboard has loaded
    const reportRows = document.querySelectorAll('.customer-report-row');
    if (reportRows.length === 0) return;

    const missionsToUpdate = Array.from(reportRows).filter(row => {
        const currentStatus = parseInt(row.getAttribute('data-mission-status'));
        return currentStatus !== 2;
    });

    if (missionsToUpdate.length === 0) return;

    missionsToUpdate.forEach(row => {
        const missionId = row.getAttribute('data-mission-id');
        const currentStatus = parseInt(row.getAttribute('data-mission-status'));

        fetch(`/mission_status/${missionId}.json`)
            .then(response => response.json())
            .then(data => {
                const newStatus = data.status;
                
                if (newStatus !== currentStatus) {
                    row.setAttribute('data-mission-status', newStatus);
                    updateStatusElement(row, newStatus);
                }
            })
            .catch(error => console.error('Error:', error));
    });
}

function updateStatusElement(row, status) {
    let statusElement = row.querySelector('.report-status');
    
    if (status === 2) {
        // Complete: remove status element
        if (statusElement) statusElement.remove();
    } else {
        if (!statusElement) {
            statusElement = document.createElement('div');
            statusElement.className = 'report-status';
            row.insertBefore(statusElement, row.querySelector('label'));
        }

        if (status === -2) {
            // Error
            statusElement.innerHTML = '<strong class="error-message">X Error</strong>';
        } else if (status === 0 || status === -1 || status === 1) {
            // In Progress
            statusElement.innerHTML = '<span class="spinner"></span><strong class="pl-1">In Progress</strong>';
        }
    }
}
  
// Check every 30 seconds
setInterval(updateMissionStatus, 30000);