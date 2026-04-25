# TODO — Code Review Findings

> Wygenerowane na podstawie przeglądu projektu. Zadania pogrupowane wg priorytetu.

---

## 🔴 Security

- [x] **CORS** — zmienić `["*"]` na whitelist z domeną frontendu (`app/core/config.py`)
- [x] **Rate limiting** — dodać na `POST /api/v1/auth/google` (np. `slowapi`)
- [x] **Daily.co webhook** — `verify_webhook_signature()` istnieje w `app/services/daily.py` ale nie jest wywoływana w handlerze (`app/api/v1/video.py`)

---

## 🟡 Jakość kodu

- [x] **Paginacja** — dodać parametry `skip`/`limit` na `GET /workshops/`
- [x] **Transakcje DB** — join warsztatu wykonuje wiele operacji bez `async with session.begin()` (`app/api/v1/video.py`)
- [x] **Walidacja dat** — `WorkshopCreate.start_time` powinno odrzucać daty z przeszłości

---

## 🔵 Architektura

- [x] **TrainerProfile.specialties** — zamienić comma-separated string na JSON array lub osobną tabelę
- [x] **Soft delete** — usunięty warsztat traci historię uczestników; dodać `deleted_at` zamiast hard delete
- [x] **Refresh token** — JWT wygasa po 7 dniach, brak mechanizmu odświeżania; użytkownik musi logować się od nowa

---

## 🟢 Nowe funkcjonalności

### Push notifications (iOS + Android)

Powiadamianie trenera X minut przed rozpoczęciem stworzonych przez niego zajęć (oraz fundament pod inne powiadomienia: przypomnienia dla uczestników, zmiany w warsztacie, itp.).

**Stack:** `expo-notifications` (frontend) + Expo Push API (backend → APNs/FCM)

**Backend:**
- [x] Dodać tabelę `push_tokens` (multi-device) + migracja Alembic
- [x] Endpoint `PUT /api/v1/users/me/push-tokens` do rejestracji/aktualizacji tokenu
- [x] Serwis `app/services/notifications.py` — klient Expo Push API (`https://exp.host/--/api/v2/push/send`), obsługa błędów i `DeviceNotRegistered`
- [x] Scheduler — pętla pollingowa w FastAPI lifespan (`app/services/scheduler.py`) z idempotentnym markerem `reminder_sent_at`
- [x] Hook w `app/api/v1/workshops.py` — przy zmianie `start_time` / `reminder_minutes_before` resetuje `reminder_sent_at` (re-arm)
- [x] Konfiguracja: `notification_lead_minutes_default`, `notification_poll_seconds`, `notifications_enabled` w `app/core/config.py`
- [x] Testy: unit dla serwisu (mock Expo), integracyjne dla schedulera

**Frontend (Expo):**
- [x] Instalacja `expo-notifications`
- [x] Flow pobrania permissions + `ExponentPushToken` przy logowaniu
- [x] Wysłanie tokenu na backend (`PUT /users/me/push-tokens`) + unregister na logout (`POST /users/me/push-tokens/unregister`)
- [x] Handler przychodzącego powiadomienia (deep link do ekranu warsztatu po tapnięciu)
- [x] Development build (Expo Go nie obsługuje push — wymagany `expo-dev-client`, już jest w zależnościach)

**Ograniczenia / uwagi:**
- iOS wymaga fizycznego urządzenia + Apple Developer Account (provisioning profile z push entitlements)
- Android działa w emulatorze z Google Play Services
- Rozważyć przy skali: migracja z `APScheduler` → Celery + Redis (persystencja jobów między restartami)

---

## ✅ Zrobione

- **2026-03-21** — wszystkie otwarte punkty powyżej zostały zaimplementowane w kodzie i migracjach.
- **Weryfikacja** — pełen backend test suite przeszedł lokalnie na Docker/PostgreSQL: `32 passed`.

- ~~**Google Client IDs**~~ — przeniesione do zmiennych środowiskowych (`app/core/config.py`)
- ~~**Testy**~~ — dodano pytest (unit + integracyjne) w `tests/`
- ~~**Timezone**~~ — ujednolicona obsługa UTC w całym projekcie
