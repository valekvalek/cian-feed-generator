# CIAN Feed Generator

Автоматический генератор XML-фидов CIAN XML v2 из API трёх застройщиков.

## Источники и актуальные фиды

| Источник | Проект | Канонический файл |
|---|---|---|
| Легенда | Марусино | `legenda/marusino_feed.xml` |
| Легенда | Коренево | `legenda/korenevo_feed.xml` |
| Легенда | ГК Некрасовка (сводный) | `legenda/nekrasovka_feed.xml` |
| Доминанта | Свет | `dominanta/svet_feed.xml` |
| Доминанта | Сводный фид | `dominanta/dominanta_feed.xml` |
| Aeon | Ривер Парк Бизнес | `aeon/aeon_riverpark_feed.xml` |

Для CIAN используйте Raw URL нужного канонического файла, например:

```text
https://raw.githubusercontent.com/valekvalek/cian-feed-generator/main/legenda/nekrasovka_feed.xml
```

Корневые XML-файлы и `legenda/svet_feed.xml` / `legenda/dominanta_feed.xml`
оставлены как временные совместимые адреса. Workflow синхронизирует их с
каноническими файлами. Для новых интеграций эти адреса использовать не следует.

## Как работает обновление

GitHub Actions запускает три генератора, валидирует новые XML, синхронизирует
устаревшие адреса и только затем коммитит результат. При ошибке API, некорректном
JSON, пустом фиде, повторяющихся ID, неправильном CIAN ID или падении числа
объектов более чем на 50% предыдущая рабочая версия не заменяется.

Расписание настроено через cron раз в час. GitHub не гарантирует точное время
запуска scheduled workflow, поэтому это не следует считать часовым SLA.

## Обязательные Secrets

В **Settings → Secrets and variables → Actions** должны быть заданы:

| Secret | Назначение |
|---|---|
| `CIAN_ID_MARUSINO` | ЖК «Легенда Марусино» |
| `CIAN_ID_KORENEVO` | ЖК «Легенда Коренево» |
| `CIAN_ID_SVET` | ЖК «Свет» |
| `CIAN_ID_AEON` | ЖК «Ривер Парк Бизнес» |

Все значения обязательны и должны быть числовыми. Они являются идентификаторами
объектов CIAN и попадают в публичные XML-файлы — не используйте здесь пароли или
API-ключи.

## Локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export CIAN_ID_MARUSINO=1234567
export CIAN_ID_KORENEVO=7654321
export CIAN_ID_SVET=2345678
export CIAN_ID_AEON=3456789

python -m legenda.fetch_feed
python -m dominanta.fetch_dominanta
python -m aeon.fetch_aeon
python validate_feeds.py
```

Совместимые команды `python fetch_feed.py`, `python fetch_dominanta.py` и
`python fetch_aeon.py` также запускают соответствующие генераторы.

## Проверки

```bash
python -m unittest discover -s tests -v
python validate_feeds.py
python sync_legacy_feeds.py
python validate_feeds.py --include-legacy
```

Тесты используют сохранённые примеры ответов API и не обращаются к сайтам
застройщиков.
