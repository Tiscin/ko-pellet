// ko-pellet - Recipe Import for KitchenOwl

// State
let currentRecipe = null;
let selectedImage = null;
let households = [];
let selectedHouseholdId = null;
let isAuthenticated = false;
let currentUser = null;
let secretsStatus = {};
let currentSourceType = 'url';
let statsExpanded = false;

// Secret key to input ID mapping
const SECRET_KEY_MAP = {
    'kitchenowl_token': 'KitchenowlToken',
    'anthropic_api_key': 'AnthropicApiKey',
    'openai_api_key': 'OpenaiApiKey',
};

// DOM Elements
const elements = {
    tabs: document.querySelectorAll('.tab'),
    sections: document.querySelectorAll('.intake-section'),
    loginBtn: document.getElementById('loginBtn'),
    loginBanner: document.getElementById('loginBanner'),
    loginBannerBtn: document.getElementById('loginBannerBtn'),
    userInfo: document.getElementById('userInfo'),
    userName: document.getElementById('userName'),
    logoutBtn: document.getElementById('logoutBtn'),
    mainContent: document.getElementById('mainContent'),
    recipeUrl: document.getElementById('recipeUrl'),
    parseUrlBtn: document.getElementById('parseUrlBtn'),
    dropZone: document.getElementById('dropZone'),
    imageInput: document.getElementById('imageInput'),
    cameraInput: document.getElementById('cameraInput'),
    takePhotoBtn: document.getElementById('takePhotoBtn'),
    imagePreview: document.getElementById('imagePreview'),
    previewImg: document.getElementById('previewImg'),
    clearImage: document.getElementById('clearImage'),
    parseImageBtn: document.getElementById('parseImageBtn'),
    recipeText: document.getElementById('recipeText'),
    parseTextBtn: document.getElementById('parseTextBtn'),
    previewSection: document.getElementById('preview-section'),
    confidenceBadge: document.getElementById('confidenceBadge'),
    reviewWarning: document.getElementById('reviewWarning'),
    reviewFields: document.getElementById('reviewFields'),
    recipeForm: document.getElementById('recipeForm'),
    ingredientsList: document.getElementById('ingredientsList'),
    instructionsList: document.getElementById('instructionsList'),
    addIngredient: document.getElementById('addIngredient'),
    addInstruction: document.getElementById('addInstruction'),
    cancelBtn: document.getElementById('cancelBtn'),
    saveBtn: document.getElementById('saveBtn'),
    editTitle: document.getElementById('editTitle'),
    editDescription: document.getElementById('editDescription'),
    editPrepTime: document.getElementById('editPrepTime'),
    editCookTime: document.getElementById('editCookTime'),
    editTotalTime: document.getElementById('editTotalTime'),
    editServings: document.getElementById('editServings'),
    editTags: document.getElementById('editTags'),
    editSource: document.getElementById('editSource'),
    editNotes: document.getElementById('editNotes'),
    loading: document.getElementById('loading'),
    loadingText: document.getElementById('loadingText'),
    settingsBtn: document.getElementById('settingsBtn'),
    settingsModal: document.getElementById('settingsModal'),
    closeSettings: document.getElementById('closeSettings'),
    settingsHousehold: document.getElementById('settingsHousehold'),
    koStatus: document.getElementById('koStatus'),
    koUrlHint: document.getElementById('koUrlHint'),
    saveSettings: document.getElementById('saveSettings'),
    settingsTabs: document.querySelectorAll('.settings-tab'),
    settingsTabContents: document.querySelectorAll('.settings-tab-content'),
    setupWizard: document.getElementById('setupWizard'),
    setupKitchenowlToken: document.getElementById('setupKitchenowlToken'),
    setupAnthropicApiKey: document.getElementById('setupAnthropicApiKey'),
    skipSetup: document.getElementById('skipSetup'),
    completeSetup: document.getElementById('completeSetup'),
    themeToggle: document.getElementById('themeToggle'),
    toast: document.getElementById('toast'),
    // Stats elements
    statsSection: document.getElementById('statsSection'),
    statsGrid: document.getElementById('statsGrid'),
    statsDetails: document.getElementById('statsDetails'),
    toggleStats: document.getElementById('toggleStats'),
    badgeName: document.getElementById('badgeName'),
    badgeDesc: document.getElementById('badgeDesc'),
    statTotalRecipes: document.getElementById('statTotalRecipes'),
    statSuccessRate: document.getElementById('statSuccessRate'),
    statTimeSaved: document.getElementById('statTimeSaved'),
    statAiCalls: document.getElementById('statAiCalls'),
    statUrl: document.getElementById('statUrl'),
    statImage: document.getElementById('statImage'),
    statText: document.getElementById('statText'),
    statAvgConfidence: document.getElementById('statAvgConfidence'),
    statIngredients: document.getElementById('statIngredients'),
    statInstructions: document.getElementById('statInstructions'),
    statTopTags: document.getElementById('statTopTags'),
    statPages: document.getElementById('statPages'),
    statInk: document.getElementById('statInk'),
    statLastRecipe: document.getElementById('statLastRecipe'),
    nextBadgeSection: document.getElementById('nextBadgeSection'),
    nextBadgeName: document.getElementById('nextBadgeName'),
    nextBadgeProgress: document.getElementById('nextBadgeProgress'),
};

