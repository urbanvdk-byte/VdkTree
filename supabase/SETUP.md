# VdkTree v0.3.0 — общая база Supabase

## Подключение
1. Создайте проект в Supabase и выполните `supabase/schema.sql` в SQL Editor.
2. В Supabase Authentication → Providers включите Email (OTP / magic link), настройте Site URL на `https://urbanvdk-byte.github.io/VdkTree/` и Redirect URLs на этот же адрес.
3. В `supabase/config.js` замените URL и publishable/anon key на значения из Supabase → Project Settings → API. **Не добавляйте service_role / secret key в GitHub!**
4. После обновления GitHub Pages откройте сайт, войдите по email и добавьте дерево. Оно появится в общей карте только после одобрения администратором в Supabase Table Editor (поле status = approved).

## Безопасность
RLS включён: общедоступны только одобренные записи; авторизованные пользователи могут отправлять только pending-записи. Фотографии в общей базе пока отключены — требуется отдельная безопасная схема Storage, проверки файлов и модерация. До настройки Supabase сайт остаётся локальной демоверсией. Для публичного запуска нужны антиспам, ограничения частоты запросов, политика обработки данных и мониторинг.
