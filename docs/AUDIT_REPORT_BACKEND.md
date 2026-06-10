# Kalba Backend — Raport z audytu kodu

**Data:** 2026-06-10
**Zakres:** cały katalog `app/`, `migrations/`, `tests/`, Dockerfile, `fly.toml`, docker-compose, CI (`.github/workflows/`).
**Metoda:** dwa niezależne przeglądy (1: correctness / security / API design; 2: architektura / standardy / wydajność / testy / dokumentacja), wyniki scalone i zdeduplikowane.
**Rewizja audytowanego kodu:** `2da3640` (branch: `main`).

**Legenda ważności:** 🔴 Krytyczny · 🟠 Wysoki · 🟡 Średni · ⚪ Niski

---

## Podsumowanie

Kod jest powyżej średniej dla projektu na tym etapie: spójny async/await, czysta separacja DTO, batchowana serializacja unikająca N+1, przemyślana współbieżność w części ścieżek (`FOR UPDATE`, `ON CONFLICT`, atomowy claim w schedulerze), idempotentne migracje. Najpoważniejsze problemy koncentrują się w **podsystemie wideo** (race conditions w budżecie Daily.co i pojemności warsztatu, brak ochrony przed replay w webhooku, brak kontroli członkostwa w grupie przy joinie) oraz w **cyklu życia tokenów** (7-dniowy access token bez możliwości unieważnienia, nieegzekwowana flaga `is_active`). Dodatkowo: trzy endpointy grup są dostępne bez autoryzacji, a najbardziej złożony moduł (`video.py`) praktycznie nie ma testów HTTP.

---

## 1. Problemy z bezpieczeństwem

### 🔴 SEC-1. Webhook Daily.co bez ochrony przed replay; czas trwania sesji w pełni zaufany
**Pliki:** `app/api/v1/video.py:231-291`, `app/services/video_budget.py:185-218`
Podpis HMAC jest weryfikowany poprawnie (raw body + `hmac.compare_digest`), ale nagłówek `x-webhook-timestamp` **nigdy nie jest sprawdzany pod kątem świeżości** i nie ma deduplikacji zdarzeń. Przechwycony, poprawnie podpisany webhook `participant.left` można odtwarzać w nieskończoność. Ścieżka rozliczenia (`settle_session`) ufa `data.get("duration")` i `user_id` z payloadu wprost — sfałszowany/odtworzony webhook z małym `duration` zwalnia zarezerwowany budżet przedwcześnie, pozwalając wybić więcej tokenów niż zakłada limit (a limit jest jedyną barierą przed płatnym użyciem Daily.co).
**Poprawka:** odrzucać webhooki z timestampem poza oknem ±5 min; deduplikować po id zdarzenia; traktować minuty z webhooka jako informacyjne i nigdy nie pozwalać, by rozliczenie zwiększało dostępny budżet poniżej realnego czasu życia pokoju.

### 🔴 SEC-2. Race condition w rezerwacji budżetu wideo — limit można przebić równoległymi joinami
**Pliki:** `app/services/video_budget.py:96-168`, wywołanie z `app/api/v1/video.py:84`
`reserve_seat` wykonuje `SUM` (odczyt zużycia) i osobny `INSERT` bez żadnej blokady/serializacji. Przy równoczesnych joinach (typowy scenariusz: start warsztatu, wielu uczestników w tej samej sekundzie) N żądań czyta to samo `used`, każde widzi `projected <= cap` i każde insertuje — limit jest cicho przekraczany. Ścieżka zapisów (`workshops.py:487`) rozwiązała identyczny problem przez `with_for_update()`; budżet nie.
**Poprawka:** `pg_advisory_xact_lock(<stały klucz budżetu>)` wokół odczytu+insertu albo `SELECT ... FOR UPDATE` na wierszu-wartowniku budżetu.

### 🔴 SEC-3. Race condition w `join_workshop` — przepełnienie pokoju i duplikaty uczestników
**Plik:** `app/api/v1/video.py:99-130`, `app/models/video.py:52-59`
`COUNT` uczestników i `INSERT` biegną bez blokady na warsztacie, a `WorkshopParticipant` **nie ma unique constraint na `(workshop_id, user_id)`**. Równoległe joiny przechodzą obie przez kontrolę pojemności; ten sam użytkownik wyścigiem dwóch żądań tworzy zduplikowane wiersze.
**Poprawka:** dodać `UniqueConstraint("user_id", "workshop_id")` (+ migracja) i `with_for_update()` na wierszu warsztatu przed liczeniem — lustrzane odbicie `enroll_workshop`.

