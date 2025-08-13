/**
 * Простое автообновление дашборда
 * Минимальная версия без сложной логики
 */

console.log('Simple AutoRefresh: Script loaded');

// Простая функция обновления данных
async function updateDashboard() {
    console.log('Simple AutoRefresh: Starting update...');
    
    try {
        const response = await fetch('/api/status');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        console.log('Simple AutoRefresh: Received data:', data);
        
        // Обновляем счётчики
        updateCounters(data);
        
        console.log('Simple AutoRefresh: Update completed');
        
    } catch (error) {
        console.error('Simple AutoRefresh: Error:', error);
    }
}

// Функция обновления счётчиков
function updateCounters(data) {
    console.log('Simple AutoRefresh: Updating counters...');
    
    // VPN активных
    const vpnCounter = document.querySelector('[data-counter="vpn-active"]');
    if (vpnCounter && data.vpn_active !== undefined) {
        console.log('Simple AutoRefresh: Updating VPN counter:', data.vpn_active);
        vpnCounter.textContent = data.vpn_active;
    }
    
    // RDP активных
    const rdpCounter = document.querySelector('[data-counter="rdp-active"]');
    if (rdpCounter && data.rdp_active !== undefined) {
        console.log('Simple AutoRefresh: Updating RDP counter:', data.rdp_active);
        rdpCounter.textContent = data.rdp_active;
    }
    
    // SMB файлов
    const smbCounter = document.querySelector('[data-counter="smb-files"]');
    if (smbCounter && data.smb_files !== undefined) {
        console.log('Simple AutoRefresh: Updating SMB counter:', data.smb_files);
        smbCounter.textContent = data.smb_files;
    }
    
    // Время последнего обновления
    if (data.last_update) {
        const lastUpdateElements = document.querySelectorAll('[data-counter="last-update"]');
        lastUpdateElements.forEach(el => {
            if (el) {
                console.log('Simple AutoRefresh: Updating last update time:', data.last_update);
                el.textContent = data.last_update;
            }
        });
    }
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    console.log('Simple AutoRefresh: DOM loaded, starting...');
    
    // Проверяем, что мы на главной странице
    const path = window.location.pathname;
    console.log('Simple AutoRefresh: Current path:', path);
    
    if (path === '/' || path === '/index' || path === '/dashboard') {
        console.log('Simple AutoRefresh: Dashboard detected, starting auto-refresh...');
        
        // Первое обновление сразу
        updateDashboard();
        
        // Автообновление каждые 15 секунд
        const interval = 15000; // 15 секунд
        console.log('Simple AutoRefresh: Setting interval:', interval);
        
        setInterval(() => {
            console.log('Simple AutoRefresh: Interval triggered');
            updateDashboard();
        }, interval);
        
        console.log('Simple AutoRefresh: Auto-refresh started successfully');
    } else {
        console.log('Simple AutoRefresh: Not a dashboard page, skipping auto-refresh');
    }
});

// Экспорт для тестирования
window.simpleAutoRefresh = {
    updateDashboard,
    updateCounters
};

console.log('Simple AutoRefresh: Script initialization complete');
