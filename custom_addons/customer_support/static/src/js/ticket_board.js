/* ============================================================
   TICKET BOARD — Full JS
   Features: columns CRUD, tasks CRUD, drag-and-drop,
             due dates, priority, internal comments,
             quick status change, sidebar tabs
   ============================================================ */

(function () {
    'use strict';

    const D            = window.BOARD_DATA || {};
    const csrf         = D.csrfToken || '';
    const ticketId     = D.ticketId;
    const currentUserId= D.currentUserId;
    const publicBoard  = D.publicBoard || false;
    const boardToken   = D.boardToken || null;
    const canEdit      = (!publicBoard) || (publicBoard && boardToken);
    let   projectMembers = D.projectMembers || [];
    let   customerConversation = D.customerConversation || [];

    // =========================================================
    // UTILITIES
    // =========================================================

    async function jsonRpc(url, params) {
        try {
            // include board_token automatically for public-token sessions
            const bodyParams = Object.assign({}, params || {});
            if (publicBoard && boardToken) {
                bodyParams.board_token = boardToken;
            }
            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
                body: JSON.stringify({ jsonrpc: '2.0', method: 'call', id: 1, params: bodyParams }),
            });
            const data = await res.json();
            // If Odoo returns a framework-level JSON-RPC error (not a controller result),
            // data.result is undefined and data.error is an object — extract a readable message.
            if (!data.result && data.error) {
                const msg = (data.error && data.error.data && data.error.data.message)
                    || (data.error && data.error.message)
                    || 'Server error';
                return { error: msg };
            }
            return data.result || data;
        } catch (e) {
            return { error: 'Network error: ' + e.message };
        }
    }

    function toast(msg, type = 'success') {
        const el = document.getElementById('tbToast');
        if (!el) return;
        el.textContent = msg;
        el.className = 'tb-toast show ' + type;
        setTimeout(() => { el.className = 'tb-toast'; }, 2800);
        // Refresh activity log after any successful action
        if (type !== 'error') setTimeout(() => {
            if (typeof refreshActivityLog === 'function') refreshActivityLog(true);
        }, 700);
    }

    function escHtml(str) {
        return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
            .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }
    function escAttr(str) { return escHtml(str); }

    function htmlToText(str) {
        const tmp = document.createElement('div');
        tmp.innerHTML = String(str || '');
        return (tmp.textContent || tmp.innerText || '').trim();
    }

    function openModal(id)  { const el = document.getElementById(id); if (el) el.classList.add('open'); }
    function closeModal(id) { const el = document.getElementById(id); if (el) el.classList.remove('open'); }

    document.querySelectorAll('.tb-modal-overlay').forEach(ov => {
        ov.addEventListener('click', e => { if (e.target === ov) ov.classList.remove('open'); });
    });

    // =========================================================
    // DUE DATE HELPER
    // =========================================================

    function dueDateClass(dateStr) {
        if (!dateStr) return '';
        const today = new Date(); today.setHours(0,0,0,0);
        const due   = new Date(dateStr);
        const diff  = Math.floor((due - today) / 86400000);
        if (diff < 0)  return 'overdue';
        if (diff <= 2) return 'due-soon';
        return 'on-time';
    }

    function formatDate(dateStr) {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    }

    // =========================================================
    // CONFIRM DELETE
    // =========================================================

    let _confirmResolve = null;
    function confirmDelete(msg) {
        return new Promise(resolve => {
            _confirmResolve = resolve;
            document.getElementById('confirmModalMsg').textContent = msg || 'Are you sure?';
            openModal('confirmModal');
        });
    }
    document.getElementById('confirmModalOk').addEventListener('click', () => {
        closeModal('confirmModal');
        if (_confirmResolve) _confirmResolve(true);
        _confirmResolve = null;
    });
    ['confirmModalClose','confirmModalCancel'].forEach(id => {
        document.getElementById(id).addEventListener('click', () => {
            closeModal('confirmModal');
            if (_confirmResolve) _confirmResolve(false);
            _confirmResolve = null;
        });
    });

    // =========================================================
    // SIDEBAR TABS
    // =========================================================

    document.querySelectorAll('.tb-stab').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            document.querySelectorAll('.tb-stab').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tb-stab-panel').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            const panel = document.getElementById('tab-' + tab);
            if (panel) panel.classList.add('active');
            // Auto-refresh log when switching to log tab
            if (tab === 'log') refreshActivityLog();
        });
    });

    // =========================================================
    // ACTIVITY LOG — live refresh
    // =========================================================

    const activityLogList  = document.getElementById('activityLogList');
    const logRefreshBtn    = document.getElementById('logRefreshBtn');

    const EVENT_ICONS = {
        created:              '🎫',
        status:               '🔄',
        assign:               '👤',
        sla:                  '⏰',
        board_col_add:        '➕',
        board_col_rename:     '✏️',
        board_col_delete:     '🗑️',
        board_task_add:       '📋',
        board_task_done:      '✅',
        board_task_undone:    '↩️',
        board_task_move:      '🔀',
        board_task_assign:    '👥',
        board_task_edit:      '✏️',
        board_task_delete:    '🗑️',
        board_checklist_add:  '☑️',
        board_checklist_done: '✔️',
        board_comment:        '💬',
        board_reply:          '📧',
        board_invite:         '📨',
    };

    let _lastLogTimestamp = null;

    function buildLogItem(entry, isNew) {
        const div = document.createElement('div');
        div.className = 'tb-log-item tb-log-' + (entry.event_type || 'created') + (isNew ? ' tb-log-new' : '');
        const icon = EVENT_ICONS[entry.event_type] || '•';
        let html = `<div class="tb-log-dot"></div>
            <div class="tb-log-content">
                <div class="tb-log-msg">${escHtml(icon + ' ' + entry.message)}</div>`;
        if (entry.detail) {
            html += `<div class="tb-log-detail">${escHtml(entry.detail)}</div>`;
        }
        html += `<div class="tb-log-time">${escHtml(entry.timestamp)}</div></div>`;
        div.innerHTML = html;
        return div;
    }

    async function refreshActivityLog(silent) {
        if (!activityLogList || (publicBoard && !canEdit)) return;
        if (logRefreshBtn) logRefreshBtn.classList.add('spinning');
        try {
            const res = await jsonRpc(
                `/customer_support/ticket/${ticketId}/activity_log`, {}
            );
            if (!res.success) return;
            const entries = res.entries || [];
            if (!entries.length) {
                activityLogList.innerHTML = '<div class="tb-empty-text">No activity recorded yet.</div>';
                return;
            }
            // Detect new entries (ones not already shown)
            const newestTs = entries[0] ? entries[0].timestamp : null;
            const isFirstLoad = _lastLogTimestamp === null;
            activityLogList.innerHTML = '';
            entries.forEach((entry, i) => {
                const isNew = !isFirstLoad && i === 0 && newestTs !== _lastLogTimestamp;
                activityLogList.appendChild(buildLogItem(entry, isNew));
            });
            _lastLogTimestamp = newestTs;
        } catch (e) { /* silent */ }
        finally {
            if (logRefreshBtn) logRefreshBtn.classList.remove('spinning');
        }
    }

    if (logRefreshBtn) {
        logRefreshBtn.addEventListener('click', () => refreshActivityLog(false));
    }

    // Auto-refresh log every 20s when log tab is visible
    setInterval(() => {
        const logTab = document.getElementById('tab-log');
        if (logTab && logTab.classList.contains('active')) refreshActivityLog(true);
    }, 20000);

    // Also refresh after every board action (hook into jsonRpc success)
    const _origJsonRpc = window.jsonRpc;
    // We wrap toast to also trigger a log refresh after any action
    const _origToast = window.toast;
    if (typeof toast === 'function') {
        window._logRefreshAfterAction = () => setTimeout(() => refreshActivityLog(true), 600);
    }

    // =========================================================
    // SIDEBAR TOGGLE
    // =========================================================

    const sidebarToggle = document.getElementById('sidebarToggle');
    const tbSidebar     = document.getElementById('tbSidebar');

    sidebarToggle.addEventListener('click', () => {
        tbSidebar.classList.toggle('collapsed');
        sidebarToggle.classList.toggle('active');
    });

    // =========================================================
    // QUICK STATUS CHANGE (focal/admin only)
    // =========================================================

    const statusToggle   = document.getElementById('statusToggle');
    const statusDropdown = document.getElementById('statusDropdown');
    const statusLabel    = document.getElementById('statusLabel');

    if (statusToggle && statusDropdown) {
        statusToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            statusDropdown.classList.toggle('open');
        });
        document.addEventListener('click', () => statusDropdown.classList.remove('open'));

        const STATUS_LABELS = {
            new:'New', assigned:'Assigned', in_progress:'In Progress',
            pending:'Pending', resolved:'Resolved', closed:'Closed'
        };

        const currentState = statusToggle.dataset.state;
        document.querySelectorAll('.tb-status-option').forEach(opt => {
            if (opt.dataset.state === currentState) opt.classList.add('active');

            opt.addEventListener('click', async () => {
                const newState = opt.dataset.state;
                statusDropdown.classList.remove('open');

                try {
                    const body = new URLSearchParams({ status: newState });
                    if (csrf) {
                        body.set('csrf_token', csrf);
                    }
                    const res = await fetch(
                        `/customer_support/ticket/${ticketId}/update_status`,
                        {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/x-www-form-urlencoded',
                                'Accept': 'application/json',
                                'X-CSRFToken': csrf,
                            },
                            body,
                        }
                    );
                    const data = await res.json();

                    if (data.success) {
                        const dot = statusToggle.querySelector('.tb-sdot');
                        if (dot) dot.className = `tb-sdot tb-sdot-${newState}`;
                        if (statusLabel) statusLabel.textContent = STATUS_LABELS[newState] || newState;
                        statusToggle.dataset.state = newState;
                        document.querySelectorAll('.tb-status-option').forEach(o =>
                            o.classList.toggle('active', o.dataset.state === newState)
                        );
                        toast('Status updated to ' + (STATUS_LABELS[newState] || newState));
                    } else {
                        toast(data.error || 'Failed to update status.', 'error');
                    }
                } catch (e) {
                    toast('Network error updating status.', 'error');
                }
            });
        });
    }

    // =========================================================
    // BOARD DOM HELPERS
    // =========================================================

    const boardArea = document.getElementById('boardArea');

    function removeEmptyState() {
        const el = document.getElementById('emptyBoard');
        if (el) el.remove();
    }

    function buildTaskEl(task) {
        const div = document.createElement('div');
        div.className = 'tb-task' + (task.is_done ? ' tb-task-done' : '');
        div.dataset.taskId = task.id;
        div.draggable = canEdit;

        const membersHtml = (task.members || []).map(m =>
            `<span class="tb-avatar" title="${escHtml(m.name)}" data-member-id="${escAttr(m.member_id || m.id)}">${escHtml(m.initials)}</span>`
        ).join('');

        let footerHtml = '';
        if ((task.task_priority && task.task_priority !== 'none') || task.due_date) {
            const priIcons = { urgent:'bi-exclamation-triangle-fill', high:'bi-arrow-up', medium:'bi-minus', low:'bi-arrow-down' };
            const priHtml = (task.task_priority && task.task_priority !== 'none')
                ? `<span class="tb-task-pri tb-tpri-${escHtml(task.task_priority)}">
                     <i class="bi ${priIcons[task.task_priority] || 'bi-minus'}"></i>
                     ${escHtml(task.task_priority.charAt(0).toUpperCase() + task.task_priority.slice(1))}
                   </span>` : '';
            const dueClass = dueDateClass(task.due_date);
            const dueHtml = task.due_date
                ? `<span class="tb-task-due ${dueClass}" data-due="${escAttr(task.due_date)}">
                     <i class="bi bi-calendar3"></i>${escHtml(formatDate(task.due_date))}
                   </span>` : '';
            footerHtml = `<div class="tb-task-footer">${priHtml}${dueHtml}</div>`;
        }

        // Checklist progress bar
        const checklist = task.checklist || [];
        const clDone  = checklist.filter(c => c.is_done).length;
        const clTotal = checklist.length;
        const clPct   = clTotal > 0 ? Math.round(clDone / clTotal * 100) : 0;
        const clHtml  = clTotal > 0
            ? `<div class="tb-task-checklist-bar">
                 <div class="tb-cl-progress"><div class="tb-cl-bar-fill" style="width:${clPct}%"></div></div>
                 <span class="tb-cl-count">${clDone}/${clTotal}</span>
               </div>` : '';

        const actionsHtml = canEdit ? `
            <div class="tb-task-actions">
                <button class="tb-task-edit-btn" data-task-id="${task.id}" title="Edit"><i class="bi bi-pencil"></i></button>
                <button class="tb-task-del-btn" data-task-id="${task.id}" title="Delete"><i class="bi bi-x-lg"></i></button>
            </div>` : '';

        div.innerHTML = `
            <div class="tb-task-header">
                <label class="tb-task-check-wrap">
                          <input type="checkbox" class="tb-task-check" data-task-id="${task.id}"
                              ${task.is_done ? 'checked' : ''} ${!canEdit ? 'disabled' : ''} />
                    <span class="tb-task-name">${escHtml(task.name)}</span>
                </label>
                ${actionsHtml}
            </div>
            ${task.description ? `<p class="tb-task-desc">${escHtml(task.description)}</p>` : ''}
            ${footerHtml}
            ${clHtml}
            ${membersHtml ? `<div class="tb-task-members">${membersHtml}</div>` : ''}
        `;

        if (canEdit) {
            div.querySelector('.tb-task-check').addEventListener('change', () => toggleTask(task.id, div));
            div.querySelector('.tb-task-edit-btn').addEventListener('click', () => openEditTask(task.id, div));
            div.querySelector('.tb-task-del-btn').addEventListener('click', async () => {
                const ok = await confirmDelete('Delete this task?');
                if (!ok) return;
                const res = await jsonRpc(`/customer_support/ticket/task/${task.id}/delete`, {});
                if (res.success) { div.remove(); updateColCount(div.closest('.tb-column')); toast('Task deleted.'); }
                else toast(res.error || 'Failed to delete task.', 'error');
            });
        }

        bindDragTask(div);
        return div;
    }

    function buildColumnEl(col) {
        const div = document.createElement('div');
        div.className = 'tb-column';
        div.dataset.colId = col.id;

        const headerActions = canEdit ? `
            <div class="tb-col-actions">
                <button class="tb-col-edit-btn" data-col-id="${col.id}"
                        data-col-name="${escAttr(col.name)}" data-col-color="${escAttr(col.color)}"
                        title="Rename"><i class="bi bi-pencil"></i></button>
                <button class="tb-col-del-btn" data-col-id="${col.id}"
                        title="Delete"><i class="bi bi-trash3"></i></button>
            </div>` : '';
        const dragHandle = canEdit ? `<i class="bi bi-grip-vertical tb-col-drag-handle" title="Drag to reorder"></i>` : '';
        const addTaskBtn = canEdit ? `<button class="tb-add-task-btn" data-col-id="${col.id}"><i class="bi bi-plus me-1"></i>Add Task</button>` : '';

        div.innerHTML = `
            <div class="tb-col-header" style="border-top: 3px solid ${escAttr(col.color)}">
                ${dragHandle}
                <div class="tb-col-title-wrap">
                    <span class="tb-col-title">${escHtml(col.name)}</span>
                    <span class="tb-col-count">0/0</span>
                </div>
                ${headerActions}
            </div>
            <div class="tb-task-list" data-col-id="${col.id}"></div>
            ${addTaskBtn}
        `;
        bindColumnButtons(div);
        bindColumnDrag(div);
        bindDragColumn(div);
        return div;
    }

    function bindColumnButtons(colEl) {
        const colId = colEl.dataset.colId;

        const editBtn = colEl.querySelector('.tb-col-edit-btn');
        if (editBtn) {
            editBtn.addEventListener('click', () => {
                document.getElementById('colModalColId').value  = colId;
                document.getElementById('colModalName').value   = editBtn.dataset.colName || '';
                const color = editBtn.dataset.colColor || '#6366f1';
                document.getElementById('colModalColor').value  = color;
                setSelectedColor(color);
                document.getElementById('colModalTitle').textContent = 'Edit Column';
                openModal('colModal');
            });
        }

        const delBtn = colEl.querySelector('.tb-col-del-btn');
        if (delBtn) {
            delBtn.addEventListener('click', async () => {
                const ok = await confirmDelete('Delete this column and all its tasks?');
                if (!ok) return;
                const res = await jsonRpc(`/customer_support/ticket/column/${colId}/delete`, {});
                if (res.success) { colEl.remove(); toast('Column deleted.'); }
                else toast(res.error || 'Failed to delete column.', 'error');
            });
        }

        const addBtn = colEl.querySelector('.tb-add-task-btn');
        if (addBtn) addBtn.addEventListener('click', () => openAddTask(colId));
    }

    function updateColCount(colEl) {
        if (!colEl) return;
        const tasks = colEl.querySelectorAll('.tb-task');
        const done  = colEl.querySelectorAll('.tb-task-done');
        const ctr   = colEl.querySelector('.tb-col-count');
        if (ctr) ctr.textContent = `${done.length}/${tasks.length}`;
    }

    // =========================================================
    // COLUMN DRAG-AND-DROP (reordering columns)
    // =========================================================

    let draggedColumn = null;

    function bindColumnDrag(colEl) {
        if (!canEdit) return;

        const handle = colEl.querySelector('.tb-col-drag-handle');
        if (!handle) return;

        // Only draggable when the user grabs the handle
        handle.addEventListener('mousedown', () => {
            colEl.setAttribute('draggable', 'true');
            const cleanup = () => {
                colEl.removeAttribute('draggable');
                document.removeEventListener('mouseup', cleanup);
            };
            document.addEventListener('mouseup', cleanup, { passive: true });
        });

        colEl.addEventListener('dragstart', e => {
            // Ignore if this is a task drag bubbling up
            if (e.target && e.target.closest && e.target.closest('.tb-task')) return;
            if (!colEl.getAttribute('draggable')) return;
            draggedColumn = colEl;
            setTimeout(() => colEl.classList.add('tb-col-dragging'), 0);
            e.dataTransfer.effectAllowed = 'move';
        });

        colEl.addEventListener('dragend', async () => {
            colEl.removeAttribute('draggable');
            colEl.classList.remove('tb-col-dragging');
            document.querySelectorAll('.tb-column').forEach(c => {
                c.classList.remove('tb-col-drag-before', 'tb-col-drag-after');
            });
            if (draggedColumn) {
                draggedColumn = null;
                await saveColumnOrder();
            }
        });

        colEl.addEventListener('dragover', e => {
            if (!draggedColumn || draggedColumn === colEl) return;
            // Only handle column-level drags (not task drags)
            if (draggedTask) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            const rect = colEl.getBoundingClientRect();
            document.querySelectorAll('.tb-column').forEach(c => {
                c.classList.remove('tb-col-drag-before', 'tb-col-drag-after');
            });
            if (e.clientX < rect.left + rect.width / 2) {
                boardArea.insertBefore(draggedColumn, colEl);
                colEl.classList.add('tb-col-drag-before');
            } else {
                boardArea.insertBefore(draggedColumn, colEl.nextSibling);
                colEl.classList.add('tb-col-drag-after');
            }
        });
    }

    async function saveColumnOrder() {
        const colIds = [...boardArea.querySelectorAll('.tb-column')]
            .map(c => parseInt(c.dataset.colId))
            .filter(id => !isNaN(id));
        try {
            await jsonRpc(`/customer_support/ticket/${ticketId}/columns/reorder`, { column_ids: colIds });
        } catch (e) { /* silent — DOM already reordered */ }
    }

    // =========================================================
    // DRAG AND DROP (task drag between columns)
    // =========================================================

    let draggedTask = null;

    function bindDragTask(taskEl) {
        taskEl.addEventListener('dragstart', e => {
            draggedTask = taskEl;
            taskEl.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
        });
        taskEl.addEventListener('dragend', () => {
            taskEl.classList.remove('dragging');
            draggedTask = null;
            document.querySelectorAll('.tb-task-list').forEach(l => l.classList.remove('drag-over-list'));
            document.querySelectorAll('.tb-column').forEach(c => c.classList.remove('drag-over'));
        });
    }

    function bindDragColumn(colEl) {
        const taskList = colEl.querySelector('.tb-task-list');
        if (!taskList) return;

        taskList.addEventListener('dragover', e => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            colEl.classList.add('drag-over');
            taskList.classList.add('drag-over-list');
        });

        taskList.addEventListener('dragleave', e => {
            if (!taskList.contains(e.relatedTarget)) {
                colEl.classList.remove('drag-over');
                taskList.classList.remove('drag-over-list');
            }
        });

        taskList.addEventListener('drop', async e => {
            e.preventDefault();
            colEl.classList.remove('drag-over');
            taskList.classList.remove('drag-over-list');
            if (!draggedTask) return;

            const sourceList = draggedTask.closest('.tb-task-list');
            const targetList = taskList;
            const newColId   = colEl.dataset.colId;
            const taskId     = draggedTask.dataset.taskId;

            // Insert before the element under the cursor
            const afterEl = getDragAfterElement(targetList, e.clientY);
            if (afterEl) targetList.insertBefore(draggedTask, afterEl);
            else          targetList.appendChild(draggedTask);

            // Update counts for both columns
            if (sourceList) updateColCount(sourceList.closest('.tb-column'));
            updateColCount(colEl);

            // Only call API if column changed
            const originalColId = sourceList ? sourceList.dataset.colId : null;
            if (String(originalColId) !== String(newColId)) {
                const res = await jsonRpc(
                    `/customer_support/ticket/task/${taskId}/move`,
                    { column_id: parseInt(newColId) }
                );
                if (!res.success) {
                    toast(res.error || 'Move failed.', 'error');
                    // revert
                    if (sourceList) sourceList.appendChild(draggedTask);
                    updateColCount(colEl);
                    if (sourceList) updateColCount(sourceList.closest('.tb-column'));
                }
            }
        });
    }

    function getDragAfterElement(container, y) {
        const draggableEls = [...container.querySelectorAll('.tb-task:not(.dragging)')];
        return draggableEls.reduce((closest, el) => {
            const box = el.getBoundingClientRect();
            const offset = y - box.top - box.height / 2;
            if (offset < 0 && offset > closest.offset) return { offset, element: el };
            return closest;
        }, { offset: Number.NEGATIVE_INFINITY }).element;
    }

    // Bind drag to server-rendered tasks and columns
    document.querySelectorAll('.tb-task').forEach(t => bindDragTask(t));
    document.querySelectorAll('.tb-column').forEach(c => {
        bindColumnButtons(c);
        bindColumnDrag(c);
        bindDragColumn(c);

        c.querySelectorAll('.tb-task').forEach(taskEl => {
            const taskId = taskEl.dataset.taskId;

            const chk = taskEl.querySelector('.tb-task-check');
            if (chk) chk.addEventListener('change', () => toggleTask(taskId, taskEl));

            const edit = taskEl.querySelector('.tb-task-edit-btn');
            if (edit) edit.addEventListener('click', () => openEditTask(taskId, taskEl));

            const del = taskEl.querySelector('.tb-task-del-btn');
            if (del) del.addEventListener('click', async () => {
                const ok = await confirmDelete('Delete this task?');
                if (!ok) return;
                const res = await jsonRpc(`/customer_support/ticket/task/${taskId}/delete`, {});
                if (res.success) { taskEl.remove(); updateColCount(c); toast('Task deleted.'); }
                else toast(res.error || 'Failed to delete.', 'error');
            });
        });

        // Colour due-date labels on load
        c.querySelectorAll('.tb-task-due[data-due]').forEach(el => {
            const cls = dueDateClass(el.dataset.due);
            if (cls) el.classList.add(cls);
        });

        updateColCount(c);
    });

    // =========================================================
    // STATUS REMINDER NUDGE
    // =========================================================

    const statusNudge    = document.getElementById('statusNudge');
    const nudgeDismiss   = document.getElementById('nudgeDismiss');
    const nudgeUpdateBtn = document.getElementById('nudgeUpdateBtn');

    if (statusNudge) {
        // Add pulsing ring to status button to draw attention
        if (statusToggle) statusToggle.classList.add('tb-nudge-pulse');

        // Dismiss button
        if (nudgeDismiss) {
            nudgeDismiss.addEventListener('click', () => {
                statusNudge.style.transition = 'opacity 0.3s, transform 0.3s';
                statusNudge.style.opacity = '0';
                statusNudge.style.transform = 'translateY(-8px)';
                setTimeout(() => { statusNudge.style.display = 'none'; }, 320);
                if (statusToggle) statusToggle.classList.remove('tb-nudge-pulse');
            });
        }

        // "Update Status" button — scrolls to and opens the status dropdown
        if (nudgeUpdateBtn && statusToggle) {
            nudgeUpdateBtn.addEventListener('click', () => {
                statusToggle.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                setTimeout(() => {
                    statusDropdown.classList.add('open');
                    statusToggle.focus();
                }, 200);
            });
        }

        // Auto-hide nudge once status is changed
        if (statusDropdown) {
            statusDropdown.querySelectorAll('.tb-status-option').forEach(opt => {
                opt.addEventListener('click', () => {
                    if (statusNudge) statusNudge.style.display = 'none';
                    if (statusToggle) statusToggle.classList.remove('tb-nudge-pulse');
                });
            });
        }
    }

    // ALL-DONE BANNER (focal/admin only)
    // =========================================================

    const allDoneBanner      = document.getElementById('allDoneBanner');
    const allDoneResolveBtn  = document.getElementById('allDoneResolveBtn');
    const allDoneDismiss     = document.getElementById('allDoneDismiss');
    let   _bannerDismissed   = false;

    function checkAllDone() {
        if (!allDoneBanner || _bannerDismissed) return;
        const all  = boardArea.querySelectorAll('.tb-task').length;
        const done = boardArea.querySelectorAll('.tb-task-done').length;
        const show = all > 0 && all === done;
        allDoneBanner.style.display = show ? '' : 'none';
    }

    if (allDoneDismiss) {
        allDoneDismiss.addEventListener('click', () => {
            _bannerDismissed = true;
            allDoneBanner.style.display = 'none';
        });
    }

    if (allDoneResolveBtn) {
        allDoneResolveBtn.addEventListener('click', async () => {
            try {
                const body = new URLSearchParams({ status: 'resolved' });
                if (csrf) {
                    body.set('csrf_token', csrf);
                }
                const res = await fetch(
                    `/customer_support/ticket/${ticketId}/update_status`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded',
                            'Accept': 'application/json',
                            'X-CSRFToken': csrf,
                        },
                        body,
                    }
                );
                const data = await res.json();
                if (data.success) {
                    allDoneBanner.style.display = 'none';
                    if (statusToggle) {
                        const dot = statusToggle.querySelector('.tb-sdot');
                        if (dot) dot.className = 'tb-sdot tb-sdot-resolved';
                        if (statusLabel) statusLabel.textContent = 'Resolved';
                        statusToggle.dataset.state = 'resolved';
                        document.querySelectorAll('.tb-status-option').forEach(o =>
                            o.classList.toggle('active', o.dataset.state === 'resolved')
                        );
                    }
                    toast('Ticket marked as Resolved!');
                } else {
                    toast(data.error || 'Failed to update status.', 'error');
                }
            } catch (e) {
                toast('Network error.', 'error');
            }
        });
    }

    // Run on page load in case the board is already 100% done
    checkAllDone();

    // =========================================================
    // TASK TOGGLE
    // =========================================================

    async function toggleTask(taskId, taskEl) {
        const res = await jsonRpc(`/customer_support/ticket/task/${taskId}/toggle`, {});
        if (res.success) {
            taskEl.classList.toggle('tb-task-done', res.is_done);
            const chk = taskEl.querySelector('.tb-task-check');
            if (chk) chk.checked = res.is_done;
            updateColCount(taskEl.closest('.tb-column'));
            _bannerDismissed = false;   // re-enable banner check after every toggle
            checkAllDone();
        } else {
            toast(res.error || 'Toggle failed.', 'error');
        }
    }

    // =========================================================
    // COLUMN MODAL
    // =========================================================

    function setSelectedColor(color) {
        document.querySelectorAll('.tb-color-dot').forEach(d =>
            d.classList.toggle('selected', d.dataset.color === color)
        );
        document.getElementById('colModalColor').value = color;
    }
    document.querySelectorAll('.tb-color-dot').forEach(d =>
        d.addEventListener('click', () => setSelectedColor(d.dataset.color))
    );
    setSelectedColor('#6366f1');

    function openAddColumnModal() {
        document.getElementById('colModalColId').value = '';
        document.getElementById('colModalName').value  = '';
        document.getElementById('colModalTitle').textContent = 'Add Column';
        setSelectedColor('#6366f1');
        openModal('colModal');
    }

    const addColumnBtn = document.getElementById('addColumnBtn');
    if (addColumnBtn) addColumnBtn.addEventListener('click', () => openAddColumnModal());
    document.getElementById('colModalClose').addEventListener('click',  () => closeModal('colModal'));
    document.getElementById('colModalCancel').addEventListener('click', () => closeModal('colModal'));

    document.getElementById('colModalSave').addEventListener('click', async () => {
        const colId = document.getElementById('colModalColId').value;
        const name  = document.getElementById('colModalName').value.trim();
        const color = document.getElementById('colModalColor').value || '#6366f1';
        if (!name) { toast('Column name is required.', 'error'); return; }

        if (colId) {
            const res = await jsonRpc(`/customer_support/ticket/column/${colId}/rename`, { name, color });
            if (res.success) {
                const colEl = boardArea.querySelector(`[data-col-id="${colId}"]`);
                if (colEl) {
                    colEl.querySelector('.tb-col-title').textContent = res.name;
                    colEl.querySelector('.tb-col-header').style.borderTopColor = res.color;
                    const eb = colEl.querySelector('.tb-col-edit-btn');
                    if (eb) { eb.dataset.colName = res.name; eb.dataset.colColor = res.color; }
                }
                closeModal('colModal'); toast('Column updated.');
            } else toast(res.error || 'Failed to rename.', 'error');
        } else {
            const res = await jsonRpc(`/customer_support/ticket/${ticketId}/board/column/add`, { name, color });
            if (res.success) {
                removeEmptyState();
                const colEl = buildColumnEl({ id: res.column_id, name: res.name, color: res.color });
                const ghost = document.getElementById('addListGhost');
                if (ghost) boardArea.insertBefore(colEl, ghost);
                else boardArea.appendChild(colEl);
                closeModal('colModal'); toast('Column added.');
            } else toast(res.error || 'Failed to add column.', 'error');
        }
    });

    // =========================================================
    // TASK MODAL
    // =========================================================

    let _taskMode = 'add';

    function buildMemberPicker(selectedIds = []) {
        const picker = document.getElementById('memberPicker');
        picker.innerHTML = '';
        const assignable = projectMembers;
        if (!assignable.length) {
            picker.innerHTML = '<div class="tb-member-empty">No team members configured.</div>';
            return;
        }
        assignable.forEach(m => {
            const memberId = parseInt(m.member_id || m.id);
            const isSel = selectedIds.includes(memberId);
            const opt = document.createElement('label');
            opt.className = 'tb-member-option' + (isSel ? ' selected' : '');
            opt.innerHTML = `
                <input type="checkbox" value="${memberId}" ${isSel ? 'checked' : ''} />
                <div class="tb-member-av">${escHtml(m.initials)}</div>
                <span class="tb-member-opt-name">${escHtml(m.name)}</span>
                <span class="tb-member-opt-role">${escHtml(m.role)}</span>
            `;
            opt.querySelector('input').addEventListener('change', function () {
                opt.classList.toggle('selected', this.checked);
            });
            picker.appendChild(opt);
        });
    }

    function getSelectedMemberIds() {
        return Array.from(document.querySelectorAll('#memberPicker input[type="checkbox"]:checked'))
            .map(cb => parseInt(cb.value))
            .filter(id => Number.isInteger(id) && id > 0);
    }

    function openAddTask(colId) {
        _taskMode = 'add';
        document.getElementById('taskModalColId').value    = colId;
        document.getElementById('taskModalTaskId').value   = '';
        document.getElementById('taskModalName').value     = '';
        document.getElementById('taskModalDesc').value     = '';
        document.getElementById('taskModalDue').value      = '';
        document.getElementById('taskModalPriority').value = 'none';
        document.getElementById('taskModalTitle').textContent = 'Add Task';
        const clGroup = document.getElementById('checklistGroup');
        const notesGroup = document.getElementById('taskNotesGroup');
        if (clGroup) clGroup.style.display = 'none';
        if (notesGroup) notesGroup.style.display = 'none';
        buildMemberPicker([]);
        openModal('taskModal');
    }

    async function openEditTask(taskId, taskEl) {
        _taskMode = 'edit';
        document.getElementById('taskModalTaskId').value = taskId;
        document.getElementById('taskModalColId').value  = '';
        document.getElementById('taskModalTitle').textContent = 'Edit Task';

        const nameEl = taskEl.querySelector('.tb-task-name');
        const descEl = taskEl.querySelector('.tb-task-desc');
        const dueEl  = taskEl.querySelector('.tb-task-due');
        const priEl  = taskEl.querySelector('.tb-task-pri');

        document.getElementById('taskModalName').value = nameEl ? nameEl.textContent.trim() : '';
        document.getElementById('taskModalDesc').value = descEl ? descEl.textContent.trim() : '';
        document.getElementById('taskModalDue').value  = dueEl  ? (dueEl.dataset.due || '') : '';

        let priority = 'none';
        if (priEl) {
            const cls = [...priEl.classList].find(c => c.startsWith('tb-tpri-'));
            if (cls) priority = cls.replace('tb-tpri-', '');
        }
        document.getElementById('taskModalPriority').value = priority;

        const avatars = taskEl.querySelectorAll('.tb-avatar');
        const currentIds = Array.from(avatars)
            .map(a => parseInt(a.dataset.memberId || '0'))
            .filter(id => Number.isInteger(id) && id > 0);
        buildMemberPicker(currentIds);

        // Show note and checklist sections in edit mode (checklist focal-only)
        const notesGroup = document.getElementById('taskNotesGroup');
        if (notesGroup) notesGroup.style.display = '';
        const clGroup = document.getElementById('checklistGroup');
        if (clGroup) clGroup.style.display = publicBoard ? 'none' : '';
        // Seed cache from BOARD_DATA if not already present
        if (!_checklistCache[taskId]) {
            const colData = (window.BOARD_DATA.boardColumns || []);
            for (const col of colData) {
                const t = (col.tasks || []).find(t => t.id === parseInt(taskId));
                if (t && t.checklist) { _checklistCache[taskId] = t.checklist; break; }
            }
        }
        if (!_taskNotesCache[taskId]) {
            const colData = (window.BOARD_DATA.boardColumns || []);
            for (const col of colData) {
                const t = (col.tasks || []).find(t => t.id === parseInt(taskId));
                if (t && t.notes) { _taskNotesCache[taskId] = t.notes; break; }
            }
        }
        buildChecklistSection(taskId);
        buildTaskNotesSection(taskId);

        openModal('taskModal');
    }

    // =========================================================
    // CHECKLIST
    // =========================================================

    // Store checklist data keyed by taskId (populated from BOARD_DATA on load)
    const _checklistCache = {};
    const _taskNotesCache = {};

    // Seed cache from initial board render
    document.querySelectorAll('.tb-task[data-task-id]').forEach(el => {
        // Checklist data is embedded by JS buildTaskEl — nothing to seed here on load
        // Cache is populated when openEditTask is called
    });

    function buildChecklistSection(taskId) {
        let container = document.getElementById('checklistSection');
        if (!container) return;
        if (publicBoard) {
            container.innerHTML = '<div class="tb-empty-text">Checklist can only be updated by focal users.</div>';
            return;
        }

        const items = _checklistCache[taskId] || [];
        container.innerHTML = '';

        // Items list
        const list = document.createElement('div');
        list.className = 'tb-cl-modal-list';
        list.id = 'checklistItems_' + taskId;

        items.forEach(item => {
            list.appendChild(buildChecklistItemEl(taskId, item));
        });
        container.appendChild(list);

        // Add input row
        const addRow = document.createElement('div');
        addRow.className = 'tb-cl-add-row';
        addRow.innerHTML = `
            <input type="text" class="tb-form-input tb-cl-new-input" id="clNewInput_${taskId}"
                   placeholder="Add an item…" maxlength="200" />
            <button class="tb-btn-secondary tb-cl-add-btn" id="clAddBtn_${taskId}">Add</button>
        `;
        container.appendChild(addRow);

        // Bind add
        const clInput = container.querySelector(`#clNewInput_${taskId}`);
        const clBtn   = container.querySelector(`#clAddBtn_${taskId}`);

        async function addItem() {
            const name = (clInput.value || '').trim();
            if (!name) return;
            clBtn.disabled = true;
            const res = await jsonRpc(`/customer_support/ticket/task/${taskId}/checklist/add`, { name });
            clBtn.disabled = false;
            if (res.success) {
                if (!_checklistCache[taskId]) _checklistCache[taskId] = [];
                _checklistCache[taskId].push(res.item);
                const listEl = document.getElementById('checklistItems_' + taskId);
                if (listEl) listEl.appendChild(buildChecklistItemEl(taskId, res.item));
                clInput.value = '';
                updateTaskCardChecklist(taskId);
            } else toast(res.error || 'Failed to add item.', 'error');
        }

        clBtn.addEventListener('click', addItem);
        clInput.addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); addItem(); }
        });
    }

    function buildTaskNotesSection(taskId) {
        let container = document.getElementById('taskNotesSection');
        if (!container) return;

        const items = _taskNotesCache[taskId] || [];
        container.innerHTML = '';

        const list = document.createElement('div');
        list.className = 'tb-note-modal-list';
        list.id = 'taskNotesItems_' + taskId;

        items.forEach(note => {
            const row = document.createElement('div');
            row.className = 'tb-note-item';
            row.innerHTML = `
                <div class="tb-note-meta"><strong>${escHtml(note.author || 'Board Member')}</strong><span>${escHtml(note.created || '')}</span></div>
                <div class="tb-note-msg">${escHtml(note.message || '')}</div>
            `;
            list.appendChild(row);
        });
        container.appendChild(list);

        const addRow = document.createElement('div');
        addRow.className = 'tb-note-add-row';
        addRow.innerHTML = `
            <textarea class="tb-form-textarea tb-note-new-input" id="noteNewInput_${taskId}" rows="2" placeholder="Write a resolving note..."></textarea>
            <button class="tb-btn-secondary tb-note-add-btn" id="noteAddBtn_${taskId}">Add Note</button>
        `;
        container.appendChild(addRow);

        const noteInput = container.querySelector(`#noteNewInput_${taskId}`);
        const noteBtn = container.querySelector(`#noteAddBtn_${taskId}`);

        async function addNote() {
            const message = (noteInput.value || '').trim();
            if (!message) return;
            noteBtn.disabled = true;
            const res = await jsonRpc(`/customer_support/ticket/task/${taskId}/note/add`, { message, author_name: '' });
            noteBtn.disabled = false;
            if (res.success) {
                if (!_taskNotesCache[taskId]) _taskNotesCache[taskId] = [];
                _taskNotesCache[taskId].push(res.note);
                const listEl = document.getElementById('taskNotesItems_' + taskId);
                if (listEl) {
                    const row = document.createElement('div');
                    row.className = 'tb-note-item';
                    row.innerHTML = `
                        <div class="tb-note-meta"><strong>${escHtml(res.note.author || 'Board Member')}</strong><span>${escHtml(res.note.created || '')}</span></div>
                        <div class="tb-note-msg">${escHtml(res.note.message || '')}</div>
                    `;
                    listEl.appendChild(row);
                }
                noteInput.value = '';
                toast('Note added.');
            } else toast(res.error || 'Failed to add note.', 'error');
        }

        noteBtn.addEventListener('click', addNote);
        noteInput.addEventListener('keydown', e => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                addNote();
            }
        });
    }

    function buildChecklistItemEl(taskId, item) {
        const row = document.createElement('div');
        row.className = 'tb-cl-item' + (item.is_done ? ' tb-cl-done' : '');
        row.dataset.clId = item.id;
        row.innerHTML = `
            <label class="tb-cl-label">
                <input type="checkbox" class="tb-cl-check" ${item.is_done ? 'checked' : ''} />
                <span class="tb-cl-name">${escHtml(item.name)}</span>
            </label>
            <button class="tb-cl-del" title="Remove"><i class="bi bi-x"></i></button>
        `;
        row.querySelector('.tb-cl-check').addEventListener('change', async () => {
            const res = await jsonRpc(`/customer_support/ticket/task/checklist/${item.id}/toggle`, {});
            if (res.success) {
                item.is_done = res.is_done;
                row.classList.toggle('tb-cl-done', res.is_done);
                updateTaskCardChecklist(taskId);
            }
        });
        row.querySelector('.tb-cl-del').addEventListener('click', async () => {
            const res = await jsonRpc(`/customer_support/ticket/task/checklist/${item.id}/delete`, {});
            if (res.success) {
                row.remove();
                if (_checklistCache[taskId]) {
                    _checklistCache[taskId] = _checklistCache[taskId].filter(c => c.id !== item.id);
                }
                updateTaskCardChecklist(taskId);
            }
        });
        return row;
    }

    function updateTaskCardChecklist(taskId) {
        const items = _checklistCache[taskId] || [];
        const done  = items.filter(c => c.is_done).length;
        const total = items.length;
        const pct   = total > 0 ? Math.round(done / total * 100) : 0;

        const taskEl = boardArea.querySelector(`.tb-task[data-task-id="${taskId}"]`);
        if (!taskEl) return;

        let barWrap = taskEl.querySelector('.tb-task-checklist-bar');
        if (total === 0) {
            if (barWrap) barWrap.remove();
            return;
        }
        if (!barWrap) {
            barWrap = document.createElement('div');
            barWrap.className = 'tb-task-checklist-bar';
            // Insert before members div or at end
            const membersDiv = taskEl.querySelector('.tb-task-members');
            if (membersDiv) taskEl.insertBefore(barWrap, membersDiv);
            else taskEl.appendChild(barWrap);
        }
        barWrap.innerHTML = `
            <div class="tb-cl-progress"><div class="tb-cl-bar-fill" style="width:${pct}%"></div></div>
            <span class="tb-cl-count">${done}/${total}</span>
        `;
    }

    // Seed checklist cache from BOARD_DATA task elements on initial load
    // We can't do this without BOARD_DATA having full task objects, so we use a different approach:
    // When openEditTask is called, we seed from the task card's data attribute if available.
    // Instead, hydrate from board columns that were passed via window.BOARD_DATA if present.
    if (window.BOARD_DATA && window.BOARD_DATA.boardColumns) {
        window.BOARD_DATA.boardColumns.forEach(col => {
            (col.tasks || []).forEach(task => {
                if (task.checklist && task.checklist.length) {
                    _checklistCache[task.id] = task.checklist;
                }
                if (task.notes && task.notes.length) {
                    _taskNotesCache[task.id] = task.notes;
                }
            });
        });
    }

    document.getElementById('taskModalClose').addEventListener('click',  () => closeModal('taskModal'));
    document.getElementById('taskModalCancel').addEventListener('click', () => closeModal('taskModal'));

    document.getElementById('taskModalSave').addEventListener('click', async () => {
        const name     = document.getElementById('taskModalName').value.trim();
        const desc     = document.getElementById('taskModalDesc').value.trim();
        const due      = document.getElementById('taskModalDue').value || null;
        const priority = document.getElementById('taskModalPriority').value || 'none';
        const members  = getSelectedMemberIds();

        if (!name) { toast('Task title is required.', 'error'); return; }

        const saveBtn = document.getElementById('taskModalSave');
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Saving…';

        try {
            if (_taskMode === 'add') {
                const colId = document.getElementById('taskModalColId').value;
                const res = await jsonRpc(
                    `/customer_support/ticket/column/${colId}/task/add`,
                    { name, description: desc, member_ids: members, due_date: due, task_priority: priority }
                );
                if (res.success) {
                    const colEl = boardArea.querySelector(`.tb-column[data-col-id="${colId}"]`);
                    if (colEl) {
                        colEl.querySelector('.tb-task-list').appendChild(buildTaskEl(res.task));
                        updateColCount(colEl);
                    }
                    closeModal('taskModal'); toast('Task added.');
                } else toast(res.error || 'Failed to add task.', 'error');

            } else {
                const taskId = document.getElementById('taskModalTaskId').value;
                const res = await jsonRpc(
                    `/customer_support/ticket/task/${taskId}/update`,
                    { name, description: desc, member_ids: members, due_date: due, task_priority: priority }
                );
                if (res.success) {
                    const taskEl = boardArea.querySelector(`.tb-task[data-task-id="${taskId}"]`);
                    if (taskEl) {
                        const colEl  = taskEl.closest('.tb-column');
                        const isDone = taskEl.classList.contains('tb-task-done');
                        const newEl  = buildTaskEl({ ...res.task, is_done: isDone });
                        taskEl.replaceWith(newEl);
                        updateColCount(colEl);
                    }
                    closeModal('taskModal'); toast('Task updated.');
                } else toast(res.error || 'Failed to update task.', 'error');
            }
        } finally {
            saveBtn.disabled = false;
            saveBtn.innerHTML = 'Save Task';
        }
    });

    // =========================================================
    // INTERNAL COMMENTS
    // =========================================================

    const commentInput = document.getElementById('commentInput');
    const commentSend  = document.getElementById('commentSend');
    const commentList  = document.getElementById('commentList');

    function buildCommentEl(c) {
        const div = document.createElement('div');
        div.className = 'tb-comment';
        div.dataset.commentId = c.id;
        div.innerHTML = `
            <div class="tb-comment-avatar">${escHtml(c.initials)}</div>
            <div class="tb-comment-body">
                <div class="tb-comment-meta">
                    <span class="tb-comment-author">${escHtml(c.author)}</span>
                    <span class="tb-comment-time">${escHtml(c.created)}</span>
                </div>
                <div class="tb-comment-msg">${escHtml(c.message)}</div>
            </div>
        `;
        return div;
    }

    // ── Poster identity for token-board users ──────────────────
    const posterRow      = document.getElementById('posterRow');
    const posterSetup    = document.getElementById('posterSetup');
    const posterDisplay  = document.getElementById('posterDisplayName');
    const posterInput    = document.getElementById('posterNameInput');
    const posterSave     = document.getElementById('posterNameSave');
    const posterChange   = document.getElementById('posterChange');

    function getPosterName()  { return sessionStorage.getItem('tb_poster_name') || ''; }
    function emailPrefix(n)   { return n.includes('@') ? n.split('@')[0] : n; }

    function applyPosterName(raw) {
        sessionStorage.setItem('tb_poster_name', raw);
        if (posterDisplay) posterDisplay.textContent = emailPrefix(raw);
        if (posterRow)   posterRow.style.display   = '';
        if (posterSetup) posterSetup.style.display = 'none';
    }

    if (publicBoard && boardToken && posterRow) {
        const saved = getPosterName();
        if (saved) {
            applyPosterName(saved);
        } else {
            posterSetup.style.display = '';
        }
        if (posterSave) {
            posterSave.addEventListener('click', () => {
                const n = (posterInput.value || '').trim();
                if (!n) { toast('Enter your name or email.', 'error'); return; }
                applyPosterName(n);
            });
        }
        if (posterInput) {
            posterInput.addEventListener('keydown', e => {
                if (e.key === 'Enter') posterSave && posterSave.click();
            });
        }
        if (posterChange) {
            posterChange.addEventListener('click', () => {
                if (posterInput) posterInput.value = getPosterName();
                if (posterSetup) posterSetup.style.display = '';
                if (posterInput) posterInput.focus();
            });
        }
    }

    if (commentSend) {
        commentSend.addEventListener('click', async () => {
            const message = (commentInput.value || '').trim();
            if (!message) { toast('Write a message first.', 'error'); return; }

            if (publicBoard && boardToken && !getPosterName()) {
                toast('Please set your name before posting.', 'error');
                if (posterSetup) posterSetup.style.display = '';
                if (posterInput) posterInput.focus();
                return;
            }

            commentSend.disabled = true;
            const poster_name = (publicBoard && boardToken) ? getPosterName() : '';
            const res = await jsonRpc(
                `/customer_support/ticket/${ticketId}/comment/add`,
                { message, mentioned_users: _mentionedUsers, poster_name }
            );
            commentSend.disabled = false;

            if (res.success) {
                const emptyEl = document.getElementById('commentsEmpty');
                if (emptyEl) emptyEl.remove();
                commentList.appendChild(buildCommentEl(res.comment));
                commentList.scrollTop = commentList.scrollHeight;
                commentInput.value = '';
                const commentsTab = document.querySelector('.tb-stab[data-tab="comments"]');
                if (commentsTab) commentsTab.click();
                toast('Note posted.');
            } else {
                toast(res.error || 'Failed to post note.', 'error');
            }
        });

        commentInput.addEventListener('keydown', e => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                commentSend.click();
            }
        });
    }

    if (commentList) commentList.scrollTop = commentList.scrollHeight;

    // =========================================================
    // @MENTION AUTOCOMPLETE IN NOTES
    // =========================================================

    let _mentionedUsers = [];   // tracks {user_id, email, name} objects mentioned in current draft

    if (commentInput) {
        const mentionDropdown = document.createElement('div');
        mentionDropdown.className = 'tb-mention-dropdown';
        mentionDropdown.style.display = 'none';
        commentInput.parentNode.insertBefore(mentionDropdown, commentInput.nextSibling);

        function hideMentionDropdown() { mentionDropdown.style.display = 'none'; }

        commentInput.addEventListener('input', () => {
            const val  = commentInput.value;
            const pos  = commentInput.selectionStart;
            const before = val.slice(0, pos);
            const atIdx = before.lastIndexOf('@');

            if (atIdx === -1 || before.slice(atIdx).includes(' ')) {
                hideMentionDropdown(); return;
            }

            const query = before.slice(atIdx + 1).toLowerCase();
            const alreadyMentioned = _mentionedUsers.map(u => u.name);
            const matches = projectMembers.filter(m =>
                m.name.toLowerCase().startsWith(query) && !alreadyMentioned.includes(m.name)
            );

            if (!matches.length) { hideMentionDropdown(); return; }

            mentionDropdown.innerHTML = '';
            matches.slice(0, 6).forEach(m => {
                const item = document.createElement('div');
                item.className = 'tb-mention-item';
                item.innerHTML = `<span class="tb-mention-av">${escHtml(m.initials)}</span>
                                  <span class="tb-mention-name">${escHtml(m.name)}</span>
                                  <span class="tb-mention-role">${escHtml(m.role)}</span>`;
                item.addEventListener('mousedown', e => {
                    e.preventDefault();
                    // Replace @query with @Name
                    const newVal = val.slice(0, atIdx) + `@${m.name} ` + val.slice(pos);
                    commentInput.value = newVal;
                    commentInput.setSelectionRange(atIdx + m.name.length + 2, atIdx + m.name.length + 2);
                    _mentionedUsers.push({ user_id: m.user_id || null, email: m.email || '', name: m.name });
                    hideMentionDropdown();
                    commentInput.focus();
                });
                mentionDropdown.appendChild(item);
            });
            mentionDropdown.style.display = '';
        });

        commentInput.addEventListener('blur', () => setTimeout(hideMentionDropdown, 150));
        commentInput.addEventListener('keydown', e => {
            if (e.key === 'Escape') hideMentionDropdown();
        });
    }

    // Reset _mentionedUsers after a comment is posted (detected via MutationObserver on the list)
    if (commentInput && commentList) {
        const observer = new MutationObserver(() => {
            _mentionedUsers = [];
        });
        observer.observe(commentList, { childList: true });
    }

    // =========================================================
    // REPLY TO CUSTOMER
    // =========================================================

    const customerReplySend  = document.getElementById('customerReplySend');
    const customerReplyInput = document.getElementById('customerReplyInput');
    const customerConversationList = document.getElementById('customerConversationList');

    function conversationBubbleHtml(msg) {
        const mine = msg.is_me ? ' mine' : '';
        const side = msg.from_customer ? 'customer' : 'focal';
        const author = msg.from_customer ? 'Customer' : (msg.author || 'Support');
        const initials = escHtml(msg.initials || '?');
        const text = escHtml(htmlToText(msg.body));
        const created = escHtml(msg.created || '');
        return `<div class="tb-conv-item ${side}${mine}">
            <div class="tb-conv-avatar">${initials}</div>
            <div class="tb-conv-body">
                <div class="tb-conv-meta">
                    <span class="tb-conv-author">${escHtml(author)}</span>
                    <span class="tb-conv-time">${created}</span>
                </div>
                <div class="tb-conv-msg">${text}</div>
            </div>
        </div>`;
    }

    function renderConversation(messages) {
        if (!customerConversationList) return;
        customerConversationList.innerHTML = '';
        if (!messages || !messages.length) {
            customerConversationList.innerHTML = '<div class="tb-empty-text" id="customerConversationEmpty">No customer conversation yet.</div>';
            return;
        }
        messages.forEach(msg => {
            customerConversationList.insertAdjacentHTML('beforeend', conversationBubbleHtml(msg));
        });
        customerConversationList.scrollTop = customerConversationList.scrollHeight;
    }

    async function refreshConversation(silent) {
        if ((publicBoard && !canEdit) || !customerConversationList) return;
        const res = await jsonRpc(`/customer_support/ticket/${ticketId}/conversation/messages`, {});
        if (!res.success) {
            if (!silent) toast(res.error || 'Failed to load conversation.', 'error');
            return;
        }
        customerConversation = res.messages || [];
        renderConversation(customerConversation);
    }

    renderConversation(customerConversation);

    if (customerReplySend && customerReplyInput) {
        customerReplySend.addEventListener('click', async () => {
            const message = customerReplyInput.value.trim();
            if (!message) { toast('Write a reply first.', 'error'); return; }

            customerReplySend.disabled = true;
            customerReplySend.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Sending…';

            const res = await jsonRpc(
                `/customer_support/ticket/${ticketId}/reply_customer`,
                { message }
            );

            customerReplySend.disabled = false;
            customerReplySend.innerHTML = '<i class="bi bi-send-fill me-1"></i>Send to Customer';

            if (res.success) {
                const now = new Date();
                customerConversation.push({
                    initials: 'Me',
                    author: 'You',
                    body: message,
                    created: now.toLocaleString('en-US', {
                        month: 'short', day: '2-digit', year: 'numeric',
                        hour: '2-digit', minute: '2-digit', hour12: false,
                    }).replace(',', ''),
                    from_customer: false,
                    is_me: true,
                });
                renderConversation(customerConversation);
                customerReplyInput.value = '';
                toast('Reply sent to customer!');
                setTimeout(() => refreshConversation(true), 500);
            } else {
                toast(res.error || 'Failed to send reply.', 'error');
            }
        });
    }

    setInterval(() => {
        const replyTab = document.getElementById('tab-reply');
        if (replyTab && replyTab.classList.contains('active')) refreshConversation(true);
    }, 20000);

    // =========================================================
    // INVITE TEAM MEMBER (focal/admin only)
    // =========================================================

    const inviteMemberBtn  = document.getElementById('inviteMemberBtn');
    const inviteModalSend  = document.getElementById('inviteModalSend');
    const inviteModalClose = document.getElementById('inviteModalClose');
    const inviteModalCancel= document.getElementById('inviteModalCancel');

    if (inviteMemberBtn) {
        inviteMemberBtn.addEventListener('click', () => {
            document.getElementById('inviteModalName').value  = '';
            document.getElementById('inviteModalEmail').value = '';
            openModal('inviteModal');
        });
    }

    if (inviteModalClose)  inviteModalClose.addEventListener('click',  () => closeModal('inviteModal'));
    if (inviteModalCancel) inviteModalCancel.addEventListener('click', () => closeModal('inviteModal'));

    if (inviteModalSend) {
        inviteModalSend.addEventListener('click', async () => {
            const name  = (document.getElementById('inviteModalName').value  || '').trim();
            const email = (document.getElementById('inviteModalEmail').value || '').trim();
            const role  = (document.getElementById('inviteModalRole') || {}).value || 'other';

            if (!name)  { toast('Name is required.', 'error');  return; }
            if (!email) { toast('Email is required.', 'error'); return; }
            if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
                toast('Enter a valid email address.', 'error'); return;
            }

            inviteModalSend.disabled = true;
            inviteModalSend.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Sending…';

            const res = await jsonRpc(
                `/customer_support/ticket/${ticketId}/board/invite`,
                { name, email, role }
            );

            inviteModalSend.disabled = false;
            inviteModalSend.innerHTML = '<i class="bi bi-send me-1"></i>Send Invite';

            if (res.success) {
                closeModal('inviteModal');
                toast(`Invite sent to ${name}!`);
                // Push new member into live projectMembers and refresh avatars
                if (res.member) {
                    projectMembers.push(res.member);
                    renderTeamAvatars();
                    buildTeamPanel();
                }
            } else {
                toast(res.error || 'Failed to send invite.', 'error');
            }
        });
    }

    // =========================================================
    // TEAM AVATARS + TEAM PANEL
    // =========================================================

    const ROLE_OPTIONS = [
        { key: 'focal_person',    label: 'Focal Person' },
        { key: 'frontend_dev',    label: 'Frontend Developer' },
        { key: 'backend_dev',     label: 'Backend Developer' },
        { key: 'network_manager', label: 'Network Manager' },
        { key: 'designer',        label: 'UI/UX Designer' },
        { key: 'qa_engineer',     label: 'QA Engineer' },
        { key: 'other',           label: 'Other' },
    ];

    // Avatar colour palette — cycles by index
    const AV_COLORS = ['#6366f1','#0891b2','#059669','#d97706','#dc2626','#7c3aed','#db2777','#0284c7'];

    const teamAvatarsWrap = document.getElementById('teamAvatarsWrap');
    const teamAvStack     = document.getElementById('teamAvStack');
    const teamAvLabel     = document.getElementById('teamAvLabel');
    const tbTeamPanel     = document.getElementById('tbTeamPanel');
    const tbTeamPanelList = document.getElementById('tbTeamPanelList');
    const tbTeamPanelClose= document.getElementById('tbTeamPanelClose');

    // Compute active task count for a member from board DOM
    function getActiveTasks(memberId) {
        if (!memberId) return 0;
        let count = 0;
        boardArea.querySelectorAll('.tb-task:not(.tb-task-done)').forEach(taskEl => {
            const avatars = taskEl.querySelectorAll('.tb-avatar');
            avatars.forEach(av => {
                const avMemberId = parseInt(av.dataset.memberId || '0');
                if (avMemberId && avMemberId === memberId) count++;
            });
        });
        return count;
    }

    function renderTeamAvatars() {
        if (!teamAvStack) return;
        teamAvStack.innerHTML = '';
        const MAX_SHOW = 5;
        projectMembers.slice(0, MAX_SHOW).forEach((m, i) => {
            const av = document.createElement('div');
            av.className = 'tb-team-av-circle';
            av.style.background = AV_COLORS[i % AV_COLORS.length];
            av.style.zIndex = MAX_SHOW - i;
            av.textContent = m.initials;
            av.title = `${m.name} — ${m.role}`;
            teamAvStack.appendChild(av);
        });
        const extra = projectMembers.length - MAX_SHOW;
        if (extra > 0) {
            const more = document.createElement('div');
            more.className = 'tb-team-av-circle tb-team-av-more';
            more.textContent = `+${extra}`;
            more.style.zIndex = 0;
            teamAvStack.appendChild(more);
        }
        if (teamAvLabel) {
            teamAvLabel.textContent = projectMembers.length === 1
                ? '1 member' : `${projectMembers.length} members`;
        }
    }

    function buildTeamPanel() {
        if (!tbTeamPanelList) return;
        tbTeamPanelList.innerHTML = '';
        if (!projectMembers.length) {
            tbTeamPanelList.innerHTML = '<div class="tb-team-empty">No team members yet.</div>';
            return;
        }
        projectMembers.forEach((m, idx) => {
            const activeTasks = getActiveTasks(parseInt(m.member_id || m.id));
            const isWorking   = activeTasks > 0;
            const row = document.createElement('div');
            row.className = 'tb-team-row';

            const roleOpts = ROLE_OPTIONS.map(r =>
                `<option value="${r.key}" ${(m.role_key || 'other') === r.key ? 'selected' : ''}>${r.label}</option>`
            ).join('');

            row.innerHTML = `
                <div class="tb-team-row-av" style="background:${AV_COLORS[idx % AV_COLORS.length]}">${escHtml(m.initials)}</div>
                <div class="tb-team-row-info">
                    <div class="tb-team-row-name">${escHtml(m.name)}</div>
                    <div class="tb-team-row-meta">
                        ${publicBoard
                            ? `<span class="tb-team-role-badge">${escHtml(m.role)}</span>`
                            : `<select class="tb-team-role-select" data-member-id="${m.member_id || ''}" data-idx="${idx}">${roleOpts}</select>`
                        }
                        <span class="tb-team-status ${isWorking ? 'working' : 'idle'}">
                            <span class="tb-team-dot"></span>
                            ${isWorking ? `${activeTasks} active task${activeTasks > 1 ? 's' : ''}` : 'No tasks'}
                        </span>
                    </div>
                </div>
            `;

            // Role change handler (focal/admin only)
            if (!publicBoard) {
                const sel = row.querySelector('.tb-team-role-select');
                if (sel) {
                    sel.addEventListener('change', async () => {
                        const newRole = sel.value;
                        const memberId = parseInt(sel.dataset.memberId);
                        if (!memberId) { toast('Cannot update role for external member.', 'error'); return; }
                        const res = await jsonRpc(
                            `/customer_support/project_member/${memberId}/set_role`,
                            { role: newRole }
                        );
                        if (res.success) {
                            const i = parseInt(sel.dataset.idx);
                            projectMembers[i].role     = res.role_label;
                            projectMembers[i].role_key = newRole;
                            // Update picker label in DOM
                            sel.closest('.tb-team-row').querySelector('.tb-team-role-select').value = newRole;
                            toast(`Role updated to ${res.role_label}.`);
                        } else toast(res.error || 'Failed to update role.', 'error');
                    });
                }
            }
            tbTeamPanelList.appendChild(row);
        });
    }

    // Open / close panel — only toggle when clicking the avatar stack/label, not the panel itself
    if (teamAvatarsWrap) {
        teamAvatarsWrap.addEventListener('click', e => {
            e.stopPropagation();
            // If click originated inside the panel, ignore (let panel handle its own events)
            if (tbTeamPanel && tbTeamPanel.contains(e.target)) return;
            if (tbTeamPanel) tbTeamPanel.classList.toggle('open');
            if (tbTeamPanel && tbTeamPanel.classList.contains('open')) buildTeamPanel();
        });
    }
    if (tbTeamPanelClose) tbTeamPanelClose.addEventListener('click', e => {
        e.stopPropagation();
        if (tbTeamPanel) tbTeamPanel.classList.remove('open');
    });
    document.addEventListener('click', e => {
        if (tbTeamPanel && tbTeamPanel.classList.contains('open') &&
            !tbTeamPanel.contains(e.target) && !teamAvatarsWrap.contains(e.target)) {
            tbTeamPanel.classList.remove('open');
        }
    });

    // Initial render
    renderTeamAvatars();

    // =========================================================
    // TRELLO-STYLE "ADD ANOTHER LIST"
    // =========================================================

    const addListGhost   = document.getElementById('addListGhost');
    const addListBtnWrap = document.getElementById('addListBtnWrap');
    const addListForm    = document.getElementById('addListForm');
    const addListBtn     = document.getElementById('addListBtn');
    const addListInput   = document.getElementById('addListInput');
    const addListSave    = document.getElementById('addListSave');
    const addListCancel  = document.getElementById('addListCancel');
    const addListColors  = document.getElementById('addListColors');

    let _addListColor = '#6366f1';

    if (addListColors) {
        const QUICK_COLORS = ['#6366f1','#06b6d4','#10b981','#f59e0b','#ef4444','#ec4899','#8b5cf6','#64748b'];
        QUICK_COLORS.forEach(c => {
            const dot = document.createElement('span');
            dot.className = 'tb-al-color-dot' + (c === _addListColor ? ' selected' : '');
            dot.style.background = c;
            dot.dataset.color = c;
            dot.addEventListener('click', () => {
                _addListColor = c;
                addListColors.querySelectorAll('.tb-al-color-dot').forEach(d => d.classList.remove('selected'));
                dot.classList.add('selected');
            });
            addListColors.appendChild(dot);
        });
    }

    function openAddListForm() {
        if (!addListGhost) return;
        addListBtnWrap.style.display = 'none';
        addListForm.style.display    = '';
        if (addListInput) { addListInput.value = ''; addListInput.focus(); }
    }

    function closeAddListForm() {
        if (!addListGhost) return;
        addListBtnWrap.style.display = '';
        addListForm.style.display    = 'none';
    }

    async function submitAddList() {
        const name = addListInput ? addListInput.value.trim() : '';
        if (!name) { if (addListInput) addListInput.focus(); return; }
        const res = await jsonRpc(
            `/customer_support/ticket/${ticketId}/board/column/add`,
            { name, color: _addListColor }
        );
        if (res.success) {
            removeEmptyState();
            const colEl = buildColumnEl({ id: res.column_id, name: res.name, color: res.color });
            boardArea.insertBefore(colEl, addListGhost);
            closeAddListForm();
            toast('List added.');
        } else {
            toast(res.error || 'Failed to add list.', 'error');
        }
    }

    if (addListBtn)    addListBtn.addEventListener('click', openAddListForm);
    if (addListCancel) addListCancel.addEventListener('click', closeAddListForm);
    if (addListSave)   addListSave.addEventListener('click', submitAddList);
    if (addListInput) {
        addListInput.addEventListener('keydown', async e => {
            if (e.key === 'Enter')  { e.preventDefault(); await submitAddList(); }
            if (e.key === 'Escape') closeAddListForm();
        });
    }
    // Close inline form when clicking outside
    document.addEventListener('click', e => {
        if (addListGhost && !addListGhost.contains(e.target)) closeAddListForm();
    });

    // =========================================================
    // BOARD BACKGROUND CUSTOMIZATION
    // =========================================================

    const BG_THEMES = [
        { name: 'Default',  value: '#0f172a' },
        { name: 'Slate',    value: '#1e293b' },
        { name: 'Navy',     value: '#0a1628' },
        { name: 'Midnight', value: '#080820' },
        { name: 'Forest',   value: '#0d1f17' },
        { name: 'Plum',     value: '#1a0a2e' },
        { name: 'Rosewood', value: '#1a0a14' },
        { name: 'Charcoal', value: '#141414' },
        { name: 'Ocean',    value: 'linear-gradient(135deg,#0a1628 0%,#1e3a5f 100%)' },
        { name: 'Aurora',   value: 'linear-gradient(135deg,#0d1f17 0%,#0a1a3a 100%)' },
        { name: 'Dusk',     value: 'linear-gradient(135deg,#1a0a2e 0%,#0f1a3a 100%)' },
        { name: 'Ember',    value: 'linear-gradient(135deg,#1a0800 0%,#1a0028 100%)' },
        { name: 'Indigo',   value: 'linear-gradient(135deg,#1a0a3e 0%,#0f1a28 100%)' },
        { name: 'Moss',     value: 'linear-gradient(135deg,#0d2010 0%,#1a2e0a 100%)' },
        { name: 'Steel',    value: 'linear-gradient(135deg,#0f172a 0%,#1c2d3d 100%)' },
        { name: 'Rose',     value: 'linear-gradient(135deg,#1a0a14 0%,#2d0a20 100%)' },
    ];

    const tbWrap         = document.getElementById('wrap');
    const bgPanel        = document.getElementById('tbBgPanel');
    const bgCustomizeBtn = document.getElementById('bgCustomizeBtn');
    const bgPanelClose   = document.getElementById('tbBgPanelClose');
    const bgGrid         = document.getElementById('tbBgGrid');
    const bgCustomInput  = document.getElementById('bgCustomColorInput');
    const bgResetBtn     = document.getElementById('tbBgReset');

    let _currentBg = D.boardBg || '';

    function applyBg(value, save) {
        if (!tbWrap) return;
        tbWrap.style.background = value || '#0f172a';
        _currentBg = value;
        if (bgGrid) bgGrid.querySelectorAll('.tb-bg-swatch').forEach(s =>
            s.classList.toggle('active', s.dataset.value === value)
        );
        if (save) jsonRpc(`/customer_support/ticket/${ticketId}/board/set_bg`, { bg: value || '' })
                     .catch(() => {});
    }

    // Build swatches
    if (bgGrid) {
        BG_THEMES.forEach(theme => {
            const swatch = document.createElement('div');
            swatch.className = 'tb-bg-swatch' + (theme.value === _currentBg ? ' active' : '');
            swatch.title = theme.name;
            swatch.dataset.value = theme.value;
            swatch.style.background = theme.value;
            swatch.addEventListener('click', () => applyBg(theme.value, true));
            bgGrid.appendChild(swatch);
        });
    }

    if (bgCustomInput) {
        bgCustomInput.addEventListener('input',  e => applyBg(e.target.value, false));
        bgCustomInput.addEventListener('change', e => applyBg(e.target.value, true));
    }
    if (bgResetBtn) bgResetBtn.addEventListener('click', () => applyBg('', true));

    if (bgCustomizeBtn) {
        bgCustomizeBtn.addEventListener('click', e => {
            e.stopPropagation();
            if (bgPanel) bgPanel.classList.toggle('open');
            bgCustomizeBtn.classList.toggle('active', bgPanel && bgPanel.classList.contains('open'));
        });
    }
    if (bgPanelClose) bgPanelClose.addEventListener('click', () => {
        if (bgPanel) bgPanel.classList.remove('open');
        if (bgCustomizeBtn) bgCustomizeBtn.classList.remove('active');
    });
    document.addEventListener('click', e => {
        if (bgPanel && bgPanel.classList.contains('open') &&
            !bgPanel.contains(e.target) && e.target !== bgCustomizeBtn) {
            bgPanel.classList.remove('open');
            if (bgCustomizeBtn) bgCustomizeBtn.classList.remove('active');
        }
    });

    // Apply saved background on load
    if (_currentBg) applyBg(_currentBg, false);

    // =========================================================
    // KEYBOARD SHORTCUTS
    // =========================================================

    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.tb-modal-overlay.open').forEach(m => m.classList.remove('open'));
            if (statusDropdown) statusDropdown.classList.remove('open');
            closeAddListForm();
            if (bgPanel) bgPanel.classList.remove('open');
            if (bgCustomizeBtn) bgCustomizeBtn.classList.remove('active');
        }
    });

})();
