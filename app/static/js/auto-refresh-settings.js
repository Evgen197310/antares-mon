/**
 * Настройки автообновления для пользователей
 */

class AutoRefreshSettings {
    constructor() {
        this.storageKey = 'autoRefreshSettings';
        this.defaultSettings = {
            enabled: true,
            interval: 30000,
            method: 'polling',
            showNotifications: true,
            pauseOnInactive: true,
            customIntervals: {
                dashboard: 15000,
                activeSessions: 15000,
                history: 60000,
                stats: 60000
            }
        };
        
        this.settings = this.loadSettings();
        this.init();
    }
    
    init() {
        this.createSettingsModal();
        this.bindEvents();
    }
    
    loadSettings() {
        try {
            const saved = localStorage.getItem(this.storageKey);
            return saved ? { ...this.defaultSettings, ...JSON.parse(saved) } : this.defaultSettings;
        } catch (e) {
            console.error('Error loading auto-refresh settings:', e);
            return this.defaultSettings;
        }
    }
    
    saveSettings() {
        try {
            localStorage.setItem(this.storageKey, JSON.stringify(this.settings));
            this.applySettings();
        } catch (e) {
            console.error('Error saving auto-refresh settings:', e);
        }
    }
    
    applySettings() {
        if (window.autoRefresh) {
            // Применяем настройки к текущему экземпляру автообновления
            window.autoRefresh.interval = this.getIntervalForCurrentPage();
            window.autoRefresh.method = this.settings.method;
            
            if (this.settings.enabled) {
                window.autoRefresh.start();
            } else {
                window.autoRefresh.stop();
            }
        }
        
        // Отправляем событие об изменении настроек
        window.dispatchEvent(new CustomEvent('autoRefreshSettingsChanged', {
            detail: this.settings
        }));
    }
    
    getIntervalForCurrentPage() {
        const path = window.location.pathname;
        
        if (path === '/' || path.includes('dashboard')) {
            return this.settings.customIntervals.dashboard;
        } else if (path.includes('active-sessions') || path.includes('/vpn/') || path.includes('/rdp/') || path.includes('/smb/')) {
            return this.settings.customIntervals.activeSessions;
        } else if (path.includes('history')) {
            return this.settings.customIntervals.history;
        } else if (path.includes('stats')) {
            return this.settings.customIntervals.stats;
        }
        
        return this.settings.interval;
    }
    
