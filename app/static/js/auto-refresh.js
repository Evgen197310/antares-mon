/**
 * Универсальный модуль автообновления для всех страниц мониторинга
 * Поддерживает polling и WebSocket для real-time обновлений
 */

class AutoRefresh {
    constructor(options = {}) {
        this.interval = options.interval || 30000; // 30 секунд по умолчанию
        this.enabled = options.enabled !== false;
        this.method = options.method || 'polling'; // 'polling' или 'websocket'
        this.endpoint = options.endpoint || window.location.pathname;
        this.onUpdate = options.onUpdate || this.defaultUpdateHandler;
        this.onError = options.onError || this.defaultErrorHandler;
        
        this.timer = null;
        this.websocket = null;
        this.lastUpdate = new Date();
        this.updateCount = 0;
        
        this.init();
    }
    
    init() {
        console.log('AutoRefresh: Initializing with config:', {
            interval: this.interval,
            enabled: this.enabled,
            method: this.method,
            endpoint: this.endpoint
        });
        
        // Пропускаем создание индикатора для упрощения отладки
        // this.createStatusIndicator();
        this.bindEvents();
        
        if (this.enabled) {
            console.log('AutoRefresh: Starting auto-refresh...');
            this.start();
        } else {
            console.log('AutoRefresh: Auto-refresh disabled');
        }
    }
    
    createStatusIndicator() {
        // Создаём индикатор статуса обновления
        const indicator = document.createElement('div');
        indicator.id = 'refresh-indicator';
        indicator.className = 'refresh-indicator';
        indicator.innerHTML = `
            <div class="refresh-status">
                <i class="fas fa-circle text-success" id="status-icon"></i>
                <span id="status-text">Автообновление</span>
                <small id="last-update" class="text-muted ms-2"></small>
            </div>
            <div class="refresh-controls">
                <button id="toggle-refresh" class="btn btn-sm btn-outline-secondary">
                    <i class="fas fa-pause"></i>
                </button>
                <button id="manual-refresh" class="btn btn-sm btn-outline-primary">
                    <i class="fas fa-sync-alt"></i>
                </button>
            </div>
        `;
        
        // Добавляем стили
        const style = document.createElement('style');
        style.textContent = `
            .refresh-indicator {
                position: fixed;
                top: 20px;
                right: 20px;
                background: rgba(255, 255, 255, 0.95);
                border: 1px solid #dee2e6;
                border-radius: 8px;
                padding: 8px 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                z-index: 1050;
                display: flex;
                align-items: center;
                gap: 10px;
                font-size: 0.875rem;
                backdrop-filter: blur(5px);
            }
            .refresh-indicator .refresh-controls {
                display: flex;
                gap: 5px;
            }
            .refresh-indicator .btn {
                padding: 2px 6px;
                font-size: 0.75rem;
            }
            @media (max-width: 768px) {
                .refresh-indicator {
                    top: 10px;
                    right: 10px;
                    font-size: 0.75rem;
                }
            }
        `;
        document.head.appendChild(style);
        document.body.appendChild(indicator);
        
        this.updateStatusIndicator();
    }
    
