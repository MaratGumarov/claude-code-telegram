// Initialize Telegram Web App
const tg = window.Telegram.WebApp;

// Initialize app
(function() {
    'use strict';

    // Expand to full height
    tg.ready();
    tg.expand();

    // Set header color to match Telegram theme
    tg.setHeaderColor('secondary_bg_color');

    // Get elements
    const loadingEl = document.getElementById('loading');
    const errorEl = document.getElementById('error');
    const errorMessageEl = document.getElementById('error-message');
    const diffContainerEl = document.getElementById('diff-container');
    const branchNameEl = document.getElementById('branch-name');
    const repoPathEl = document.getElementById('repo-path');

    // Get token from URL
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');

    if (!token) {
        showError('No access token provided');
        return;
    }

    // Fetch diff from API
    fetchDiff(token);

    async function fetchDiff(token) {
        try {
            // Get base URL from current location or use relative path
            const baseUrl = window.location.origin;
            const response = await fetch(`${baseUrl}/api/diff/${token}`);

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            // Update header info
            if (data.branch) {
                branchNameEl.textContent = data.branch;
            }
            if (data.repo_path) {
                repoPathEl.textContent = shortenPath(data.repo_path);
            }

            // Hide loading
            loadingEl.classList.add('hidden');

            // Check if there are changes
            if (!data.diff || data.diff === 'No changes to show') {
                showEmptyState();
                return;
            }

            // Render diff
            renderDiff(data.diff);

        } catch (error) {
            console.error('Error fetching diff:', error);
            showError(error.message || 'Failed to load diff');
        }
    }

    function renderDiff(diffText) {
        try {
            // Create diff configuration
            const configuration = {
                drawFileList: true,
                fileListToggle: true,
                fileContentToggle: true,
                matching: 'lines',
                outputFormat: 'side-by-side',
                synchronisedScroll: true,
                highlight: true,
                renderNothingWhenEmpty: false,
            };

            // Detect if screen is narrow, use line-by-line view
            if (window.innerWidth < 768) {
                configuration.outputFormat = 'line-by-line';
            }

            // Create diff2html UI
            const diff2htmlUi = new Diff2HtmlUI(diffContainerEl, diffText, configuration);
            diff2htmlUi.draw();

            // Show haptic feedback on success
            tg.HapticFeedback.notificationOccurred('success');

        } catch (error) {
            console.error('Error rendering diff:', error);
            showError('Failed to render diff: ' + error.message);
        }
    }

    function showError(message) {
        loadingEl.classList.add('hidden');
        errorEl.classList.remove('hidden');
        errorMessageEl.textContent = message;

        // Show haptic feedback on error
        tg.HapticFeedback.notificationOccurred('error');
    }

    function showEmptyState() {
        diffContainerEl.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">✨</div>
                <h3>No changes</h3>
                <p>Working tree is clean</p>
            </div>
        `;

        tg.HapticFeedback.notificationOccurred('success');
    }

    function shortenPath(path) {
        // Shorten long paths for mobile display
        const parts = path.split('/');
        if (parts.length > 3) {
            return '.../' + parts.slice(-2).join('/');
        }
        return path;
    }

    // Handle orientation changes
    window.addEventListener('resize', function() {
        // Re-render diff with appropriate layout if needed
        const diffData = diffContainerEl.getAttribute('data-diff');
        if (diffData) {
            renderDiff(diffData);
        }
    });

})();
