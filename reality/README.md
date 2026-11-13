# Загадки Реальности. Биохакинг — Telegram autopublisher

Канал: https://t.me/priroda_realnosti
Бот: https://t.me/priroda_realnosti_bot

Не зависит от `news.yml`, `dino.yml` и других рабочих процессов.

## Публикации

- Каждые 20 минут GitHub Actions ищет научные истории в RSS ScienceDaily / Phys.org.
- До 7 постов за местные сутки, интервал не менее 120 минут.
- Время: 08:00–22:00, Europe/Belgrade, учитывается летнее/зимнее время.
- Приоритет: необычные открытия, природа, животные, космос, технологии, мозг, сон. Для медицинских тем действует осторожный фильтр без советов по лечению.
- Подтверждённый заголовок и короткий фрагмент RSS переводятся на русский; ссылка на издателя остаётся. Не придумывать материал, чтобы заполнить лимит.
- К научной истории прикрепляется тематическая иллюстрация из Wikimedia Commons только с проверенной лицензией CC0 / Public domain / CC BY и обязательной атрибуцией. Иллюстрация честно помечена как иллюстрация, а не фото конкретного открытия.
- До 1 видеопоста NASA в день: официальный видеоархив, короткий фрагмент до 25 секунд с сохранением пропорций, подпись на русском и ссылка на NASA.
- Сохраняется история за 90 дней. Неподходящие, повторные материалы и непроверенные источники пропускаются.
- Редакционный отбор автоматический: не заменяет проверку научной достоверности человеком.

## Безопасное подключение

Токен, отправленный в переписке, был раскрыт. В @BotFather нажмите Revoke и создайте новый. **Новый токен НЕ отправлять в чат и НЕ добавлять в файлы публичного репозитория**.

1. Добавьте @priroda_realnosti_bot администратором канала @priroda_realnosti с разрешением **Публикация сообщений**.
2. Откройте Settings → Secrets and variables → Actions в репозитории zamendirin-lgtm/serbia24-bot.
3. New repository secret: Name `REALITY_BOT_TOKEN`, Secret — новый токен BotFather.
4. Actions → Reality — science, mysteries and NASA media → Run workflow. `dry_run=true` — тест без публикации, `dry_run=false` — реальный запуск.
5. При ошибке сохранения истории: Settings → Actions → General → Workflow permissions → Read and write permissions.

GitHub scheduled jobs may run late or be skipped during service congestion. Only one successful message is sent per run.
