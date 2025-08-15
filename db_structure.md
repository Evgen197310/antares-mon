# Структура базы данных мониторинга

## Базы данных
- `smbstat` - SMB мониторинг файлов
- `rdpstat` - RDP сессии пользователей
- `vpnstat` - VPN подключения
- `monitoring` - аутентификация и общие данные

## SMBSTAT Database

### Таблица: smb_files
```sql
CREATE TABLE `smb_files` (
  `id` int NOT NULL AUTO_INCREMENT,
  `path` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `hash` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `norm_path` text COLLATE utf8mb4_unicode_ci,  -- ⚠️ ВАЖНО: нормализованный путь для поиска
  PRIMARY KEY (`id`),
  UNIQUE KEY `path` (`path`(255)),
  KEY `idx_norm_path` (`norm_path`(255))        -- ⚠️ ИНДЕКС для быстрого поиска
)
```

### Таблица: smb_users
```sql
CREATE TABLE `smb_users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`)
)
```

### Таблица: smb_clients
```sql
CREATE TABLE `smb_clients` (
  `id` int NOT NULL AUTO_INCREMENT,
  `host` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `ip` varchar(45) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `host` (`host`)
)
```

### Таблица: active_smb_sessions (АКТИВНЫЕ сессии)
```sql
CREATE TABLE `active_smb_sessions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `file_id` int NOT NULL,
  `user_id` int NOT NULL,
  `client_id` int NOT NULL,
  `session_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `open_time` datetime NOT NULL,
  `initial_size` bigint DEFAULT NULL,
  `last_seen` datetime NOT NULL,
  `open_in_rdp` tinyint(1) NOT NULL DEFAULT '0',  -- ⚠️ ВАЖНО: встроенный флаг RDP!
  PRIMARY KEY (`id`),
  KEY `file_id` (`file_id`),
  KEY `client_id` (`client_id`),
  KEY `idx_smb_active_user_open` (`user_id`,`open_time`),
  CONSTRAINT `active_smb_sessions_ibfk_1` FOREIGN KEY (`file_id`) REFERENCES `smb_files` (`id`),
  CONSTRAINT `active_smb_sessions_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `smb_users` (`id`),
  CONSTRAINT `active_smb_sessions_ibfk_3` FOREIGN KEY (`client_id`) REFERENCES `smb_clients` (`id`)
)
```

### Таблица: smb_session_history (ИСТОРИЯ сессий)
```sql
CREATE TABLE `smb_session_history` (
  `id` int NOT NULL AUTO_INCREMENT,
  `file_id` int NOT NULL,
  `user_id` int NOT NULL,
  `client_id` int NOT NULL,
  `session_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `open_time` datetime NOT NULL,
  `close_time` datetime NOT NULL,
  `duration_sec` int DEFAULT NULL,
  `initial_size` bigint DEFAULT NULL,
  `final_size` bigint DEFAULT NULL,
  `open_in_rdp` tinyint(1) NOT NULL DEFAULT '0',  -- ⚠️ ВАЖНО: встроенный флаг RDP!
  PRIMARY KEY (`id`),
  KEY `file_id` (`file_id`),
  KEY `client_id` (`client_id`),
  KEY `idx_smb_hist_user_open` (`user_id`,`open_time`),
  KEY `idx_user_open_rdp` (`user_id`,`open_in_rdp`,`open_time`),  -- ⚠️ ИНДЕКС для RDP-фильтрации
  CONSTRAINT `smb_session_history_ibfk_1` FOREIGN KEY (`file_id`) REFERENCES `smb_files` (`id`),
  CONSTRAINT `smb_session_history_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `smb_users` (`id`),
  CONSTRAINT `smb_session_history_ibfk_3` FOREIGN KEY (`client_id`) REFERENCES `smb_clients` (`id`)
)
```

## RDPSTAT Database

### Таблица: rdp_active_sessions
```sql
CREATE TABLE `rdp_active_sessions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `domain` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `collection_name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `remote_host` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `login_time` datetime NOT NULL,
  `connection_type` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `last_update` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `state` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `session_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `notes` text COLLATE utf8mb4_unicode_ci,
  `duration_seconds` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_active` (`username`,`domain`,`collection_name`),
  KEY `idx_rdp_active_user_login` (`username`,`login_time`)
)
```

### Таблица: rdp_session_history
```sql
CREATE TABLE `rdp_session_history` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `domain` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `session_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `collection_name` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `remote_host` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `connection_type` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `login_time` datetime DEFAULT NULL,
  `logout_time` datetime DEFAULT NULL,
  `duration_seconds` int DEFAULT NULL,
  `last_input_time` datetime DEFAULT NULL,
  `idle_seconds` int DEFAULT '0',
  `state` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `notes` text COLLATE utf8mb4_unicode_ci,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_session` (`username`,`collection_name`,`remote_host`,`login_time`,`connection_type`),
  KEY `username` (`username`),
  KEY `collection_name` (`collection_name`),
  KEY `session_id` (`session_id`),
  KEY `idx_rdp_hist_user_login_logout` (`username`,`login_time`,`logout_time`)
)
```

## ВАЖНЫЕ НАХОДКИ для поиска:

### 1. Встроенное поле RDP
- ✅ `smb_session_history.open_in_rdp` - встроенный boolean флаг
- ✅ `active_smb_sessions.open_in_rdp` - встроенный boolean флаг
- ✅ Индекс `idx_user_open_rdp` для быстрой фильтрации по RDP

### 2. Нормализованные пути
- ✅ `smb_files.norm_path` - готовое поле для поиска
- ✅ Индекс `idx_norm_path` для быстрого поиска

### 3. Оптимизированные индексы
- ✅ `idx_smb_hist_user_open` для поиска по пользователю и времени
- ✅ `idx_user_open_rdp` для RDP-фильтрации
- ✅ `idx_norm_path` для поиска по пути

### 4. Логика определения "изменён"
- Сравнивать `initial_size` и `final_size` в истории
- `final_size IS NULL` = файл ещё не закрыт (может считаться изменённым)

## SQL для поиска (правильный подход):

```sql
-- Поиск по всей истории с фильтрами
SELECT 
    f.id AS file_id,
    f.path,
    f.norm_path,
    u.id AS user_id,
    u.username,
    h.open_time,
    h.close_time,
    h.initial_size,
    h.final_size,
    h.open_in_rdp,
    CASE WHEN (h.final_size != h.initial_size OR h.final_size IS NULL) THEN 1 ELSE 0 END AS is_modified
FROM smb_session_history h
JOIN smb_files f ON h.file_id = f.id
JOIN smb_users u ON h.user_id = u.id
WHERE
    -- Поиск по файлу (используем norm_path если есть)
    (f.norm_path LIKE '%термин%' OR LOWER(REPLACE(f.path, '\\', '/')) LIKE '%термин%')
    -- Поиск по пользователю (нормализация домена)
    AND LOWER(CASE WHEN INSTR(u.username, '\\') > 0 THEN SUBSTRING_INDEX(u.username, '\\', -1) ELSE u.username END) LIKE '%пользователь%'
    -- Фильтр изменённых
    AND (h.final_size != h.initial_size OR h.final_size IS NULL)
    -- Фильтр RDP (использовать встроенное поле!)
    AND h.open_in_rdp = 1
ORDER BY h.open_time DESC
LIMIT 10 OFFSET 0;
```