    createSettingsModal() {
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.id = 'autoRefreshSettingsModal';
        modal.setAttribute('tabindex', '-1');
        modal.innerHTML = `
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="fas fa-cog me-2"></i>
                            Настройки автообновления
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <form id="autoRefreshSettingsForm">
                            <!-- Основные настройки -->
                            <div class="mb-4">
                                <h6 class="fw-bold mb-3">Основные настройки</h6>
                                
                                <div class="form-check mb-3">
                                    <input class="form-check-input" type="checkbox" id="enableAutoRefresh" 
                                           ${this.settings.enabled ? 'checked' : ''}>
                                    <label class="form-check-label" for="enableAutoRefresh">
                                        Включить автообновление
                                    </label>
                                </div>
                                
                                <div class="mb-3">
                                    <label for="refreshMethod" class="form-label">Метод обновления</label>
                                    <select class="form-select" id="refreshMethod">
                                        <option value="polling" ${this.settings.method === 'polling' ? 'selected' : ''}>
                                            Polling (HTTP запросы)
                                        </option>
                                        <option value="websocket" ${this.settings.method === 'websocket' ? 'selected' : ''}>
                                            WebSocket (экспериментально)
                                        </option>
                                    </select>
                                    <div class="form-text">
                                        Polling более стабилен, WebSocket быстрее реагирует на изменения
                                    </div>
                                </div>
                                
                                <div class="form-check mb-3">
                                    <input class="form-check-input" type="checkbox" id="showNotifications"
                                           ${this.settings.showNotifications ? 'checked' : ''}>
                                    <label class="form-check-label" for="showNotifications">
                                        Показывать уведомления об ошибках
                                    </label>
                                </div>
                                
                                <div class="form-check mb-3">
                                    <input class="form-check-input" type="checkbox" id="pauseOnInactive"
                                           ${this.settings.pauseOnInactive ? 'checked' : ''}>
                                    <label class="form-check-label" for="pauseOnInactive">
                                        Приостанавливать при неактивной вкладке
                                    </label>
                                </div>
                            </div>
                            
                            <!-- Интервалы обновления -->
                            <div class="mb-4">
                                <h6 class="fw-bold mb-3">Интервалы обновления</h6>
                                
                                <div class="mb-3">
                                    <label for="dashboardInterval" class="form-label">
                                        Главная страница (секунды)
                                    </label>
                                    <input type="number" class="form-control" id="dashboardInterval" 
                                           min="5" max="300" value="${this.settings.customIntervals.dashboard / 1000}">
                                    <div class="form-text">Рекомендуется: 15-30 секунд</div>
                                </div>
                                
                                <div class="mb-3">
                                    <label for="activeSessionsInterval" class="form-label">
                                        Активные сессии (секунды)
                                    </label>
                                    <input type="number" class="form-control" id="activeSessionsInterval" 
                                           min="5" max="300" value="${this.settings.customIntervals.activeSessions / 1000}">
                                    <div class="form-text">Рекомендуется: 10-20 секунд</div>
                                </div>
                                
                                <div class="mb-3">
                                    <label for="historyInterval" class="form-label">
                                        История (секунды)
                                    </label>
                                    <input type="number" class="form-control" id="historyInterval" 
                                           min="30" max="600" value="${this.settings.customIntervals.history / 1000}">
                                    <div class="form-text">Рекомендуется: 60-120 секунд</div>
                                </div>
                                
                                <div class="mb-3">
                                    <label for="statsInterval" class="form-label">
                                        Статистика (секунды)
                                    </label>
                                    <input type="number" class="form-control" id="statsInterval" 
                                           min="30" max="600" value="${this.settings.customIntervals.stats / 1000}">
                                    <div class="form-text">Рекомендуется: 60-300 секунд</div>
                                </div>
                            </div>
                            
                            <!-- Предустановки -->
                            <div class="mb-4">
                                <h6 class="fw-bold mb-3">Быстрые настройки</h6>
                                <div class="btn-group w-100" role="group">
                                    <button type="button" class="btn btn-outline-primary" data-preset="fast">
                                        Быстро
                                    </button>
                                    <button type="button" class="btn btn-outline-secondary" data-preset="normal">
                                        Обычно
                                    </button>
                                    <button type="button" class="btn btn-outline-success" data-preset="slow">
                                        Медленно
                                    </button>
                                </div>
                                <div class="form-text mt-2">
                                    Быстро: 10/10/30/60 сек | Обычно: 15/15/60/120 сек | Медленно: 30/30/120/300 сек
                                </div>
                            </div>
                        </form>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                            Отмена
                        </button>
                        <button type="button" class="btn btn-primary" id="saveSettings">
                            Сохранить
                        </button>
                        <button type="button" class="btn btn-outline-warning" id="resetSettings">
                            Сброс
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
    }
    
    bindEvents() {
        // Добавляем кнопку настроек в индикатор автообновления
        setTimeout(() => {
            const refreshControls = document.querySelector('.refresh-controls');
            if (refreshControls) {
                const settingsBtn = document.createElement('button');
                settingsBtn.className = 'btn btn-sm btn-outline-secondary';
                settingsBtn.innerHTML = '<i class="fas fa-cog"></i>';
                settingsBtn.title = 'Настройки автообновления';
                settingsBtn.setAttribute('data-bs-toggle', 'modal');
                settingsBtn.setAttribute('data-bs-target', '#autoRefreshSettingsModal');
                refreshControls.appendChild(settingsBtn);
            }
        }, 1000);
        
        // Сохранение настроек
        document.getElementById('saveSettings').addEventListener('click', () => {
            this.saveFormSettings();
            const modal = bootstrap.Modal.getInstance(document.getElementById('autoRefreshSettingsModal'));
            modal.hide();
        });
        
        // Сброс настроек
        document.getElementById('resetSettings').addEventListener('click', () => {
            this.resetToDefaults();
        });
        
        // Предустановки
        document.querySelectorAll('[data-preset]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.applyPreset(e.target.dataset.preset);
            });
        });
    }
    
    saveFormSettings() {
        const form = document.getElementById('autoRefreshSettingsForm');
        
        this.settings = {
            enabled: form.querySelector('#enableAutoRefresh').checked,
            method: form.querySelector('#refreshMethod').value,
            showNotifications: form.querySelector('#showNotifications').checked,
            pauseOnInactive: form.querySelector('#pauseOnInactive').checked,
            customIntervals: {
                dashboard: parseInt(form.querySelector('#dashboardInterval').value) * 1000,
                activeSessions: parseInt(form.querySelector('#activeSessionsInterval').value) * 1000,
                history: parseInt(form.querySelector('#historyInterval').value) * 1000,
                stats: parseInt(form.querySelector('#statsInterval').value) * 1000
            }
        };
        
        this.saveSettings();
        this.showNotification('Настройки сохранены', 'success');
    }
    
    resetToDefaults() {
        this.settings = { ...this.defaultSettings };
        this.updateFormValues();
        this.saveSettings();
        this.showNotification('Настройки сброшены к значениям по умолчанию', 'info');
    }
    
    applyPreset(preset) {
        const presets = {
            fast: { dashboard: 10, activeSessions: 10, history: 30, stats: 60 },
            normal: { dashboard: 15, activeSessions: 15, history: 60, stats: 120 },
            slow: { dashboard: 30, activeSessions: 30, history: 120, stats: 300 }
        };
        
        const intervals = presets[preset];
        if (intervals) {
            document.getElementById('dashboardInterval').value = intervals.dashboard;
            document.getElementById('activeSessionsInterval').value = intervals.activeSessions;
            document.getElementById('historyInterval').value = intervals.history;
            document.getElementById('statsInterval').value = intervals.stats;
            
            this.showNotification(`Применена предустановка: ${preset}`, 'info');
        }
    }
    
    updateFormValues() {
        const form = document.getElementById('autoRefreshSettingsForm');
        if (!form) return;
        
        form.querySelector('#enableAutoRefresh').checked = this.settings.enabled;
        form.querySelector('#refreshMethod').value = this.settings.method;
        form.querySelector('#showNotifications').checked = this.settings.showNotifications;
        form.querySelector('#pauseOnInactive').checked = this.settings.pauseOnInactive;
        form.querySelector('#dashboardInterval').value = this.settings.customIntervals.dashboard / 1000;
        form.querySelector('#activeSessionsInterval').value = this.settings.customIntervals.activeSessions / 1000;
        form.querySelector('#historyInterval').value = this.settings.customIntervals.history / 1000;
        form.querySelector('#statsInterval').value = this.settings.customIntervals.stats / 1000;
    }
    
    showNotification(message, type = 'info') {
        if (!this.settings.showNotifications && type === 'error') return;
        
        const notification = document.createElement('div');
        notification.className = `alert alert-${type === 'error' ? 'danger' : type === 'success' ? 'success' : 'info'} alert-dismissible fade show`;
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
        
        setTimeout(() => {
            if (notification.parentNode) {
                notification.remove();
            }
        }, 3000);
    }
    
    getSettings() {
        return this.settings;
    }
}

// Инициализация настроек автообновления
window.AutoRefreshSettings = AutoRefreshSettings;

document.addEventListener('DOMContentLoaded', function() {
    window.autoRefreshSettings = new AutoRefreshSettings();
});