### 🟠 SEC-4. Flaga `is_active` nigdy nie jest egzekwowana — dezaktywowany użytkownik zachowuje pełny dostęp
**Pliki:** `app/core/security.py:148-153`, `app/models/user.py:20`
`get_current_user_id` dekoduje JWT i zwraca id bez ładowania użytkownika; żaden endpoint nie sprawdza `is_active`. Użytkownik oznaczony jako nieaktywny (np. nadużycia, usuwanie konta) zachowuje ważny 7-dniowy token i pełny dostęp do API.
**Poprawka:** dependency `get_current_active_user` ładujący użytkownika i zwracający 401 przy `is_active is False` — albo świadome usunięcie pola, by nie sugerowało nieistniejącej funkcji.

### 🟠 SEC-5. Access token żyje 7 dni i jest nieodwoływalny — reset hasła / usunięcie konta go nie unieważnia
**Pliki:** `app/core/config.py:31`, `app/api/v1/auth.py:241-255`, `app/api/v1/users.py:33-50`
Reset hasła i usunięcie konta unieważniają refresh tokeny, ale bezstanowy access JWT pozostaje ważny do końca 7-dniowego okresu. Po resecie hasła wymuszonym kompromitacją skradziony access token atakującego nadal działa nawet tydzień.
**Poprawka:** skrócić TTL access tokena do 15–60 min (refresh flow już istnieje) i/lub dodać sprawdzanie wersji tokena / `is_active` w dependency auth (łączy się z SEC-4).

### 🟠 SEC-6. Łączenie kont Google po e-mailu bez weryfikacji `email_verified` — możliwość przejęcia konta
**Pliki:** `app/api/v1/auth.py:280-318`, `app/core/security.py:107-145`
Gdy brak dopasowania po `google_id`, użytkownik jest wyszukiwany **po e-mailu** i jeśli ma `google_id is None`, tożsamość Google jest automatycznie dowiązywana do istniejącego konta hasłowego. `verify_google_id_token` nigdy nie sprawdza `email_verified`. Atakujący z kontem Google o niezweryfikowanym e-mailu ofiary mógłby się wpiąć w jej natywne konto. Rejestracja natywna również nie wymaga weryfikacji e-maila.
**Poprawka:** wymagać `payload.get("email_verified") in (True, "true")` przed jakimkolwiek lookupem/linkowaniem po e-mailu; bez weryfikacji — osobne konto lub jawny flow łączenia.

### 🟠 SEC-7. CORS: `localhost` w domyślnej liście originów na produkcji + `allow_credentials=True` + wildcard metod/nagłówków
**Pliki:** `app/main.py:50-56`, `app/core/config.py:77-81`
Domyślne `cors_origins` zawiera `http://localhost:3000` i `http://localhost:8081` i jest używane bezwarunkowo z `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`. Jeśli sekret `CORS_ORIGINS` nie nadpisuje tego na prodzie, originy localhost są zaufane z poświadczeniami. Dodatkowo `backend-kalba.fly.dev` (gdzie serwowane są strony resetu hasła) nie jest na liście.
**Poprawka:** lista originów wyłącznie z env per środowisko; nigdy localhost w domyślnej konfiguracji prod; zawęzić metody/nagłówki.

### 🟠 SEC-8. `/auth/login` bez rate limitu; limiter in-memory nieskuteczny na Fly z autoskalowaniem
**Pliki:** `app/core/rate_limit.py:11-43`, `fly.toml:17-19`
Limiter jest per-proces; z `min_machines_running = 0` i autoskalowaniem limity mnożą się przez liczbę maszyn i zerują przy każdym cold starcie. Logowanie hasłem **w ogóle nie ma limitu** — brute-force jest nieskrępowany (limity mają tylko google/reset/push).
**Poprawka:** dodać limiter na `/auth/login`; przenieść liczniki do współdzielonego magazynu (Postgres/Redis).

### 🟡 SEC-9. `GET /groups/{id}/members` w ogóle bez uwierzytelnienia — wyciek PII
**Plik:** `app/api/v1/groups.py:269-288`
Sygnatura trasy nie ma `Depends(get_current_user_id)` — **ktokolwiek** może wylistować członków dowolnej grupy (`full_name`, `role`, `user_id`).
**Poprawka:** wymagać auth + członkostwa/własności grupy.

