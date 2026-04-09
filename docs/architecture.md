# Архитектура MVP

## 1. Принцип

ParkRadar строится как demo-first MVP, который строго соответствует ТЗ и при этом честно масштабируется в production.

Пользовательский слой не показывает видео и скриншоты. Он показывает только агрегированную доступность парковки.

## 2. Основные компоненты

### User PWA

- ввод адреса или ссылки из карт
- получение количества свободных мест
- просмотр распределения по классам машин
- запуск trip monitoring
- получение уведомлений через pull

### Admin UI

- email/password авторизация
- управление реестром камер
- загрузка test-mode snapshots
- ручной ввод `free_a/free_b/free_c/free_d/free_pickup`
- просмотр статистики запросов и зон availability
- ручной запуск `due-check`

### Backend API

- `geo/resolve`
- `parking/search`
- `trip-monitoring/*`
- `test/*`
- `admin/*`
- `auth/*`

### Data Layer

- SQLite как быстрое и устойчивое хранилище MVP
- таблицы камер, снимков, запросов, поездок, уведомлений и auth

### Scheduler

- встроенный фоновый цикл внутри backend
- автоматически выполняет due-check для активных trip-сессий
- не требует внешнего cron для MVP

## 3. Почему так хорошо для хакатона

- можно показать полный пользовательский поток
- можно показать админский контур и ingestion
- можно руками провоцировать изменения availability в демо
- можно честно объяснить путь к production

## 4. Что реализовано сейчас

- test-mode ingestion
- поиск по адресу и ссылкам из карт
- агрегированный parking search в радиусе до 1 км
- распределение по классам машин
- admin auth и сессии
- forgot/reset password
- trip monitoring
- встроенный scheduler
- pull notifications
- FCM fallback architecture
- rate limit и базовые security headers

## 5. Что станет следующим этапом

### Pilot Production

- реальные потоки камер
- более точный CV/ML pipeline
- ETA от картографического API
- production push stack

### Scale

- вынесенный worker для scheduler
- очередь задач
- Postgres и аналитические витрины
- наблюдаемость, SLA/SLO и on-call