function showLoading(text = 'Processing...') {
    elements.loadingText.textContent = text;
    elements.loading.classList.remove('hidden');
}

function hideLoading() {
    elements.loading.classList.add('hidden');
}

function showToast(message, type = 'info') {
    elements.toast.textContent = message;
    elements.toast.className = `toast ${type}`;
    elements.toast.classList.remove('hidden');
    setTimeout(() => elements.toast.classList.add('hidden'), 4000);
}

async function apiRequest(endpoint, options = {}) {
    const response = await fetch(`/api${endpoint}`, {
        headers: { 'Content-Type': 'application/json', ...options.headers },
        ...options,
    });
    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(error.detail || 'Request failed');
    }
    return response.json();
}

async function checkAuthStatus() {
    try {
        const status = await apiRequest('/auth/status');
        isAuthenticated = status.authenticated;
        currentUser = status.user;
        updateAuthUI(status);
        return status;
    } catch (error) {
        updateAuthUI({ authenticated: false, oidc_configured: false, forward_auth_enabled: false });
        return { authenticated: false };
    }
}

function updateAuthUI(status) {
    if (status.authenticated) {
        elements.loginBtn.classList.add('hidden');
        elements.loginBanner.classList.add('hidden');
        elements.userInfo.classList.remove('hidden');
        elements.userName.textContent = status.user?.name || status.user?.email || 'User';
        elements.mainContent.classList.remove('hidden');
        if (status.auth_method === 'forward_auth') {
            elements.logoutBtn.classList.add('hidden');
        } else {
            elements.logoutBtn.classList.remove('hidden');
        }
    } else {
        elements.userInfo.classList.add('hidden');
        elements.mainContent.classList.add('hidden');
        if (status.oidc_configured) {
            elements.loginBtn.classList.remove('hidden');
            elements.loginBanner.classList.remove('hidden');
        } else if (status.forward_auth_enabled) {
            elements.loginBtn.classList.add('hidden');
            elements.loginBanner.classList.remove('hidden');
            elements.loginBannerBtn.textContent = 'Access via proxy required';
            elements.loginBannerBtn.disabled = true;
        } else {
            elements.loginBtn.classList.add('hidden');
            elements.loginBanner.classList.add('hidden');
        }
    }
}

function initAuth() {
    const handleLogin = () => { window.location.href = '/api/auth/login'; };
    elements.loginBtn.addEventListener('click', handleLogin);
    elements.loginBannerBtn.addEventListener('click', handleLogin);
    elements.logoutBtn.addEventListener('click', async () => {
        try {
            await apiRequest('/auth/logout', { method: 'POST' });
            isAuthenticated = false;
            currentUser = null;
            showToast('Logged out successfully');
            await checkAuthStatus();
        } catch (error) {
            showToast('Logout failed', 'error');
        }
    });
}

