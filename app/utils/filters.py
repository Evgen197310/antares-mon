from datetime import datetime

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
