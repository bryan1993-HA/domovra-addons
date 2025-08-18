// Recherche, modales de renommage et suppression — vanilla JS
(function () {
    const $ = (s, p = document) => p.querySelector(s);
    const $$ = (s, p = document) => Array.from(p.querySelectorAll(s));

    // Recherche live sur table + cartes
    const searchInput = $('#search-input');
    function applyFilter(q) {
        const norm = (t) => t.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();
        const query = norm(q || '');
        const rows = $$('#locations-body .location-row');
        const cards = $$('#locations-cards .location-card');

        [...rows, ...cards].forEach(el => {
            const name = norm(el.dataset.name || '');
            el.style.display = name.includes(query) ? '' : 'none';
        });
    }
    if (searchInput) {
        searchInput.addEventListener('input', (e) => applyFilter(e.target.value));
    }

    // Renommage
    const renameDialog = $('#rename-dialog');
    const renameForm = $('#rename-form');
    const renameInput = $('#rename-input');
    const renameHidden = $('#rename-hidden');
    const renameCancel = $('#rename-cancel');

    function openRename(el) {
        const name = el.dataset.name;
        const id = el.dataset.id;
        const url = el.dataset.renameUrl || `/locations/${id}/rename`;
        renameInput.value = name;
        renameHidden.value = id;
        renameForm.setAttribute('action', url);
        renameDialog.showModal();
        setTimeout(() => renameInput.focus(), 50);
    }

    $$('.btn-rename').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const host = e.target.closest('[data-id]');
            if (host) openRename(host);
        });
    });

    renameCancel?.addEventListener('click', () => renameDialog.close());

    // Suppression
    const deleteDialog = $('#delete-dialog');
    const deleteForm = $('#delete-form');
    const deleteName = $('#delete-name');
    const deleteHidden = $('#delete-hidden');
    const deleteCancel = $('#delete-cancel');

    function openDelete(el) {
        const name = el.dataset.name;
        const id = el.dataset.id;
        const url = el.dataset.deleteUrl || `/locations/${id}/delete`;
        deleteName.textContent = name;
        deleteHidden.value = id;
        deleteForm.setAttribute('action', url);
        deleteDialog.showModal();
    }

    $$('.btn-delete').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const host = e.target.closest('[data-id]');
            if (host) openDelete(host);
        });
    });

    deleteCancel?.addEventListener('click', () => deleteDialog.close());

    // Soumissions: petit “anti double-clic”
    [renameForm, deleteForm, $('#add-form')].forEach(form => {
        if (!form) return;
        form.addEventListener('submit', () => {
            const submit = form.querySelector('button[type="submit"]');
            if (submit) {
                submit.disabled = true;
                submit.textContent = submit.textContent + '…';
            }
        });
    });
})();
