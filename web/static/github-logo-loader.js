document.addEventListener('DOMContentLoaded', function() {
  const repoLogos = document.querySelectorAll('.repo-logo');

  const observer = new IntersectionObserver((entries, observer) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const repoName = entry.target.dataset.repo;

        if (!repoName || repoName.trim() === '') {
          observer.unobserve(entry.target);
          return;
        }

        if (repoName.indexOf('/') === -1) {
          createFallbackImage(entry.target); // Create fallback image if repo name is invalid
          observer.unobserve(entry.target);
          return;
        }

        const [owner, repo] = repoName.split('/');
        const avatarUrl = `https://github.com/${owner}.png`;

        createImage(entry.target, avatarUrl); // Create image for the repo logo

        // Handle image loading success
        const img = entry.target.querySelector('img');
        img.onload = function() {
          entry.target.style.backgroundColor = 'transparent'; // Set background to transparent
        };

        // Handle image loading error
        img.onerror = function() {
          createFallbackImage(entry.target); // Fallback to default logo if fetching fails
          entry.target.style.backgroundColor = 'transparent';
        };

        observer.unobserve(entry.target);
      }
    });
  }, { rootMargin: '100px' });

  repoLogos.forEach(logo => observer.observe(logo));

  function createImage(container, src) {
    const img = document.createElement('img');
    img.src = src;
    img.alt = `${container.dataset.repo.split('/')[0]} logo`;
    img.className = 'github-logo';
    container.appendChild(img);
  }

  function createFallbackImage(container) {
    const img = document.createElement('img');
    img.src = defaultLogoUrl; // Use the dynamically set default logo URL
    img.alt = 'Default GitHub logo';
    img.className = 'github-logo';
    container.appendChild(img);
  }
});