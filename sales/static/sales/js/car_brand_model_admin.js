document.addEventListener('DOMContentLoaded', function () {
    const brandInput = document.getElementById('id_brand');
    const modelInput = document.getElementById('id_model_name');
    const modelDatalist = document.getElementById('car-model-options');
    const costCurrencySelect = document.getElementById('id_cost_currency');
    const currencySelect = document.getElementById('id_currency');

    if (costCurrencySelect && currencySelect) {
        const syncCurrency = function (source, target) {
            if (!source || !target) {
                return;
            }
            if (target.value !== source.value) {
                target.value = source.value;
            }
        };

        costCurrencySelect.addEventListener('change', function () {
            syncCurrency(costCurrencySelect, currencySelect);
        });

        currencySelect.addEventListener('change', function () {
            syncCurrency(currencySelect, costCurrencySelect);
        });

        if (costCurrencySelect.value && currencySelect.value !== costCurrencySelect.value) {
            currencySelect.value = costCurrencySelect.value;
        } else if (currencySelect.value && costCurrencySelect.value !== currencySelect.value) {
            costCurrencySelect.value = currencySelect.value;
        }
    }

    if (!brandInput || !modelInput || !modelDatalist) {
        return;
    }

    let brandModelMap = {};
    const rawMap = brandInput.dataset.brandModelMap || '{}';

    try {
        brandModelMap = JSON.parse(rawMap);
    } catch (error) {
        brandModelMap = {};
    }

    const normalizedMap = {};
    Object.keys(brandModelMap).forEach((brandName) => {
        normalizedMap[brandName.trim().toLowerCase()] = brandModelMap[brandName] || [];
    });

    function updateModelOptions() {
        const selectedBrand = (brandInput.value || '').trim().toLowerCase();
        const models = normalizedMap[selectedBrand] || [];

        while (modelDatalist.firstChild) {
            modelDatalist.removeChild(modelDatalist.firstChild);
        }

        models.forEach((modelName) => {
            const option = document.createElement('option');
            option.value = modelName;
            modelDatalist.appendChild(option);
        });
    }

    brandInput.addEventListener('input', updateModelOptions);
    brandInput.addEventListener('change', updateModelOptions);

    updateModelOptions();
});