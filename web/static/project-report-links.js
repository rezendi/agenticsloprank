document.addEventListener('DOMContentLoaded', () => {
    const reportRows = document.querySelectorAll('.customer-report-row, .project-row');
    reportRows.forEach(row => {
        row.addEventListener('click', (event) => {
            console.log('Row clicked:', row); // Debug log
            if (!event.target.closest('a')) {
                const link = row.querySelector('a');
                if (link) {
                    console.log('Link found, clicking:', link.href); // Debug log
                    link.click();
                } else {
                    console.log('No link found in row.'); // Debug log
                }
            }
        });
    });
});