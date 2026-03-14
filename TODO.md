# TODO — Code Review Findings

> Wygenerowane na podstawie przeglądu projektu. Zadania pogrupowane wg priorytetu.

---

## 🔴 Security

- [ ] **CORS** — zmienić `["*"]` na whitelist z domeną frontendu (`app/core/config.py`)
- [ ] **Rate limiting** — dodać na `POST /api/v1/auth/google` (np. `slowapi`)
- [ ] **Daily.co webhook** — zaimplementować walidację podpisu (`X-Daily-Signature`) w `app/api/v1/video.py`
- [ ] **Google Client IDs** — przenieść z `app.config.js` do zmiennych środowiskowych (`.env`)

---

## 🟡 Jakość kodu

- [ ] **Testy** — dodać pytest (backend) i Jest/Vitest (frontend); aktualnie zero pokrycia
- [ ] **Paginacja** — dodać parametry `skip`/`limit` na `GET /workshops/`
- [ ] **Transakcje DB** — join warsztatu wykonuje 6-9 operacji bez `async with session.begin()` (`app/api/v1/video.py`)
- [ ] **Timezone** — ujednolicić obsługę naive vs aware datetimes w całym projekcie
- [ ] **Walidacja dat** — `WorkshopCreate.start_time` powinno odrzucać daty z przeszłości

---

## 🔵 Architektura

- [ ] **TrainerProfile.specialties** — zamienić comma-separated string na JSON array lub osobną tabelę
- [ ] **Soft delete** — usunięty warsztat traci historię uczestników; dodać `deleted_at` zamiast hard delete
- [ ] **Refresh token** — JWT wygasa po 7 dniach, brak mechanizmu odświeżania; użytkownik musi logować się od nowa