async function loadSecretsStatus() {
    try {
        secretsStatus = await apiRequest('/secrets/status');
        updateSecretsStatusUI();
        return secretsStatus;
    } catch (error) {
        return {};
    }
}

function updateSecretsStatusUI() {
    for (const [key, inputSuffix] of Object.entries(SECRET_KEY_MAP)) {
        const statusEl = document.getElementById(`status${inputSuffix}`);
        if (!statusEl) continue;
        const status = secretsStatus[key];
        const text = statusEl.querySelector('.status-text');
        if (status?.configured) {
            statusEl.classList.add('configured');
            statusEl.classList.remove('not-configured');
            text.textContent = 'Configured';
        } else {
            statusEl.classList.remove('configured');
            statusEl.classList.add('not-configured');
            text.textContent = 'Not configured';
        }
    }
}

async function saveSecret(key, value) {
    if (!value) {
        await apiRequest(`/secrets/${key}`, { method: 'DELETE' });
    } else {
        await apiRequest(`/secrets/${key}`, { method: 'POST', body: JSON.stringify({ value }) });
    }
}

function initSecrets() {
    document.querySelectorAll('.toggle-secret').forEach(btn => {
        btn.addEventListener('click', () => {
            const input = document.getElementById(btn.dataset.target);
            if (input) input.type = input.type === 'password' ? 'text' : 'password';
        });
    });
}

async function checkFirstRun() {
    if (!isAuthenticated) return;
    await loadSecretsStatus();
    if (!secretsStatus.kitchenowl_token?.configured) {
        elements.setupWizard.classList.remove('hidden');
    }
}

function initSetupWizard() {
    elements.skipSetup?.addEventListener('click', () => {
        elements.setupWizard.classList.add('hidden');
        localStorage.setItem('setupSkipped', 'true');
    });
    elements.completeSetup?.addEventListener('click', async () => {
        const token = elements.setupKitchenowlToken?.value?.trim();
        const anthropicKey = elements.setupAnthropicApiKey?.value?.trim();
        if (!token) { showToast('Please enter your KitchenOwl token', 'error'); return; }
        try {
            showLoading('Saving configuration...');
            await saveSecret('kitchenowl_token', token);
            if (anthropicKey) await saveSecret('anthropic_api_key', anthropicKey);
            elements.setupWizard.classList.add('hidden');
            showToast('Configuration saved successfully', 'success');
            await loadSecretsStatus();
            await checkKitchenOwlStatus();
        } catch (error) {
            showToast(`Failed to save configuration: ${error.message}`, 'error');
        } finally {
            hideLoading();
        }
    });
}

function initTabs() {
    elements.tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetId = tab.dataset.tab;
            elements.tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            elements.sections.forEach(s => s.classList.remove('active'));
            document.getElementById(`${targetId}-section`).classList.add('active');
            elements.previewSection.classList.add('hidden');
        });
    });
}

function initSettingsTabs() {
    elements.settingsTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetId = tab.dataset.settingsTab;
            elements.settingsTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            elements.settingsTabContents.forEach(c => c.classList.add('hidden'));
            document.getElementById(`settings-${targetId}`).classList.remove('hidden');
        });
    });
}

function initUrlImport() {
    elements.parseUrlBtn.addEventListener('click', async () => {
        const url = elements.recipeUrl.value.trim();
        if (!url) { showToast('Please enter a URL', 'error'); return; }
        try {
            showLoading('Fetching recipe...');
            currentSourceType = 'url';
            const recipe = await apiRequest('/parse/url', { method: 'POST', body: JSON.stringify({ url }) });
            showRecipePreview(recipe);
            showToast('Recipe imported successfully', 'success');
        } catch (error) {
            showToast(error.message, 'error');
        } finally {
            hideLoading();
        }
    });
    elements.recipeUrl.addEventListener('keypress', (e) => { if (e.key === 'Enter') elements.parseUrlBtn.click(); });
}

