
# ───── Telegram ─────
BOT_TOKEN = "8151857752:AAGJYcyTQbRGU0DwO1xFMd-qa9ho0ehPnGI"
CHAT_ID   = "51578249"
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Мониторинг новых дел во 2-м КСОЮ.
Рабочие файлы: /var/lib/court_notify/
"""

import json
import sys
import pathlib
import requests
import pandas as pd
from bs4 import BeautifulSoup
from typing import Tuple, Set, List, Dict

# ─── Константы ───
URL = (
    "https://2kas.sudrf.ru/modules.php?name=sud_delo&srv_num=1&name_op=r"
    "&delo_id=2800001&case_type=0&new=2800001&G33_PARTS__NAMESS=%CF%F3%F1%F2%EE%F8%E8%EB%EE%E2"
    "&g33_case__CASE_NUMBERSS=&g33_case__JUDICIAL_UIDSS=&delo_table=g33_case"
    "&g33_case__ENTRY_DATE1D=&g33_case__ENTRY_DATE2D=&G33_CASE__COURT_I_REGION_ID="
    "&G33_CASE__COURT_I=&G33_CASE__CASE_NUMBER_ISS=&g33_case__RESULT_DATE_I1D="
    "&g33_case__RESULT_DATE_I2D=&G33_CASE__M_SUB_TYPE=&G33_CASE__WRIT_TYPE="
    "&G33_CASE__VSRFID_NOTPOST=&G33_CASE__JUDGE=&g33_case__RESULT_DATE1D="
    "&g33_case__RESULT_DATE2D=&G33_CASE__RESULT=&G33_CASE__RESULT_FOR_I_VERDICT_ID="
    "&G33_CASE__RESULT_FOR_A_VERDICT_ID=&G33_CASE__BUILDING_ID=&G33_CASE__COURT_STRUCT="
    "&G33_CASE__JUDGE_I=&G33_EVENT__EVENT_NAME=&G33_EVENT__EVENT_DATEDD=&G33_PARTS__PARTS_TYPE="
    "&G33_PARTS__INN_STRSS=&G33_PARTS__KPP_STRSS=&G33_PARTS__OGRN_STRSS=&G33_PARTS__OGRNIP_STRSS="
    "&G33_RKN_ACCESS_RESTRICTION__RKN_REASON=&g33_rkn_access_restriction__RKN_RESTRICT_URLSS="
    "&G3_DOCUMENT__PUBL_DATE1D=&G3_DOCUMENT__PUBL_DATE2D=&G3_DOCUMENT__VALIDITY_DATE1D="
    "&G3_DOCUMENT__VALIDITY_DATE2D=&Submit=%CD%E0%E9%F2%E8"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "YandexBrowser/24.4.5.368 Yowser/2.5 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}

# ─── Пути ───
DATA_DIR = pathlib.Path("/var/lib/court_notify")
DATA_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = DATA_DIR / "known_cases.json"
LATEST_CSV   = DATA_DIR / "court_cases_latest.csv"

# ─── Вспомогательные функции ───
def smart_decode(raw: bytes) -> str:
    for enc in ("cp1251", "utf-8", "utf-8-sig", "windows-1251"):
        try:
            txt = raw.decode(enc)
            if txt.count("�") < 0.01 * len(txt):
                return txt
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def fetch_html() -> str:
    r = requests.get(URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return smart_decode(r.content)


def parse_table(html: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "lxml")
    table = None
    for t in soup.find_all("table"):
        ths = t.find_all("th")
        if len(ths) >= 6 and "№" in ths[0].get_text():
            table = t
            break
    if table is None:
        raise RuntimeError("Таблица с результатами не найдена")

    rows = []  # type: List[Dict[str, str]]
    for tr in table.find_all("tr")[1:]:
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) >= 6:
            rows.append(
                {
                    "№ дела": cells[0],
                    "Дата поступления": cells[1],
                    "Категория/Заявитель/Суд и № в 1-й инстанции": cells[2],
                    "Судья": cells[3],
                    "Дата решения": cells[4],
                    "Решение": cells[5],
                }
            )
    if not rows:
        raise RuntimeError("Таблица найдена, но строк нет")
    return pd.DataFrame(rows)


def load_history() -> Tuple[Set[str], bool]:
    if HISTORY_FILE.exists():
        nums = set(json.loads(HISTORY_FILE.read_text(encoding="utf-8")))
        return nums, False
    return set(), True


def save_history(nums: Set[str]) -> None:
    HISTORY_FILE.write_text(
        json.dumps(sorted(nums), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

MAX_LEN = 4090          # чуть меньше 4096, чтобы оставить запас

def send_telegram(text: str) -> None:
    url = "https://api.telegram.org/bot{}/sendMessage".format(BOT_TOKEN)

    # разбиваем на части, не разрывая строки посередине
    while text:
        chunk = text[:MAX_LEN]
        if len(text) > MAX_LEN:
            # пытаемся «откатиться» до последнего перевода строки
            split_idx = chunk.rfind("\n")
            if split_idx > 0:
                chunk = text[:split_idx]
        resp = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": chunk
            },
            timeout=20,
        )
        # для отладки: печатаем тело ответа при ошибках
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            print("⚠️ Telegram error:", resp.text, file=sys.stderr)
            raise

        text = text[len(chunk):].lstrip("\n")


# ─── Main ───
def main() -> None:
    try:
        df = parse_table(fetch_html())
    except Exception as exc:
        print("❌ Ошибка: {}".format(exc), file=sys.stderr)
        sys.exit(1)

    df.to_csv(LATEST_CSV, index=False, encoding="utf-8-sig")

    known, first_run = load_history()
    new_df = df if first_run else df[~df["№ дела"].isin(known)]

    if new_df.empty:
        print("Новых дел нет.")
        return

    header = (
        "📑 Первый запуск — все текущие дела"
        if first_run
        else "📑 Новые дела во 2-м КСОЮ"
    )
    msg = [header]

    for _, r in new_df.iterrows():
        msg.extend(
            [
                "",
                "№ дела: {}".format(r["№ дела"]),
                "Дата поступления: {}".format(r["Дата поступления"]),
                "Категория/Заявитель: {}".format(
                    r["Категория/Заявитель/Суд и № в 1-й инстанции"]
                ),
                "Судья: {}".format(r["Судья"] or "—"),
                "Дата решения: {}".format(r["Дата решения"] or "—"),
                "Решение: {}".format(r["Решение"] or "—"),
            ]
        )

    send_telegram("\n".join(msg))
    save_history(known.union(set(new_df["№ дела"])))
    print("Отправлено {} дел.".format(len(new_df)))


if __name__ == "__main__":
    main()
