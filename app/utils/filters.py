from datetime import datetime, timedelta

def pretty_time(seconds):
    """Форматирование времени в человекочитаемый вид"""
    if not seconds:
        return "-"
    
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    
    parts = []
    if days:
        parts.append(f"{days} д.")
    if hours:
        parts.append(f"{hours} ч.")
    if minutes:
        parts.append(f"{minutes} мин.")
    if seconds or not parts:
        parts.append(f"{seconds} сек.")
    
    return ' '.join(parts)

def rusdatetime(dt):
    """Форматирование даты и времени на русском"""
    if not dt:
        return ''
    
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace('T', ' '))
        except:
            return dt
    
    months = [
        'янв', 'фев', 'мар', 'апр', 'май', 'июн',
        'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'
    ]
    
    return f"{dt.day} {months[dt.month-1]} {dt.year} {dt.hour:02d}:{dt.minute:02d}"

def human_filesize(size):
    """Форматирование размера файла"""
    if not size:
        return "0 Б"
    
    size = int(size)
    for unit in ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} ПБ"

def basename(path):
    """Получить имя файла из полного пути"""
    if not path:
        return ""
    return path.split('/')[-1].split('\\')[-1]

def dt_to_str(dt):
    """Преобразование datetime в строку для HTML input"""
    if not dt:
        return ''
    return dt.strftime('%Y-%m-%dT%H:%M:%S')

def register_filters(app):
    """Регистрация всех фильтров в Flask приложении"""
    app.jinja_env.filters['pretty_time'] = pretty_time
    app.jinja_env.filters['rusdatetime'] = rusdatetime
    app.jinja_env.filters['human_filesize'] = human_filesize
    app.jinja_env.filters['basename'] = basename
    app.jinja_env.filters['dt_to_str'] = dt_to_str
    app.jinja_env.filters['datetime_format'] = datetime_format
    app.jinja_env.filters['time_ago'] = time_ago
    app.jinja_env.filters['duration_format'] = duration_format

def datetime_format(value, fmt='%Y-%m-%d %H:%M:%S'):
    """Форматирует datetime/строку в заданный формат."""
    if not value:
        return ''
    if isinstance(value, str):
        try:
            # Поддержка ISO-строк
            value = datetime.fromisoformat(value.replace('T', ' '))
        except Exception:
            return value
    try:
        return value.strftime(fmt)
    except Exception:
        return str(value)

def time_ago(value):
    """Возвращает человекочитаемую разницу времени: '5 мин. назад'"""
    if not value:
        return ''
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('T', ' '))
        except Exception:
            return value
    delta = datetime.now() - value
    if delta < timedelta(seconds=60):
        return f"{int(delta.total_seconds())} сек. назад"
    if delta < timedelta(hours=1):
        minutes = int(delta.total_seconds() // 60)
        return f"{minutes} мин. назад"
    if delta < timedelta(days=1):
        hours = int(delta.total_seconds() // 3600)
        return f"{hours} ч. назад"
    days = delta.days
    return f"{days} дн. назад"

def duration_format(seconds):
    """Форматирует длительность в секундах в компактный вид: 1ч 23м 45с"""
    if seconds is None or seconds == '':
        return '-'
    try:
        seconds = int(seconds)
    except Exception:
        return str(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    parts = []
    if h:
        parts.append(f"{h}ч")
    if m:
        parts.append(f"{m}м")
    if s or not parts:
        parts.append(f"{s}с")
    return ' '.join(parts)
