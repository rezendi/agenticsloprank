document.addEventListener('DOMContentLoaded', (event) => {
    // Select all code blocks with the class 'language-diff'
    const codeBlocks = document.querySelectorAll('pre code.language-diff');

    // Iterate over each code block
    codeBlocks.forEach(codeBlock => {
        // Split the content by new line to process each line
        const lines = codeBlock.textContent.split('\n');
        // Clear the current content
        codeBlock.textContent = '';

        // Iterate over each line to apply styling
        lines.forEach(line => {
            const span = document.createElement('span');

            // Determine the line type and apply corresponding class
            if (line.startsWith('+')) {
                span.className = 'added';
            } else if (line.startsWith('-')) {
                span.className = 'removed';
            } else {
                span.className = 'unchanged';
            }

            // Set the text content of the span and append it to the code block
            span.textContent = line + '\n'; // Add newline for spacing
            codeBlock.appendChild(span);
        });
    });
});