# CIAN Feed Generator

Автоматический генератор XML-фидов CIAN XML v2 из API четырёх застройщиков.

## Источники и актуальные фиды

| Источник | Проект | Канонический файл |
|---|---|---|
| Легенда | Марусино | `legenda/marusino_feed.xml` |
| Легенда | Коренево | `legenda/korenevo_feed.xml` |
| Легенда | ГК Некрасовка (сводный) | `legenda/nekrasovka_feed.xml` |
| Доминанта | Свет | `dominanta/svet_feed.xml` |
| Доминанта | Сводный фид | `dominanta/dominanta_feed.xml` |
| Aeon | Ривер Парк Бизнес | `aeon/aeon_riverpark_feed.xml` |
| Sezar Group | СЕЗАР СИТИ | `sezar/sezar_city_feed.xml` |

Для CIAN используйте Raw URL нужного канонического файла, например:

```text
https://raw.githubusercontent.com/valekvalek/cian-feed-generator/main/legenda/nekrasovka_feed.xml
```

Корневые XML-файлы и `legenda/svet_feed.xml` / `legenda/dominanta_feed.xml`
оставлены как временные совместимые адреса. Workflow синхронизирует их с
каноническими файлами. Для новых интеграций эти адреса использовать не следует.

## Как работает обновление

Каждый фид запускается отдельным GitHub Actions workflow. Поэтому ошибка API,
секрета или данных одного ЖК не останавливает обновление остальных, а в Actions
видны отдельные статус и лог для каждого проекта.

| Workflow | Фид | Запуск (UTC) |
|---|---|---|
| `generate_marusino_feed.yml` | Легенда Марусино | каждый час в `:00` |
| `generate_korenevo_feed.yml` | Легенда Коренево | каждый час в `:05` |
| `generate_nekrasovka_feed.yml` | ГК Некрасовка (сводный) | каждый час в `:10` |
| `generate_sezar_feed.yml` | СЕЗАР СИТИ | каждый час в `:15` |
| `generate_svet_feed.yml` | Свет | каждый час в `:20` |
| `generate_aeon_feed.yml` | Ривер Парк Бизнес | каждый час в `:25` |

Сводная Некрасовка не обращается к API и не использует секреты: она собирается
из последних успешно опубликованных фидов Марусино и Коренево. Каждый workflow
валидирует только свой результат, синхронизирует только свои совместимые адреса
и коммитит только принадлежащие ему файлы. При некорректном JSON, пустом фиде,
повторяющихся ID, неправильном CIAN ID или падении числа объектов более чем на
50% предыдущая рабочая версия этого фида не заменяется.

GitHub не гарантирует точное время запуска scheduled workflow, поэтому расписание
не следует считать часовым SLA. Любой workflow также можно запустить отдельно
вручную через **Actions → нужный workflow → Run workflow**.

## Обязательные Secrets

В **Settings → Secrets and variables → Actions** должны быть заданы:

| Secret | Назначение |
|---|---|
| `CIAN_ID_MARUSINO` | ЖК «Легенда Марусино» |
| `CIAN_ID_KORENEVO` | ЖК «Легенда Коренево» |
| `CIAN_ID_SVET` | ЖК «Свет» |
| `CIAN_ID_AEON` | ЖК «Ривер Парк Бизнес» |
| `CIAN_ID_SEZAR_CITY` | ЖК «СЕЗАР СИТИ» (`4850351`) |

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
export CIAN_ID_SEZAR_CITY=4850351

python -m legenda.fetch_feed --project marusino
python -m legenda.fetch_feed --project korenevo
python -m legenda.build_nekrasovka
python -m dominanta.fetch_dominanta
python -m aeon.fetch_aeon
python -m sezar.fetch_sezar
python validate_feeds.py --only marusino --include-legacy
python validate_feeds.py --only korenevo --include-legacy
python validate_feeds.py --only nekrasovka --include-legacy
python validate_feeds.py --only svet --include-legacy
python validate_feeds.py --only aeon --include-legacy
python validate_feeds.py --only sezar
```

Совместимые команды `python fetch_feed.py`, `python fetch_dominanta.py`,
`python fetch_aeon.py` и `python fetch_sezar.py` также запускают соответствующие
генераторы.

## Проверки

```bash
python -m unittest discover -s tests -v
python validate_feeds.py
python sync_legacy_feeds.py
python validate_feeds.py --include-legacy
```

Тесты используют сохранённые примеры ответов API и не обращаются к сайтам
застройщиков.
