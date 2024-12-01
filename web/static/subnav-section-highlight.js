document.addEventListener('DOMContentLoaded', () => {
  const observerCallback = (entries, observer) => {
    entries.forEach(entry => {
      const navLink = document.querySelector(`a[href="#${entry.target.id}"]`);
      if (entry.isIntersecting) {
        document.querySelectorAll('.subnav-panel a').forEach(link => {
          link.classList.remove('active');
        });
        if (navLink) {
          navLink.classList.add('active');
        }
        // Highlight the followup_qs link if the followups section is intersecting
        if (entry.target.classList.contains('followups')) {
          const followupLink = document.querySelector('a[href="#followup_qs"]');
          if (followupLink) {
            followupLink.classList.add('active');
          }
        }
      }
      updateAccordionHeaderClass();
    });
  };

  const observerOptions = {
    root: null,
    rootMargin: '-50% 0px -50% 0px',
    threshold: [],
  };

  const observer = new IntersectionObserver(observerCallback, observerOptions);
  const sections = document.querySelectorAll('#report-summary, .report-section, .followups');
  sections.forEach(section => observer.observe(section));

  window.addEventListener('resize', () => {
    observer.disconnect();
    sections.forEach(section => observer.observe(section));
  });

  function updateAccordionHeaderClass() {
    const accordions = document.querySelectorAll('.accordion-item');
    accordions.forEach(header => {
      const hasActiveChild = header.querySelector('.active') !== null;
      if (hasActiveChild) {
        header.classList.add('has-active-child');
        const caret = header.querySelector('.accordion-caret');
        if (caret && !caret.classList.contains('open')) {
          toggleAccordion(caret);
        }
      } else {
        header.classList.remove('has-active-child');
        const caret = header.querySelector('.accordion-caret');
        if (caret && caret.classList.contains('open')) {
          toggleAccordion(caret);
        }
      }
    });
  }
});