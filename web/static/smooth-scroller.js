document.addEventListener("DOMContentLoaded", function() {
    // Select all anchor links that have a hash (i.e., #)
    var anchorLinks = document.querySelectorAll('a[href^="#"]');

    anchorLinks.forEach(function(link) {
        link.addEventListener("click", function(e) {
            // Prevent the default anchor behavior
            e.preventDefault();

            // Get the target element's ID from the href attribute
            var targetId = this.getAttribute("href");
            var targetElement = document.querySelector(targetId);

            if (targetElement) {
                // Check if the sticky header exists and get its height
                var header = document.querySelector('.sticky-header');
                var headerHeight = header ? header.offsetHeight : 0;

                // Calculate position to scroll to, accounting for the header height
                var positionToScroll = targetElement.getBoundingClientRect().top + window.pageYOffset - headerHeight;

                // Smooth scroll to the calculated position
                window.scrollTo({
                    top: positionToScroll,
                    behavior: "smooth"
                });
            }
        });
    });
});