    bindEvents() {
        // Кнопка переключения автообновления
        document.getElementById('toggle-refresh').addEventListener('click', () => {
            this.toggle();
        });
        
        // Кнопка ручного обновления
        document.getElementById('manual-refresh').addEventListener('click', () => {
            this.refresh();
        });
        
        // Обновление при фокусе на вкладке
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && this.enabled) {
                this.refresh();
            }
        });
        
        // Остановка при уходе со страницы
        window.addEventListener('beforeunload', () => {
            this.stop();
        });
    }
    
    start() {
        console.log('AutoRefresh: start() called, method:', this.method);
        
        if (this.method === 'websocket') {
            console.log('AutoRefresh: Starting WebSocket...');
            this.startWebSocket();
        } else {
            console.log('AutoRefresh: Starting polling with interval:', this.interval);
            this.startPolling();
        }
        this.enabled = true;
        
        // Пропускаем обновление индикатора для упрощения отладки
        // this.updateStatusIndicator();
        
        console.log('AutoRefresh: Started successfully');
    }
    
    stop() {
        if (this.timer) {
            clearInterval(this.timer);
            this.timer = null;
        }
        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }
        this.enabled = false;
        this.updateStatusIndicator();
    }
    
    toggle() {
        if (this.enabled) {
            this.stop();
        } else {
            this.start();
        }
    }
    
    startPolling() {
        console.log('AutoRefresh: Setting up polling timer with interval:', this.interval);
        this.timer = setInterval(() => {
            console.log('AutoRefresh: Timer triggered, calling refresh...');
            this.refresh();
        }, this.interval);
        console.log('AutoRefresh: Polling timer set, ID:', this.timer);
        
        // Выполняем первое обновление сразу
        console.log('AutoRefresh: Performing initial refresh...');
        this.refresh();
    }
    
    startWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/updates`;
        
        this.websocket = new WebSocket(wsUrl);
        
        this.websocket.onopen = () => {
            console.log('WebSocket connected');
            this.updateStatusIndicator('connected');
        };
        
        this.websocket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleWebSocketUpdate(data);
        };
        
        this.websocket.onclose = () => {
            console.log('WebSocket disconnected, falling back to polling');
            this.method = 'polling';
            this.startPolling();
        };
        
        this.websocket.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.onError(error);
        };
    }
    
    async refresh() {
        try {
            console.log('AutoRefresh: Starting refresh...');
            this.updateStatusIndicator('updating');
            
            // Определяем API endpoint для текущей страницы
            const apiEndpoint = this.getApiEndpoint();
            console.log('AutoRefresh: API endpoint:', apiEndpoint);
            
            if (apiEndpoint) {
                const response = await fetch(apiEndpoint);
                if (response.ok) {
                    const data = await response.json();
                    console.log('AutoRefresh: Received data:', data);
                    this.onUpdate(data);
                    this.lastUpdate = new Date();
                    this.updateCount++;
                    this.updateStatusIndicator('success');
                    console.log('AutoRefresh: Update completed successfully');
                } else {
                    throw new Error(`HTTP ${response.status}`);
                }
            } else {
                // Fallback: перезагрузка страницы
                window.location.reload();
            }
        } catch (error) {
            console.error('Refresh error:', error);
            this.onError(error);
            this.updateStatusIndicator('error');
        }
    }
    
    getApiEndpoint() {
        const path = window.location.pathname;
        
        // Маппинг страниц на API endpoints
        const apiMap = {
            '/': '/api/status',
            '/vpn/': '/api/vpn/sessions',
            '/vpn/history': '/api/vpn/history',
            '/vpn/stats': '/api/vpn/stats',
            '/vpn/topology': '/api/vpn/sessions',
            '/rdp/': '/api/rdp/sessions',
            '/rdp/active-sessions': '/api/rdp/sessions',
            '/rdp/sessions-history': '/api/rdp/history',
            '/smb/': '/api/smb/sessions',
            '/smb/files-open-now': '/api/smb/files',
            '/smb/users': '/api/smb/users',
            '/smb/files-modified-stats': '/api/smb/stats'
        };
        
        return apiMap[path] || null;
    }
    
    handleWebSocketUpdate(data) {
        this.onUpdate(data);
        this.lastUpdate = new Date();
        this.updateCount++;
        this.updateStatusIndicator('success');
    }
    
    defaultUpdateHandler(data) {
        // Универсальный обработчик обновления данных
        console.log('AutoRefresh: defaultUpdateHandler called with data:', data);
        
        // Обновляем счётчики на дашборде
        this.updateDashboardCounters(data);
        
        // Обновляем таблицы
        this.updateTables(data);
        
        // Обновляем графики (если есть)
        this.updateCharts(data);
    }
    
    updateDashboardCounters(data) {
        // Обновление счётчиков на карточках дашборда
        console.log('AutoRefresh: Updating dashboard counters with data:', data);
        
        if (data.vpn_active !== undefined) {
            const vpnCounter = document.querySelector('[data-counter="vpn-active"]');
            console.log('AutoRefresh: VPN counter element:', vpnCounter, 'value:', data.vpn_active);
            if (vpnCounter) vpnCounter.textContent = data.vpn_active;
        }
        
        if (data.rdp_active !== undefined) {
            const rdpCounter = document.querySelector('[data-counter="rdp-active"]');
            if (rdpCounter) rdpCounter.textContent = data.rdp_active;
        }
        
        if (data.smb_files !== undefined) {
            const smbCounter = document.querySelector('[data-counter="smb-files"]');
            if (smbCounter) smbCounter.textContent = data.smb_files;
        }
        
        // Дополнительные счётчики для других данных
        if (data.vpn_today !== undefined) {
            const vpnTodayCounter = document.querySelector('[data-counter="vpn-today"]');
            if (vpnTodayCounter) vpnTodayCounter.textContent = data.vpn_today;
        }
        
        if (data.mikrotik_devices !== undefined) {
            const mikrotikCounter = document.querySelector('[data-counter="mikrotik-devices"]');
            if (mikrotikCounter) mikrotikCounter.textContent = data.mikrotik_devices;
        }
        
        // Обновляем время последнего обновления
        if (data.last_update) {
            const lastUpdateElements = document.querySelectorAll('[data-counter="last-update"]');
            lastUpdateElements.forEach(el => {
                if (el) el.textContent = data.last_update;
            });
        }
    }
    
    updateTables(data) {
        // Обновление таблиц с данными
        const tables = document.querySelectorAll('[data-auto-refresh="table"]');
        tables.forEach(table => {
            const tableType = table.dataset.tableType;
            if (data[tableType]) {
                this.refreshTable(table, data[tableType]);
            }
        });
    }
    
    refreshTable(table, newData) {
        const tbody = table.querySelector('tbody');
        if (!tbody || !newData) return;
        
        // Сохраняем текущее состояние прокрутки
        const scrollTop = window.pageYOffset;
        
        // Обновляем содержимое таблицы
        tbody.innerHTML = this.generateTableRows(newData, table.dataset.tableType);
        
        // Восстанавливаем прокрутку
        window.scrollTo(0, scrollTop);
        
        // Анимация обновления
        tbody.style.opacity = '0.7';
        setTimeout(() => {
            tbody.style.opacity = '1';
        }, 200);
    }
    
    generateTableRows(data, tableType) {
        // Генерация строк таблицы в зависимости от типа
        switch (tableType) {
            case 'vpn-sessions':
                return this.generateVpnRows(data);
            case 'rdp-sessions':
                return this.generateRdpRows(data);
            case 'smb-files':
                return this.generateSmbRows(data);
            default:
                return '';
        }
    }
    
    generateVpnRows(sessions) {
        return sessions.map(session => `
            <tr>
                <td><a href="/vpn/user/${session.username}">${session.username}</a></td>
                <td>${session.external_ip || 'N/A'}</td>
                <td>${session.internal_ip || 'N/A'}</td>
                <td>${session.router || 'N/A'}</td>
                <td>${this.formatDuration(session.duration)}</td>
            </tr>
        `).join('');
    }
    
    generateRdpRows(sessions) {
        return sessions.map(session => `
            <tr>
                <td><a href="/rdp/user/${session.username}">${session.username}</a></td>
                <td>${session.collection || 'N/A'}</td>
                <td>${session.server || 'N/A'}</td>
                <td>${this.formatDateTime(session.login_time)}</td>
                <td>${this.formatDuration(session.duration)}</td>
            </tr>
        `).join('');
    }
    
    generateSmbRows(files) {
        return files.map(file => `
            <tr>
                <td><a href="/smb/user/${file.username}">${file.username}</a></td>
                <td><a href="/smb/download/${encodeURIComponent(file.path)}" title="${file.path}">${file.filename}</a></td>
                <td>${file.server || 'N/A'}</td>
                <td>${this.formatDateTime(file.open_time)}</td>
            </tr>
        `).join('');
    }
    
    updateCharts(data) {
        // Обновление графиков (если используются Chart.js или другие библиотеки)
        const charts = document.querySelectorAll('[data-auto-refresh="chart"]');
        charts.forEach(chart => {
            // Логика обновления графиков
            console.log('Updating chart:', chart.id);
        });
    }
    
    updateStatusIndicator(status = null) {
        const icon = document.getElementById('status-icon');
        const text = document.getElementById('status-text');
        const lastUpdate = document.getElementById('last-update');
        const toggleBtn = document.getElementById('toggle-refresh');
        
        if (!icon || !text || !lastUpdate || !toggleBtn) return;
        
        // Обновляем время последнего обновления
        if (this.lastUpdate) {
            lastUpdate.textContent = this.formatTime(this.lastUpdate);
        }
        
        // Обновляем статус
        switch (status) {
            case 'updating':
                icon.className = 'fas fa-circle text-warning';
                text.textContent = 'Обновление...';
                break;
            case 'success':
                icon.className = 'fas fa-circle text-success';
                text.textContent = 'Автообновление';
                break;
            case 'error':
                icon.className = 'fas fa-circle text-danger';
                text.textContent = 'Ошибка';
                break;
            case 'connected':
                icon.className = 'fas fa-circle text-info';
                text.textContent = 'WebSocket';
                break;
            default:
                if (this.enabled) {
                    icon.className = 'fas fa-circle text-success';
                    text.textContent = 'Автообновление';
                } else {
                    icon.className = 'fas fa-circle text-secondary';
                    text.textContent = 'Остановлено';
                }
        }
        
        // Обновляем кнопку переключения
        const toggleIcon = toggleBtn.querySelector('i');
        if (this.enabled) {
            toggleIcon.className = 'fas fa-pause';
            toggleBtn.title = 'Остановить автообновление';
        } else {
            toggleIcon.className = 'fas fa-play';
            toggleBtn.title = 'Запустить автообновление';
        }
    }
    
    defaultErrorHandler(error) {
        console.error('AutoRefresh error:', error);
        this.updateStatusIndicator('error');
        
        // Показываем уведомление об ошибке
        this.showNotification('Ошибка обновления данных', 'error');
    }
    
    showNotification(message, type = 'info') {
        // Простое уведомление
        const notification = document.createElement('div');
        notification.className = `alert alert-${type === 'error' ? 'danger' : 'info'} alert-dismissible fade show`;
        notification.style.cssText = `
            position: fixed;
            top: 80px;
            right: 20px;
            z-index: 1060;
            min-width: 300px;
        `;
        notification.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        document.body.appendChild(notification);
        
        // Автоудаление через 5 секунд
        setTimeout(() => {
            if (notification.parentNode) {
                notification.remove();
            }
        }, 5000);
    }
    
    formatTime(date) {
        return date.toLocaleTimeString('ru-RU', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }
    
    formatDateTime(dateString) {
        const date = new Date(dateString);
        return date.toLocaleString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }
    
    formatDuration(seconds) {
        if (!seconds) return 'N/A';
        
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        
        if (hours > 0) {
            return `${hours}ч ${minutes}м`;
        } else {
            return `${minutes}м`;
        }
    }
}

// Глобальная инициализация автообновления
window.AutoRefresh = AutoRefresh;

// Упрощённая инициализация автообновления
document.addEventListener('DOMContentLoaded', function() {
    console.log('AutoRefresh: DOM loaded, starting simple initialization...');
    
    // Определяем, нужно ли автообновление для текущей страницы
    const path = window.location.pathname;
    console.log('AutoRefresh: Current path:', path);
    
    let shouldAutoRefresh = false;
    let interval = 15000; // 15 секунд по умолчанию
    
    // Автообновление только для дашборда и активных сессий
    if (path === '/' || path === '/index' || path === '/dashboard') {
        shouldAutoRefresh = true;
        interval = 15000; // 15 секунд для дашборда
        console.log('AutoRefresh: Dashboard detected, enabling auto-refresh');
    } else if (path.includes('/rdp/active-sessions') || path.includes('/vpn/active') || path.includes('/smb/active')) {
        shouldAutoRefresh = true;
        interval = 15000; // 15 секунд для активных сессий
        console.log('AutoRefresh: Active sessions page detected, enabling auto-refresh');
    } else {
        console.log('AutoRefresh: Static page, auto-refresh disabled');
    }
    
    if (shouldAutoRefresh) {
        // Простая функция обновления
        async function updateDashboard() {
            console.log('AutoRefresh: Updating dashboard...');
            try {
                const response = await fetch('/api/status');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                
                const data = await response.json();
                console.log('AutoRefresh: Data received:', data);
                
                // Обновляем счётчики на дашборде
                updateDashboardCounters(data);
                
                // Обновляем списки пользователей и файлов
                await updateDashboardLists();
                
                // Обновляем время последнего обновления
                const timeElement = document.getElementById('server-time');
                if (timeElement && data.last_update) {
                    timeElement.textContent = data.last_update;
                }
                
                console.log('AutoRefresh: Update completed successfully');
            } catch (error) {
                console.error('AutoRefresh: Update failed:', error);
            }
        }
        
        // Функция обновления счётчиков дашборда
        function updateDashboardCounters(data) {
            // VPN активных
            const vpnCounter = document.querySelector('[data-counter="vpn-active"]');
            if (vpnCounter && data.vpn_active !== undefined) {
                vpnCounter.textContent = data.vpn_active;
            }
            
            // RDP активных
            const rdpCounter = document.querySelector('[data-counter="rdp-active"]');
            if (rdpCounter && data.rdp_active !== undefined) {
                rdpCounter.textContent = data.rdp_active;
            }
            
            // SMB файлов
            const smbCounter = document.querySelector('[data-counter="smb-files"]');
            if (smbCounter && data.smb_files !== undefined) {
                smbCounter.textContent = data.smb_files;
            }
            
            // MikroTik устройств
            const mikrotikCounter = document.querySelector('[data-counter="mikrotik-devices"]');
            if (mikrotikCounter && data.mikrotik_devices !== undefined) {
                mikrotikCounter.textContent = data.mikrotik_devices;
            }
            
            console.log('AutoRefresh: Counters updated');
        }
        
        // Функция обновления списков пользователей и файлов
        async function updateDashboardLists() {
            console.log('AutoRefresh: Updating dashboard lists...');
            
            try {
                // Обновляем VPN пользователей
                await updateVpnUsersList();
                
                // Обновляем RDP пользователей
                await updateRdpUsersList();
                
                // Обновляем SMB файлы
                await updateSmbFilesList();
                
                console.log('AutoRefresh: Lists updated successfully');
            } catch (error) {
                console.error('AutoRefresh: Lists update failed:', error);
            }
        }
        
        // Обновление списка VPN пользователей
        async function updateVpnUsersList() {
            try {
                const response = await fetch('/api/vpn/sessions');
                if (!response.ok) return;
                
                const data = await response.json();
                const vpnUsersContainer = document.querySelector('.card-body .mt-2.small');
                
                if (vpnUsersContainer && data.data && data.data.length > 0) {
                    // Дедупликация пользователей по имени
                    const uniqueUsers = [];
                    const seenUsers = new Set();
                    
                    for (const session of data.data) {
                        if (session.username && !seenUsers.has(session.username)) {
                            seenUsers.add(session.username);
                            uniqueUsers.push(session);
                        }
                    }
                    
                    const userLinks = uniqueUsers.slice(0, 5).map(session => 
                        `<a href="/vpn/user/${session.username}" class="me-2">${session.username}</a>`
                    ).join('');
                    
                    vpnUsersContainer.innerHTML = `<strong>Сейчас:</strong> ${userLinks}`;
                }
            } catch (error) {
                console.error('AutoRefresh: VPN users update failed:', error);
            }
        }
        
        // Обновление списка RDP пользователей
        async function updateRdpUsersList() {
            try {
                const response = await fetch('/api/rdp/sessions');
                if (!response.ok) return;
                
                const data = await response.json();
                const rdpUsersContainers = document.querySelectorAll('.card.border-success .mt-2.small');
                
                if (rdpUsersContainers.length > 0 && data.data && data.data.length > 0) {
                    // Дедупликация пользователей по имени
                    const uniqueUsers = [];
                    const seenUsers = new Set();
                    
                    for (const session of data.data) {
                        if (session.username && !seenUsers.has(session.username)) {
                            seenUsers.add(session.username);
                            uniqueUsers.push(session);
                        }
                    }
                    
                    const userLinks = uniqueUsers.slice(0, 5).map(session => 
                        `<a href="/rdp/user/${session.username}" class="me-2">${session.username}</a>`
                    ).join('');
                    
                    rdpUsersContainers[0].innerHTML = `<strong>Сейчас:</strong> ${userLinks}`;
                }
            } catch (error) {
                console.error('AutoRefresh: RDP users update failed:', error);
            }
        }
        
        // Обновление списка SMB файлов
        async function updateSmbFilesList() {
            try {
                const response = await fetch('/api/smb/sessions');
                if (!response.ok) return;
                
                const data = await response.json();
                // Используем уникальный ID для SMB файлов на главной странице
                const smbFilesContainer = document.getElementById('smb-files-list');
                
                if (smbFilesContainer && data.data && data.data.length > 0) {
                    // Дедупликация файлов по пути
                    const uniqueFiles = [];
                    const seenFiles = new Set();
                    
                    for (const session of data.data) {
                        if (session.path && !seenFiles.has(session.path)) {
                            seenFiles.add(session.path);
                            uniqueFiles.push(session);
                        }
                    }
                    
                    // Показываем больше файлов (до 5 вместо 3) и убираем ограничение ширины
                    const fileLinks = uniqueFiles.slice(0, 5).map(session => {
                        const fileName = session.path ? session.path.split('\\').pop() : 'Unknown';
                        // Используем правильный URL для скачивания файла, если есть file_id
                        const fileUrl = session.file_id ? `/smb/download/${session.file_id}` : `/smb/file/${session.session_id}`;
                        return `<a href="${fileUrl}" class="me-2" title="${session.path}">${fileName}</a>`;
                    }).join('');
                    
                    smbFilesContainer.innerHTML = `<strong>Сейчас:</strong> ${fileLinks}`;
                } else {
                    console.log('AutoRefresh: SMB container not found or no data');
                }
            } catch (error) {
                console.error('AutoRefresh: SMB files update failed:', error);
            }
        }
        
        // Первое обновление сразу
        updateDashboard();
        
        // Запускаем автообновление
        setInterval(updateDashboard, interval);
        console.log(`AutoRefresh: Started with interval ${interval}ms`);
    }
});
