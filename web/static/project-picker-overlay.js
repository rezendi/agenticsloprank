function initializeProjectOverlay() {
  const showOverlayButton = document.getElementById('show-projects-overlay');
  const closeOverlayButton = document.getElementById('close-projects-overlay');
  const overlay = document.getElementById('projects-overlay');

  if (showOverlayButton && closeOverlayButton && overlay) {
    showOverlayButton.addEventListener('click', function(e) {
      e.preventDefault();
      overlay.style.display = 'flex';
    });

    closeOverlayButton.addEventListener('click', function(e) {
      e.preventDefault();
      e.stopPropagation();
      overlay.style.display = 'none';
    });

    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) {
        overlay.style.display = 'none';
      }
    });
  }
}

document.addEventListener('DOMContentLoaded', function() {
  const configValuesContainer = document.getElementById('values');
  
  if (configValuesContainer) {
    // Configure view: Wait for the config values to load
    const observer = new MutationObserver(function(mutations) {
      if (mutations[0].addedNodes.length > 0) {
        initializeProjectOverlay();
        observer.disconnect();
      }
    });
    observer.observe(configValuesContainer, { childList: true });
  } else {
    // Report view: Initialize immediately
    initializeProjectOverlay();
  }
});