function initImageUpload() {
    elements.takePhotoBtn.addEventListener('click', () => elements.cameraInput.click());
    elements.cameraInput.addEventListener('change', (e) => { if (e.target.files.length > 0) handleImageFile(e.target.files[0]); });
    elements.dropZone.addEventListener('click', () => elements.imageInput.click());
    elements.imageInput.addEventListener('change', (e) => { if (e.target.files.length > 0) handleImageFile(e.target.files[0]); });
    elements.dropZone.addEventListener('dragover', (e) => { e.preventDefault(); elements.dropZone.classList.add('dragover'); });
    elements.dropZone.addEventListener('dragleave', () => elements.dropZone.classList.remove('dragover'));
    elements.dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        elements.dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) handleImageFile(e.dataTransfer.files[0]);
    });
    document.addEventListener('paste', (e) => {
        const imageSection = document.getElementById('image-section');
        if (!imageSection.classList.contains('active')) return;
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
            if (item.type.startsWith('image/')) {
                const file = item.getAsFile();
                if (file) { handleImageFile(file); break; }
            }
        }
    });
    elements.clearImage.addEventListener('click', () => clearImagePreview());
    elements.parseImageBtn.addEventListener('click', async () => {
        if (!selectedImage) { showToast('Please select an image first', 'error'); return; }
        try {
            showLoading('Extracting recipe from image...');
            currentSourceType = 'image';
            const formData = new FormData();
            formData.append('file', selectedImage);
            const response = await fetch('/api/parse/image', { method: 'POST', body: formData });
            if (!response.ok) {
                const error = await response.json().catch(() => ({ detail: 'Request failed' }));
                throw new Error(error.detail || 'Request failed');
            }
            const recipe = await response.json();
            showRecipePreview(recipe);
            showToast('Recipe extracted successfully', 'success');
        } catch (error) {
            showToast(error.message, 'error');
        } finally {
            hideLoading();
        }
    });
}

function handleImageFile(file) {
    if (!file.type.startsWith('image/')) { showToast('Please select an image file', 'error'); return; }
    selectedImage = file;
    const reader = new FileReader();
    reader.onload = (e) => {
        elements.previewImg.src = e.target.result;
        elements.imagePreview.classList.remove('hidden');
        elements.dropZone.classList.add('hidden');
        elements.parseImageBtn.disabled = false;
    };
    reader.readAsDataURL(file);
}

function clearImagePreview() {
    selectedImage = null;
    elements.previewImg.src = '';
    elements.imagePreview.classList.add('hidden');
    elements.dropZone.classList.remove('hidden');
    elements.parseImageBtn.disabled = true;
    elements.imageInput.value = '';
    elements.cameraInput.value = '';
}

function initTextPaste() {
    elements.parseTextBtn.addEventListener('click', async () => {
        const text = elements.recipeText.value.trim();
        if (!text) { showToast('Please paste some recipe text', 'error'); return; }
        try {
            showLoading('Parsing recipe text...');
            currentSourceType = 'text';
            const recipe = await apiRequest('/parse/text', { method: 'POST', body: JSON.stringify({ text }) });
            showRecipePreview(recipe);
            showToast('Recipe parsed successfully', 'success');
        } catch (error) {
            showToast(error.message, 'error');
        } finally {
            hideLoading();
        }
    });
}