### 🟡 SEC-10. Endpointy wideo nie sprawdzają członkostwa w grupie — obejście modelu widoczności
**Plik:** `app/api/v1/video.py:49-204, 304-334`
`get_workshop` egzekwuje członkostwo w grupie (404 dla obcych), ale `join_workshop` i `get_workshop_rules` — nie. Dowolny uwierzytelniony użytkownik znający UUID warsztatu może pobrać token dołączenia (ogranicza go tylko okno czasowe + pojemność + budżet) oraz czytać reguły.
**Poprawka:** zastosować tę samą bramkę `_caller_group_ids` / członkostwa co w endpointach odczytu warsztatów.

### 🟡 SEC-11. `GET /groups/` i `GET /groups/{id}` widoczne anonimowo
**Plik:** `app/api/v1/groups.py:78-94, 122`
Pełen katalog grup (tytuły, opisy, liczby członków) dostępny bez logowania — niespójne z modelem widoczności „tylko członkowie" obowiązującym dla warsztatów. Jeśli to celowe (discovery), udokumentować w DESIGN.md; jeśli nie — zabramkować.

### 🟡 SEC-12. PII w logach + ryzyko logowania SQL z parametrami
**Pliki:** `app/main.py:14`, `app/db.py:38-42`, m.in. `app/api/v1/auth.py:191`
Root logger na INFO, liczne logi z e-mailami i id użytkowników; `echo=bool(debug)` — ustawienie `DEBUG=true` w jakimkolwiek środowisku loguje cały SQL z parametrami.
**Poprawka:** wymusić `debug=False` na prodzie walidatorem konfiguracji; usunąć surowe e-maile z logów (hash lub pominięcie).

### 🟡 SEC-13. `forgot_password` rozróżnialny czasowo (timing side-channel)
**Plik:** `app/api/v1/auth.py:140-198`
Endpoint zawsze zwraca 202 (dobrze), ale gałąź „konto istnieje" wykonuje synchroniczny `await EmailService(...).send_password_reset(...)` (sieciowe wywołanie Brevo) **przed** odpowiedzią — istnienie konta da się odróżnić po latencji.
**Poprawka:** wysyłka e-maila w background tasku (`BackgroundTasks`), obie gałęzie odpowiadają w stałym czasie.

### ⚪ SEC-14. Brak asercji startowej na domyślny `jwt_secret_key` w prod
**Plik:** `app/core/config.py:29`
Domyślny sekret `"change-me-in-production-min-32-bytes"` może trafić na produkcję bez ostrzeżenia. **Poprawka:** `model_validator` odrzucający placeholder przy `app_env == PROD` (analogicznie dla `database_url`).

### ⚪ SEC-15. `/docs`, `/redoc`, OpenAPI publiczne na produkcji
**Plik:** `app/main.py:42-63`
**Poprawka:** `docs_url=None, redoc_url=None, openapi_url=None` gdy `app_env == prod`.

