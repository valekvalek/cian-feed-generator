# CIAN Feed Generator

Автоматический генератор XML-фида для ЦИАН из API сайтов ЖК Легенда.

## Что делает

- Каждый час запрашивает свободные квартиры через API сайтов ЖК
- Формирует `cian_feed.xml` по стандарту **ЦИАН XML v2**
- Коммитит обновлённый файл в репозиторий автоматически

## Структура

```
cian-feed-generator/
├── fetch_feed.py                  # Основной скрипт
├── cian_feed.xml                  # Генерируемый фид (обновляется автоматически)
├── .github/workflows/
│   └── generate_feed.yml          # GitHub Actions: запуск каждый час
└── README.md
```

## Первоначальная настройка

### 1. Добавить ЦИАН-ID ЖК в Secrets

Перейти в репозитории: **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Значение |
|---|---|
| `CIAN_ID_MARUSINO` | Числовой ID ЖК «Легенда Марусино» в базе ЦИАН |
| `CIAN_ID_KORENEVO` | Числовой ID ЖК «Легенда Коренево» в базе ЦИАН |

### 2. Уточнить API-эндпоинты

В файле `fetch_feed.py` в разделе `PROJECTS` указаны предполагаемые URL:
```python
"api_url": "https://legenda-korenevo.ru/api/real-estates/"
```
Проверьте точный URL через DevTools (вкладка Network → Fetch/XHR) и при необходимости скорректируйте.

### 3. Ручной запуск

GitHub → **Actions** → **Generate CIAN Feed** → **Run workflow**

## Локальный запуск

```bash
pip install requests

# Опционально: задать ЦИАН-ID через переменные окружения
export CIAN_ID_MARUSINO=1234567
export CIAN_ID_KORENEVO=7654321

python fetch_feed.py
```

## Расписание

Фид обновляется **каждый час** автоматически через GitHub Actions.
Для изменения частоты отредактируйте `cron` в `.github/workflows/generate_feed.yml`.
