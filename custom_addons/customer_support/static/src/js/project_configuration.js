// static/src/js/project_configuration.js

document.addEventListener('DOMContentLoaded', function () {

    /* ================================
       AUTO-OPEN PROJECT TAB (URL PARAMS)
       ================================ */
    const urlParams = new URLSearchParams(window.location.search);
    const projectTab = document.getElementById('project-tab');

    if (projectTab && (urlParams.get('tab') === 'project' || urlParams.get('error') === '1')) {
        const tabTrigger = new bootstrap.Tab(projectTab);
        tabTrigger.show();
    }

    /* ================================
       FORM VALIDATION
       ================================ */
    const form = document.getElementById('projectConfigForm');

    if (form) {
        form.addEventListener('submit', function (event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            } else {
                // Loading state on submit button
                const submitBtn = form.querySelector('button[type="submit"]');
                if (submitBtn) {
                    submitBtn.classList.add('loading');
                    submitBtn.disabled = true;
                }
            }
            form.classList.add('was-validated');
        });

        /* ================================
           AUTO-UPPERCASE PROJECT KEY
           ================================ */
        const projectKeyInput = document.getElementById('project_key');
        if (projectKeyInput) {
            projectKeyInput.addEventListener('input', function () {
                this.value = this.value
                    .toUpperCase()
                    .replace(/[^A-Z0-9-]/g, '');
            });
        }

        /* ================================
           START / END DATE VALIDATION
           ================================ */
        const startDateInput = document.getElementById('start_date');
        const endDateInput = document.getElementById('end_date');

        if (startDateInput && endDateInput) {
            startDateInput.addEventListener('change', function () {
                endDateInput.setAttribute('min', this.value);
            });

            endDateInput.addEventListener('change', function () {
                if (startDateInput.value && this.value < startDateInput.value) {
                    this.setCustomValidity('End date must be after start date');
                } else {
                    this.setCustomValidity('');
                }
            });
        }

        /* ================================
           MILESTONE DATE VALIDATION
           ================================ */
        const alphaDate = document.getElementById('alpha_date');
        const betaDate = document.getElementById('beta_date');
        const finalDate = document.getElementById('final_date');

        if (alphaDate && betaDate) {
            alphaDate.addEventListener('change', function () {
                betaDate.setAttribute('min', this.value);
            });
        }

        if (betaDate && finalDate) {
            betaDate.addEventListener('change', function () {
                finalDate.setAttribute('min', this.value);
            });
        }
    }

    /* ================================
       AUTO-DISMISS ALERTS
       ================================ */
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(function (alert) {
        setTimeout(function () {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });

    /* ================================
       SCROLL TO FORM ON ERROR
       ================================ */
    if (urlParams.get('error') === '1' && form) {
        setTimeout(function () {
            form.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 300);
    }

    /* ================================
       TEXTAREA CHARACTER COUNTER (OPTIONAL)
       ================================ */
    const textareas = document.querySelectorAll('textarea');
    textareas.forEach(function (textarea) {
        textarea.addEventListener('input', function () {
            const maxLength = this.getAttribute('maxlength');
            if (maxLength) {
                const remaining = maxLength - this.value.length;
                // Hook for UI counter if needed
            }
        });
    });

});