function showRecipePreview(recipe) {
    currentRecipe = recipe;
    elements.editTitle.value = recipe.title || '';
    elements.editDescription.value = recipe.description || '';
    elements.editPrepTime.value = recipe.prep_time || '';
    elements.editCookTime.value = recipe.cook_time || '';
    elements.editTotalTime.value = recipe.total_time || '';
    elements.editServings.value = recipe.servings || '';
    elements.editTags.value = (recipe.tags || []).join(', ');
    elements.editSource.value = recipe.source_url || '';
    elements.editNotes.value = recipe.notes || '';
    elements.ingredientsList.innerHTML = '';
    if (recipe.ingredients && recipe.ingredients.length > 0) {
        recipe.ingredients.forEach(ing => addIngredientRow(ing.raw || formatIngredient(ing)));
    } else {
        addIngredientRow('');
    }
    elements.instructionsList.innerHTML = '';
    if (recipe.instructions && recipe.instructions.length > 0) {
        recipe.instructions.forEach(inst => addInstructionRow(inst));
    } else {
        addInstructionRow('');
    }
    elements.confidenceBadge.dataset.confidence = recipe.confidence;
    elements.confidenceBadge.querySelector('.confidence-value').textContent = recipe.confidence;
    if (recipe.fields_needing_review && recipe.fields_needing_review.length > 0) {
        elements.reviewFields.textContent = recipe.fields_needing_review.join(', ');
        elements.reviewWarning.classList.remove('hidden');
    } else {
        elements.reviewWarning.classList.add('hidden');
    }
    elements.previewSection.classList.remove('hidden');
    elements.previewSection.scrollIntoView({ behavior: 'smooth' });
}

function formatIngredient(ing) {
    const parts = [];
    if (ing.quantity) parts.push(ing.quantity);
    if (ing.unit) parts.push(ing.unit);
    parts.push(ing.name);
    if (ing.note) parts.push(`(${ing.note})`);
    return parts.join(' ');
}

function addIngredientRow(value = '') {
    const row = document.createElement('div');
    row.className = 'list-item';
    row.innerHTML = `<span class="drag-handle">&#8942;&#8942;</span><input type="text" value="${escapeHtml(value)}" placeholder="e.g., 2 cups flour"><button type="button" class="remove-btn" title="Remove">&times;</button>`;
    row.querySelector('.remove-btn').addEventListener('click', () => row.remove());
    elements.ingredientsList.appendChild(row);
}

function addInstructionRow(value = '') {
    const row = document.createElement('div');
    row.className = 'list-item';
    row.innerHTML = `<span class="drag-handle">&#8942;&#8942;</span><textarea placeholder="Enter instruction step...">${escapeHtml(value)}</textarea><button type="button" class="remove-btn" title="Remove">&times;</button>`;
    row.querySelector('.remove-btn').addEventListener('click', () => row.remove());
    elements.instructionsList.appendChild(row);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function initRecipeForm() {
    elements.addIngredient.addEventListener('click', () => addIngredientRow(''));
    elements.addInstruction.addEventListener('click', () => addInstructionRow(''));
    elements.cancelBtn.addEventListener('click', () => { elements.previewSection.classList.add('hidden'); currentRecipe = null; });
    elements.recipeForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!isAuthenticated) { showToast('Please log in to save recipes', 'error'); return; }
        if (!selectedHouseholdId) { showToast('Please select a household in Settings first', 'error'); elements.settingsModal.classList.remove('hidden'); return; }
        const ingredients = [];
        elements.ingredientsList.querySelectorAll('input').forEach(input => {
            const val = input.value.trim();
            if (val) ingredients.push({ name: val, raw: val });
        });
        const instructions = [];
        elements.instructionsList.querySelectorAll('textarea').forEach(textarea => {
            const val = textarea.value.trim();
            if (val) instructions.push(val);
        });
        const tags = elements.editTags.value.split(',').map(t => t.trim()).filter(t => t);
        const recipe = {
            title: elements.editTitle.value.trim(),
            description: elements.editDescription.value.trim() || null,
            prep_time: parseInt(elements.editPrepTime.value) || null,
            cook_time: parseInt(elements.editCookTime.value) || null,
            total_time: parseInt(elements.editTotalTime.value) || null,
            servings: elements.editServings.value.trim() || null,
            ingredients, instructions, tags,
            source_url: elements.editSource.value.trim() || null,
            notes: elements.editNotes.value.trim() || null,
            confidence: 'high', fields_needing_review: [],
            source_type: currentSourceType,
        };
        if (!recipe.title) { showToast('Recipe title is required', 'error'); return; }
        try {
            showLoading('Saving to KitchenOwl...');
            await apiRequest(`/kitchenowl/recipe/${selectedHouseholdId}`, { method: 'POST', body: JSON.stringify(recipe) });
            showToast('Recipe saved to KitchenOwl!', 'success');
            elements.previewSection.classList.add('hidden');
            elements.recipeUrl.value = '';
            elements.recipeText.value = '';
            clearImagePreview();
            // Refresh stats after save
            await loadStats();
        } catch (error) {
            showToast(error.message, 'error');
        } finally {
            hideLoading();
        }
    });
}

