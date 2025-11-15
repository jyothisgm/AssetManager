document.addEventListener("DOMContentLoaded", function () {
    const observer = new MutationObserver((mutations, obs) => {
        const link = document.querySelector("tr.add-row a.addlink");
        if (link) {
        const parentGroup = link.closest(".inline-group");
        if (parentGroup && parentGroup.id.includes("gmailaccount")) {
            // Remove Django’s default click handler
            const newLink = link.cloneNode(true);
            link.parentNode.replaceChild(newLink, link);

            // Add our own behaviour
            newLink.addEventListener("click", function (e) {
                e.preventDefault(); // stop Django’s inline-adding JS
                window.location.href = "/user/gmail_connect/";
            });

            // stop observing after successful replacement
            obs.disconnect();
        }
        }
    });

    observer.observe(document.body, { childList: true, subtree: true });
});
