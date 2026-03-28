function initializeCarAddEnhancements() {
    const addPageRoot = document.querySelector('.car-add-page');
    if (!addPageRoot) {
        return;
    }

    const defaultBackRow = document.querySelector('.page-back-row');
    if (defaultBackRow) {
        defaultBackRow.style.display = 'none';
    }

    const financeRows = [
        '.form-row.field-cost_price.field-cost_currency',
        '.form-row.field-selling_price.field-currency',
    ];

    financeRows.forEach((selector) => {
        const row = document.querySelector(selector);
        if (row) {
            row.classList.add('car-price-currency-row');
        }
    });

    setupElegantDropdown('id_brand', 'car-brand-options');
    setupElegantDropdown('id_model_name', 'car-model-options');

    setupUploadDropzone('id_image', 'صورة السيارة');
    setupUploadDropzone('id_contract_image', 'صورة العقد');
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeCarAddEnhancements);
} else {
    initializeCarAddEnhancements();
}

function setupElegantDropdown(inputId, datalistId) {
    const input = document.getElementById(inputId);
    const datalist = document.getElementById(datalistId);

    if (!input || !datalist || !input.parentNode) {
        return;
    }

    if (input.parentNode.classList && input.parentNode.classList.contains('car-elegant-select')) {
        return;
    }

    // Keep only the custom in-place dropdown panel and disable the browser-native datalist popup.
    input.removeAttribute('list');
    input.setAttribute('autocomplete', 'new-password');
    input.setAttribute('autocorrect', 'off');
    input.setAttribute('autocapitalize', 'off');
    input.setAttribute('spellcheck', 'false');

    const wrapper = document.createElement('div');
    wrapper.className = 'car-elegant-select';
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);

    const panel = document.createElement('div');
    panel.className = 'car-elegant-select-panel';
    wrapper.appendChild(panel);

    const closePanel = function () {
        panel.classList.remove('is-open');
    };

    const openPanel = function () {
        panel.classList.add('is-open');
    };

    const readOptions = function () {
        return Array.from(datalist.querySelectorAll('option'))
            .map((option) => (option.value || '').trim())
            .filter((value) => value.length > 0);
    };

    const renderOptions = function (query) {
        const allOptions = readOptions();
        const normalizedQuery = (query || '').trim().toLowerCase();
        const filteredOptions = normalizedQuery
            ? allOptions.filter((value) => value.toLowerCase().includes(normalizedQuery))
            : allOptions;

        panel.innerHTML = '';

        if (filteredOptions.length === 0) {
            const emptyItem = document.createElement('div');
            emptyItem.className = 'car-elegant-empty';
            emptyItem.textContent = 'لا توجد نتائج مطابقة';
            panel.appendChild(emptyItem);
            return;
        }

        filteredOptions.slice(0, 40).forEach((value) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'car-elegant-option';
            button.textContent = value;
            button.dataset.value = value;
            panel.appendChild(button);
        });
    };

    input.addEventListener('focus', function () {
        renderOptions(input.value);
        openPanel();
    });

    input.addEventListener('input', function () {
        renderOptions(input.value);
        openPanel();
    });

    input.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            closePanel();
        }
    });

    panel.addEventListener('mousedown', function (event) {
        const option = event.target.closest('.car-elegant-option');
        if (!option) {
            return;
        }

        event.preventDefault();
        input.value = option.dataset.value || '';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        closePanel();
    });

    document.addEventListener('click', function (event) {
        if (!wrapper.contains(event.target)) {
            closePanel();
        }
    });

    const observer = new MutationObserver(function () {
        if (panel.classList.contains('is-open')) {
            renderOptions(input.value);
        }
    });
    observer.observe(datalist, { childList: true, subtree: true });
}

function setupUploadDropzone(inputId, labelText) {
    const input = document.getElementById(inputId);

    if (!input || input.type !== 'file' || !input.parentNode) {
        return;
    }

    const dropzone = document.createElement('div');
    dropzone.className = 'car-upload-dropzone';

    const icon = document.createElement('span');
    icon.className = 'drop-icon';
    icon.innerHTML = '<i class="bi bi-camera" aria-hidden="true"></i>';

    const label = document.createElement('span');
    label.className = 'drop-label';
    label.textContent = `اسحب ${labelText} هنا أو اضغط للاختيار`;

    const hint = document.createElement('span');
    hint.className = 'drop-hint';
    hint.textContent = 'PNG / JPG / WEBP';

    const thumb = document.createElement('img');
    thumb.className = 'car-upload-thumb';
    thumb.alt = 'معاينة الصورة';
    thumb.style.display = 'none';

    input.parentNode.insertBefore(dropzone, input);
    dropzone.appendChild(icon);
    dropzone.appendChild(label);
    dropzone.appendChild(hint);
    dropzone.appendChild(thumb);
    dropzone.appendChild(input);

    const renderPreview = function (file) {
        if (!file || !file.type || !file.type.startsWith('image/')) {
            thumb.removeAttribute('src');
            thumb.style.display = 'none';
            return;
        }

        const reader = new FileReader();
        reader.onload = function (event) {
            thumb.src = event.target.result;
            thumb.style.display = 'block';
        };
        reader.readAsDataURL(file);
    };

    input.addEventListener('change', function () {
        renderPreview(input.files && input.files[0]);
    });

    ['dragenter', 'dragover'].forEach((eventName) => {
        dropzone.addEventListener(eventName, function (event) {
            event.preventDefault();
            event.stopPropagation();
            dropzone.classList.add('is-dragover');
        });
    });

    ['dragleave', 'dragend', 'drop'].forEach((eventName) => {
        dropzone.addEventListener(eventName, function (event) {
            event.preventDefault();
            event.stopPropagation();
            dropzone.classList.remove('is-dragover');
        });
    });

    dropzone.addEventListener('drop', function (event) {
        const droppedFiles = event.dataTransfer && event.dataTransfer.files;
        if (!droppedFiles || droppedFiles.length === 0) {
            return;
        }

        const file = droppedFiles[0];
        const transfer = new DataTransfer();
        transfer.items.add(file);
        input.files = transfer.files;
        input.dispatchEvent(new Event('change', { bubbles: true }));
    });
}