function initSettings() {
    elements.settingsBtn.addEventListener('click', async () => { elements.settingsModal.classList.remove('hidden'); await loadSettings(); });
    elements.closeSettings.addEventListener('click', () => elements.settingsModal.classList.add('hidden'));
    elements.settingsModal.addEventListener('click', (e) => { if (e.target === elements.settingsModal) elements.settingsModal.classList.add('hidden'); });
    elements.saveSettings.addEventListener('click', async () => {
        try {
            showLoading('Saving settings...');
            selectedHouseholdId = elements.settingsHousehold.value ? parseInt(elements.settingsHousehold.value) : null;
            localStorage.setItem('selectedHouseholdId', selectedHouseholdId || '');
            const secretInputs = [
                { key: 'kitchenowl_token', id: 'secretKitchenowlToken' },
                { key: 'anthropic_api_key', id: 'secretAnthropicApiKey' },
                { key: 'openai_api_key', id: 'secretOpenaiApiKey' },
            ];
            for (const { key, id } of secretInputs) {
                const input = document.getElementById(id);
                if (input && input.value.trim()) {
                    await saveSecret(key, input.value.trim());
                    input.value = '';
                }
            }
            await loadSecretsStatus();
            await checkKitchenOwlStatus();
            showToast('Settings saved', 'success');
            elements.settingsModal.classList.add('hidden');
        } catch (error) {
            showToast(`Failed to save settings: ${error.message}`, 'error');
        } finally {
            hideLoading();
        }
    });
    initSettingsTabs();
}

async function loadSettings() {
    try {
        const settings = await apiRequest('/settings');
        elements.koUrlHint.textContent = `Connected to: ${settings.kitchenowl_url}`;
        const savedHousehold = localStorage.getItem('selectedHouseholdId');
        if (savedHousehold) selectedHouseholdId = parseInt(savedHousehold);
        await loadSecretsStatus();
        await checkKitchenOwlStatus();
    } catch (error) {}
}

async function checkKitchenOwlStatus() {
    try {
        const status = await apiRequest('/kitchenowl/status');
        updateConnectionStatus(status);
        if (status.connected) await loadHouseholds();
    } catch (error) {
        updateConnectionStatus({ connected: false, error: error.message });
    }
}

function updateConnectionStatus(status) {
    elements.koStatus.className = 'status-indicator';
    if (status.connected) {
        elements.koStatus.classList.add('connected');
        elements.koStatus.querySelector('.status-text').textContent = 'Connected';
    } else {
        elements.koStatus.classList.add('error');
        elements.koStatus.querySelector('.status-text').textContent = status.error || 'Not connected';
    }
}

async function loadHouseholds() {
    try {
        households = await apiRequest('/kitchenowl/households');
        elements.settingsHousehold.innerHTML = '<option value="">Select household...</option>';
        households.forEach(h => {
            const option = document.createElement('option');
            option.value = h.id;
            option.textContent = h.name;
            if (h.id === selectedHouseholdId) option.selected = true;
            elements.settingsHousehold.appendChild(option);
        });
    } catch (error) {}
}

function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.dataset.theme = savedTheme;
    elements.themeToggle.addEventListener('click', () => {
        const current = document.documentElement.dataset.theme;
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.dataset.theme = next;
        localStorage.setItem('theme', next);
    });
}

