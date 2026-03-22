# TODO — Code Review Findings

> Wygenerowane na podstawie przeglądu projektu. Zadania pogrupowane wg priorytetu.

---

## 🔴 Security

- [ ] **CORS** — zmienić `["*"]` na whitelist z domeną frontendu (`app/core/config.py`)
- [ ] **Rate limiting** — dodać na `POST /api/v1/auth/google` (np. `slowapi`)
- [ ] **Daily.co webhook** — `verify_webhook_signature()` istnieje w `app/services/daily.py` ale nie jest wywoływana w handlerze (`app/api/v1/video.py`)

---

## 🟡 Jakość kodu

- [ ] **Paginacja** — dodać parametry `skip`/`limit` na `GET /workshops/`
- [ ] **Transakcje DB** — join warsztatu wykonuje wiele operacji bez `async with session.begin()` (`app/api/v1/video.py`)
- [x] **Walidacja dat** — `WorkshopCreate.start_time` powinno odrzucać daty z przeszłości

---

## 🔵 Architektura

- [x] **TrainerProfile.specialties** — zamienić comma-separated string na JSON array lub osobną tabelę
- [x] **Soft delete** — usunięty warsztat traci historię uczestników; dodać `deleted_at` zamiast hard delete
- [x] **Refresh token** — JWT wygasa po 7 dniach, brak mechanizmu odświeżania; użytkownik musi logować się od nowa

---

## ✅ Zrobione

- ~~**Google Client IDs**~~ — przeniesione do zmiennych środowiskowych (`app/core/config.py`)
- ~~**Testy**~~ — dodano pytest (unit + integracyjne) w `tests/`
- ~~**Timezone**~~ — ujednolicona obsługa UTC w całym projekcie
