// Intended for Reports
function toggleSubnav() {
    const subNavContainer = document.getElementById('subnav');
    const menuButton = document.getElementById('menu-button');
    subNavContainer.classList.toggle('subnav-menu-show');
    menuButton.classList.toggle('subnav-open');
    return true;
}

// Add event listener for the menu button
document.addEventListener('DOMContentLoaded', () => {
    const menuButton = document.getElementById('menu-button');
    if (menuButton) {
        menuButton.addEventListener('click', toggleSubnav);
    }
});