### ⚪ SEC-16. E-mail jako nazwa wyświetlana w pokoju wideo
**Plik:** `app/api/v1/video.py:164-176`
Przy braku `full_name` nazwą uczestnika widoczną dla wszystkich staje się jego e-mail. **Poprawka:** fallback na neutralną etykietę („Participant").

---

## 2. Błędy w implementacji (correctness)

### 🟠 IMP-1. `host_action` zapisuje stan `all_muted`/`all_cameras_off` nawet bez aktywnego pokoju — „duch" stanu dziedziczony przez następną sesję
**Plik:** `app/api/v1/video.py:341-415`
Trener może przełączyć reguły w dowolnym momencie (także po `latest_join`); gdy `video_room_id is None`, broadcast jest cicho pomijany, ale stan w `WorkshopRules` zostaje — następna sesja startuje z „wszyscy wyciszeni" przez `join_workshop:160-161`.
**Poprawka:** bramkować host-action na istniejącej/aktywnej sesji albo resetować stan live przy (re)tworzeniu pokoju.

### 🟡 IMP-2. Pokój Daily „already exists" → twardy 502 przy joinie
**Pliki:** `app/api/v1/video.py:133-151`, `app/services/daily.py:77-86`, `app/api/v1/workshops.py:444-462`
Nazwa pokoju jest deterministyczna (`kalba-{id}`), soft-delete kasuje pokój w Daily, ale zostawia `video_room_id`; każdy `DailyServiceError` przy create jest mapowany na 502, więc zastany/duplikowany pokój blokuje joiny.
**Poprawka:** traktować „already exists" jako sukces (pokój jest używalny) albo czyścić `video_room_id` przy delete.

### 🟡 IMP-3. Usuwanie konta nieatomowe; ręczna kaskada krucha na nowe FK
**Pliki:** `app/services/account.py:29-113`, `app/api/v1/users.py:33-50`
Serwis commituje w środku (`account.py:112`) — awaria w trakcie kaskady zostawia częściowo usuniętego użytkownika. Każda przyszła tabela z FK do `user.id` nieuwzględniona w kaskadzie wywali `DELETE FROM user`.
**Poprawka:** jedna jawna transakcja (`async with session.begin()`), bez commitu w połowie; test regresyjny wykrywający nowe nieobsłużone FK.

### 🟡 IMP-4. Webhook: `request.json()` parsuje body drugi raz i może rzucić nieobsłużony 500
**Plik:** `app/api/v1/video.py:219-220`
Body nie-JSON / puste → nieobsłużony `JSONDecodeError` przed weryfikacją podpisu na publicznym endpoincie.
**Poprawka:** `json.loads(payload_body)` w try/except → 400.

### ⚪ IMP-5. `WorkshopUpdate` bez walidatorów `ge=1`; pojemność można obniżyć poniżej liczby zapisanych
**Pliki:** `app/api/v1/workshops.py:333-421`, `app/models/workshop.py:79-94`
PATCH może ustawić `duration_minutes=0`/ujemne (psuje matematykę wygaśnięcia pokoju w `daily.py:49` i estymaty budżetu) oraz `max_participants` poniżej obecnych zapisów. **Poprawka:** `ge=1` na DTO update; odrzucać obniżenie pojemności poniżej bieżącej liczby zapisanych. Dodatkowo `price` bez `ge=0` (`workshop.py:24,57`).

### ⚪ IMP-6. Walidator `start_time` w update blokuje edycję warsztatów już rozpoczętych
**Plik:** `app/models/workshop.py:96-105`
PATCH innych pól z przeszłym (oryginalnym) `start_time` jest odrzucany. **Poprawka:** walidować tylko gdy `start_time` faktycznie się zmienia.

### ⚪ IMP-7. Scheduler przypomnień nie zadziała, gdy wszystkie maszyny śpią
**Pliki:** `app/services/scheduler.py:96-184`, `fly.toml`
Atomowy claim jest poprawny (multi-instance safe), ale z `min_machines_running=0` przypomnienia nie wyjdą, jeśli żadne żądanie nie obudzi maszyny w oknie. **Poprawka:** min. jedna maszyna stale działająca lub dedykowany proces dla zadań czasowych.

### ⚪ IMP-8. Migracja `e1a2b3c4d5f6` destrukcyjna i nieodwracalna
**Plik:** `migrations/versions/e1a2b3c4d5f6_require_group_on_workshop.py:25-40`
Upgrade twardo usuwa osierocone warsztaty; downgrade nie przywraca danych. Udokumentować jako one-way (świadoma decyzja).

---

## 3. Błędy architektoniczne

### 🟡 ARCH-1. Logika biznesowa skoncentrowana w handlerach API wbrew własnej regule projektu
**Pliki:** `app/api/v1/workshops.py`, `groups.py`, `my_kalba.py`
CLAUDE.md: „business logic w `services/`". W praktyce: pojemność/blokady zapisów (`workshops.py:469-559`), tworzenie warsztatu z regułami/tagami/przypomnieniami (257-330), logika reschedule (333-421), SQL statystyk dashboardu (`my_kalba.py:95-141`) — wszystko w handlerach. `video.py` i `auth.py` poprawnie delegują.
**Poprawka:** wyodrębnić co najmniej `workshop_service` (enroll/capacity — kod wrażliwy na współbieżność) i serializatory.

### 🟡 ARCH-2. Router importuje prywatny helper z innego routera + duplikacja serializacji
**Pliki:** `app/api/v1/groups.py:11` (`from app.api.v1.workshops import _serialize_workshops`), `app/api/v1/my_kalba.py:77-92`
`groups` importuje `_serialize_workshops` (prefiks `_`!) z `workshops`, a `my_kalba` reimplementuje tę samą logikę inline. **Poprawka:** przenieść do `app/services/workshops.py`, importować z serwisu we wszystkich trzech miejscach.

### 🟡 ARCH-3. Engine budowany w czasie importu; `get_settings()` z `lru_cache` zamraża konfigurację
**Pliki:** `app/db.py:34-44`, `app/core/config.py:101-116`, `tests/conftest.py:45-66`
`dependency_overrides[get_settings]` nie wpływa na nic czytanego przy imporcie — testy obchodzą to monkeypatchem `app.db.async_session` (smell). **Poprawka:** leniwa fabryka `get_engine()` zamiast modułowego globala.

### 🟡 ARCH-4. `create_workshop` woła `get_settings()` wprost zamiast przez DI
**Plik:** `app/api/v1/workshops.py:281`
Niespójne z resztą (auth.py, video.py wstrzykują przez `Depends`). **Poprawka:** `settings: Settings = Depends(get_settings)` w sygnaturze.

### ⚪ ARCH-5. `_utc_now_naive()` zdefiniowane w ~7 miejscach, `_minutes_until_start` w 2
**Pliki:** `scheduler.py`, `my_kalba.py:28`, `video_budget.py:30`, `notifications.py:33`, `my_kalba_notifications.py:11-14` i in.
To konwencja przechowywania czasu (UTC-naive) — powinna mieć jedno źródło. **Poprawka:** `app/core/time.py` z `utc_now_naive()` i `minutes_until(dt)`.

### ⚪ ARCH-6. Nowy `httpx.AsyncClient` na każde wywołanie zewnętrzne
**Pliki:** `security.py:115`, `daily.py:65,98,115,149`, `email.py:52`
Brak reużycia połączeń/TLS; ścieżka joinu robi 2–3 sekwencyjne wywołania Daily. **Poprawka:** współdzielony klient o cyklu życia aplikacji (lifespan) wstrzykiwany przez DI. Niski priorytet przy obecnej skali.

### ⚪ ARCH-7. `logging.basicConfig` jako efekt uboczny importu
**Plik:** `app/main.py:14`
Konflikt z konfiguracją logowania uvicorna i pytest. **Poprawka:** konfiguracja w `create_app()` lub przez `--log-config`.

---

## 4. Jakość kodu / standardy

- 🟡 **STD-1.** Mieszane style statusów HTTP — `status.HTTP_403_FORBIDDEN` obok gołych `404`, `502` w tych samych plikach (`workshops.py:109,111`, cały `video.py`). Ujednolicić na stałe `status.*`.
- ⚪ **STD-2.** Niespójna polityka `extra` na DTO wejściowych — tylko część ma `extra="forbid"` (`my_kalba.py:60-87`); `WorkshopCreate/Update`, `GroupCreate/Update`, DTO auth cicho ignorują nieznane pola. Ustandaryzować `extra="forbid"` wszędzie.
- ⚪ **STD-3.** Walidacja dwupoziomowa dla jednego konceptu — „nie w przeszłości" w DTO (`models/workshop.py:69-76`), zakres lat 2024–2100 w handlerze (`workshops.py:80-92`). Skonsolidować w walidatorze DTO.
- ⚪ **STD-4.** Pola `WorkshopRules` bez ścieżki egzekwowania (`allow_unmute_after`, `allow_camera_toggle`, `late_join_behavior` — `models/video.py:43-45`); `late_join_behavior` nie jest nawet w `RulesRead`. Udokumentować w docstringu jako not-yet-enforced.
- ⚪ **STD-5.** `_build_settings` tworzy `Settings()` dwa razy + `# type: ignore` (`config.py:101-116`). Użyć mechanizmu źródeł pydantic-settings.

---

## 5. Testy i CI

### 🟠 TEST-1. Podsystem wideo — najbardziej złożony i „przychodowy" kod — bez testów HTTP
**Pliki:** `app/api/v1/video.py`, `tests/integration/`
`join_workshop` testowany tylko pośrednio przez `test_video_budget.py` (asercje na wierszach budżetu). **Zero** testów dla: okna czasowego (403 przed/po), kontroli pojemności, rollbacku rezerwacji przy `DailyServiceError`, `host_action` (autoryzacja 403, każdy `HostActionType`, `broadcast_sent=False`), `get_workshop_rules` (domyślne wartości).
**Minimalny zestaw do dodania:**
1. join przed `start_time - 5min` → 403; po end+10min → 403; host w dowolnym momencie → 200,
2. N-ty uczestnik → 403 „Workshop is full",
3. `create_room`/`create_meeting_token` rzuca `DailyServiceError` → 502 **i** liczba `VideoUsageSession` wraca do stanu sprzed,
4. host-action przez nie-trenera → 403,
5. rules bez wiersza w DB → wartości domyślne.

### 🟡 TEST-2. Pozostałe luki pokrycia
- `GET /users/me` (w tym 404) — brak testu HTTP.
- Kaskada usuwania konta: brak asercji, że trener z grupami/warsztatami traci `VideoUsageSession`, `WorkshopRules`, `WorkshopTag`, `WorkshopParticipant`.
- `app/api/web.py` (`/reset-password`, `/privacy`) — choćby smoke 200 + content-type.
- `my_kalba.py`: 3 testy na 8 endpointów; matematyka granic tygodnia/miesiąca w `_load_stats` (`my_kalba.py:102-130`) nietestowana.
- Brak testów współbieżności dla SEC-2/SEC-3 (równoległe joiny).

---

## 6. Dokumentacja

### 🟠 DOC-1. CLAUDE.md nieaktualny — aktywnie wprowadza w błąd
**Plik:** `CLAUDE.md`
- Drzewo architektury pomija istniejące moduły: `groups`, `my_kalba`, `notifications`, `tags`, `app/api/web.py` oraz serwisy `account`, `email`, `hashtags`, `notifications`, `my_kalba_notifications`, `scheduler`, `video_budget` (~5 z ~13 opisanych).
- Sekcja „Roles" jest błędna: widoczność/zapisy bramkuje **członkostwo w grupie** (`workshops.py:117-135`), nie rola.
- „Auth Flow" opisuje tylko `/auth/google`; w kodzie jest 7 endpointów (rejestracja, login hasłem, refresh, reset hasła).
- Migracje: doc `uv run alembic` vs Dockerfile `python -m alembic` (`Dockerfile:22`).
**Poprawka:** zregenerować drzewo z faktycznej listy plików; przepisać Roles/Auth Flow.

---

## 7. Sugestie poprawek — plan zadań dla modelu wykonawczego (np. Sonnet)

Zadania są niezależne, uporządkowane wg priorytetu. Każde = osobny branch + PR (konwencja: `<dev>/nazwa`). Po każdym: `uv run pytest -q --tb=short` (wymaga Postgresa z docker-compose).

| # | Zadanie | Pliki | Kryteria akceptacji |
|---|---------|-------|---------------------|
| 1 | Replay-protection webhooka: okno ±5 min na `x-webhook-timestamp` + dedup po event id; parsowanie body raz, w try/except → 400 | `app/api/v1/video.py` | Test: stary timestamp → 401/400; powtórzone zdarzenie → ignorowane; body nie-JSON → 400 |
| 2 | Advisory lock w `reserve_seat` (`pg_advisory_xact_lock`) wokół SUM+INSERT | `app/services/video_budget.py` | Test współbieżny: N równoległych rezerwacji nie przekracza capa |
| 3 | `UniqueConstraint("user_id","workshop_id")` na `WorkshopParticipant` + migracja + `with_for_update()` na warsztacie w `join_workshop` (wzorzec z `enroll_workshop`) | `app/models/video.py`, `app/api/v1/video.py`, nowa migracja | Migracja czyści ewentualne duplikaty przed nałożeniem constraintu; test podwójnego joinu |
| 4 | Dependency `get_current_active_user` (ładuje usera, 401 gdy `not is_active` lub user nie istnieje); podpiąć we wszystkich endpointach wymagających auth | `app/core/security.py`, routery | Test: nieaktywny user → 401 na dowolnym endpoincie |
| 5 | Skrócić `jwt_expire_minutes` do 60; potwierdzić, że frontend ma refresh flow (ma — interceptor 401) | `app/core/config.py` | Testy auth przechodzą; refresh flow działa |
| 6 | Wymagać `email_verified` przed lookupem/linkowaniem po e-mailu w `google_auth` | `app/api/v1/auth.py`, `app/core/security.py` | Test: token bez `email_verified` → brak auto-linkowania |
| 7 | Auth + członkostwo na `GET /groups/{id}/members`; decyzja + ew. bramka dla `GET /groups/` i `GET /groups/{id}` (udokumentować w DESIGN.md) | `app/api/v1/groups.py` | Anonimowy → 401; nie-członek → 403/404 |
| 8 | Bramka członkostwa w grupie dla `join_workshop` i `get_workshop_rules` (reużyć `_caller_group_ids`) | `app/api/v1/video.py` | Nie-członek → 404 (spójnie z `get_workshop`) |
| 9 | Rate limit na `/auth/login` (reużyć `InMemoryRateLimiter` jako minimum; docelowo magazyn współdzielony) | `app/api/v1/auth.py`, `app/core/rate_limit.py` | Test: 6. próba w minucie → 429 |
| 10 | Walidator prod-config: odrzuć placeholder `jwt_secret_key`, `debug=True` i localhost w `cors_origins` gdy `app_env == PROD`; wyłącz `/docs` na prodzie | `app/core/config.py`, `app/main.py` | Boot z placeholderem + `APP_ENV=prod` → błąd startu |
| 11 | `forgot_password`: wysyłka e-maila przez `BackgroundTasks`; usunąć surowe e-maile z logów INFO w całym repo | `app/api/v1/auth.py` i in. | Obie gałęzie zwracają 202 bez wywołania sieciowego na ścieżce odpowiedzi |
| 12 | Host-action: nie zapisywać stanu live bez aktywnego pokoju lub resetować `all_muted`/`all_cameras_off` przy tworzeniu pokoju; „room already exists" w Daily traktować jako sukces | `app/api/v1/video.py`, `app/services/daily.py` | Nowa sesja nie dziedziczy stanu; join nie pada na zastanym pokoju |
| 13 | Atomowe usuwanie konta: jedna transakcja, bez commitu w serwisie | `app/services/account.py` | Symulowana awaria w środku kaskady → pełny rollback |
| 14 | Testy HTTP podsystemu wideo (lista z TEST-1) | `tests/integration/test_video_endpoints.py` (nowy) | Min. 8 przypadków z TEST-1 zielonych |
| 15 | Refaktor: `_serialize_workshops` → `app/services/workshops.py`; enroll/capacity → serwis; `Depends(get_settings)` w `create_workshop`; `app/core/time.py` dla `utc_now_naive` | `workshops.py`, `groups.py`, `my_kalba.py` + nowe pliki | Zero zmian zachowania; wszystkie testy zielone |
| 16 | Walidatory DTO: `ge=1` na `WorkshopUpdate.duration_minutes/max_participants`, `ge=0` na `price`, `extra="forbid"` na wszystkich DTO wejściowych; walidacja `start_time` tylko przy zmianie | `app/models/workshop.py` i in. | Testy walidacji 422 |
| 17 | Aktualizacja CLAUDE.md (drzewo, Roles, Auth Flow) i wpis w `../frontend/docs/DESIGN.md` o decyzjach z zadań 5/7/8 | `CLAUDE.md`, `../frontend/docs/DESIGN.md` | Przegląd ręczny |

**Wskazówki dla modelu wykonawczego:**
- Wzorce do naśladowania istnieją w repo: blokada pojemności → `workshops.py:484-487` (`with_for_update`), atomowy claim → `scheduler.py:96-115`, idempotencja → `ON CONFLICT` w tagach/tokenach.
- Czas przechowywany jako **UTC-naive** — nie wprowadzać stref czasowych do kolumn.
- Testy wymagają działającego Postgresa (`docker compose -f docker-compose.local.yml up -d`).
- Przed commitem obowiązuje code review wg sekcji „Workflow Orchestration" w CLAUDE.md.

---

## Zweryfikowane jako OK (nie zgłaszać ponownie)

- SQL injection: wszystkie zapytania przez parameter binding; jedyny interpolowany SQL to stała w migracji (bez inputu użytkownika); `suggest_tags` poprawnie escapuje wildcardy LIKE (`hashtags.py:82-93`).
- HMAC webhooka: raw body + `hmac.compare_digest` — poprawny prymityw (luka to replay, nie kryptografia).
- Rotacja refresh tokenów przy `/auth/refresh`: poprawna.
- Mass assignment `role`: pole nigdy nie jest bindowane z żadnego DTO — brak eskalacji uprawnień przez body.
- Sekrety: `.env.dev`/`.env.local` git-ignorowane i nieśledzone; brak sekretów w repo.
- Listy warsztatów: serializacja O(1) (batchowane COUNT/enrollment) — brak N+1.
- Migracje idempotentne (inspector-guarded).