// Stats functions
async function loadStats() {
    if (!isAuthenticated) return;
    try {
        const stats = await apiRequest('/stats');
        updateStatsUI(stats);
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

function updateStatsUI(stats) {
    // Main stats
    elements.statTotalRecipes.textContent = stats.total_recipes || 0;
    elements.statSuccessRate.textContent = `${stats.success_rate || 100}%`;
    elements.statAiCalls.textContent = stats.ai_api_calls || 0;

    // Time saved
    const hours = stats.time_saved_hours || 0;
    if (hours >= 1) {
        elements.statTimeSaved.textContent = `${hours}h`;
    } else {
        elements.statTimeSaved.textContent = `${stats.time_saved_minutes || 0}m`;
    }

    // Source breakdown
    elements.statUrl.textContent = stats.recipes_url || 0;
    elements.statImage.textContent = stats.recipes_image || 0;
    elements.statText.textContent = stats.recipes_text || 0;

    // Confidence
    if (stats.average_confidence) {
        elements.statAvgConfidence.textContent = `${stats.average_confidence}% (${stats.average_confidence_label})`;
    } else {
        elements.statAvgConfidence.textContent = '-';
    }

    // Totals
    elements.statIngredients.textContent = stats.total_ingredients || 0;
    elements.statInstructions.textContent = stats.total_instructions || 0;

    // Top tags
    if (stats.top_tags && stats.top_tags.length > 0) {
        elements.statTopTags.textContent = stats.top_tags.map(t => t.tag).join(', ');
    } else {
        elements.statTopTags.textContent = '-';
    }

    // Impact
    elements.statPages.textContent = stats.pages_saved || 0;
    elements.statInk.textContent = stats.ink_cartridges_saved || 0;

    // Last recipe
    if (stats.last_recipe_title) {
        const date = stats.last_recipe_at ? new Date(stats.last_recipe_at).toLocaleDateString() : '';
        elements.statLastRecipe.textContent = `${stats.last_recipe_title}${date ? ` (${date})` : ''}`;
    } else {
        elements.statLastRecipe.textContent = '-';
    }

    // Current badge
    if (stats.current_badge) {
        elements.badgeName.textContent = stats.current_badge.name;
        elements.badgeDesc.textContent = stats.current_badge.description;
    } else {
        elements.badgeName.textContent = 'Getting Started';
        elements.badgeDesc.textContent = 'Import your first recipe!';
    }

    // Next badge
    if (stats.next_badge) {
        elements.nextBadgeSection.classList.remove('hidden');
        elements.nextBadgeName.textContent = stats.next_badge.name;
        elements.nextBadgeProgress.textContent = `(${stats.next_badge.recipes_needed} more recipe${stats.next_badge.recipes_needed === 1 ? '' : 's'})`;
    } else {
        elements.nextBadgeSection.classList.add('hidden');
    }
}

function initStats() {
    // Load saved preference
    statsExpanded = localStorage.getItem('statsExpanded') === 'true';
    if (statsExpanded) {
        elements.statsDetails.classList.remove('hidden');
    }

    elements.toggleStats.addEventListener('click', () => {
        statsExpanded = !statsExpanded;
        elements.statsDetails.classList.toggle('hidden', !statsExpanded);
        localStorage.setItem('statsExpanded', statsExpanded);
    });
}

document.addEventListener('DOMContentLoaded', async () => {
    initTabs();
    initAuth();
    initSecrets();
    initSetupWizard();
    initUrlImport();
    initImageUpload();
    initTextPaste();
    initRecipeForm();
    initSettings();
    initTheme();
    initStats();
    const savedHousehold = localStorage.getItem('selectedHouseholdId');
    if (savedHousehold) selectedHouseholdId = parseInt(savedHousehold);
    const authStatus = await checkAuthStatus();
    if (authStatus.authenticated) {
        await loadStats();
        const skipped = localStorage.getItem('setupSkipped');
        if (!skipped) await checkFirstRun();
    }
});
