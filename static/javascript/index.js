// Fade out and remove flash messages after 4 seconds.
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.flash, .flash-msg').forEach(function (flash) {
        setTimeout(function () {
            flash.style.transition = 'opacity 0.5s';
            flash.style.opacity = '0';
            setTimeout(function () { flash.remove(); }, 500);
        }, 4000);
    });
});
