"""Server-rendered web pages served directly by the backend.

These exist so password-reset links in email are clickable from any client
(including desktop browsers) without needing a separately hosted web app. The
page is self-contained (inline CSS/JS) and talks to the JSON API on the same
origin.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["web"])


_RESET_PASSWORD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Reset your Kalba password</title>
<style>
  :root {
    --canvas: #F5F1EB; --surface: #FAF8F4; --elevated: #FFFFFF;
    --primary: #566B52; --accent: #B8877A; --ink: #2B2A26;
    --ink-body: #57564F; --ink-muted: #8C8A82; --line: #E4DFD6;
    --danger: #C4836E; --ok: #566B52;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; display: flex; align-items: center;
    justify-content: center; padding: 24px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: linear-gradient(180deg, #F2E4DE 0%, var(--canvas) 34%, var(--canvas) 100%);
    color: var(--ink);
  }
  .card {
    width: 100%; max-width: 420px; background: var(--surface);
    border: 1px solid var(--line); border-radius: 24px; padding: 32px;
    box-shadow: 0 14px 40px rgba(0,0,0,0.08);
  }
  .brand { text-align: center; font-size: 30px; font-weight: 200; letter-spacing: 7px;
    margin: 0 0 8px; }
  h1 { font-size: 22px; font-weight: 600; text-align: center; margin: 8px 0 6px; }
  p.sub { color: var(--ink-body); font-size: 14px; text-align: center; margin: 0 0 22px;
    line-height: 1.5; }
  label { display: block; font-size: 14px; font-weight: 600; margin: 16px 0 8px; }
  input {
    width: 100%; min-height: 50px; padding: 0 14px; font-size: 16px;
    border: 1px solid var(--line); border-radius: 12px; background: var(--elevated);
    color: var(--ink);
  }
  input:focus { outline: none; border-color: var(--primary); }
  button {
    width: 100%; min-height: 52px; margin-top: 24px; border: none; cursor: pointer;
    background: var(--primary); color: #fff; font-size: 16px; font-weight: 700;
    letter-spacing: 0.3px; border-radius: 999px;
  }
  button:disabled { opacity: 0.6; cursor: default; }
  .msg { margin-top: 16px; font-size: 14px; text-align: center; line-height: 1.5; }
  .msg.error { color: var(--danger); font-weight: 600; }
  .msg.ok { color: var(--ok); font-weight: 600; }
  .hidden { display: none; }
</style>
</head>
<body>
  <div class="card">
    <p class="brand">KALBA</p>
    <h1>Choose a new password</h1>
    <p class="sub">Enter a new password for your Kalba account.</p>

    <form id="form">
      <label for="password">New password</label>
      <input id="password" type="password" autocomplete="new-password"
        placeholder="At least 8 characters, letters and numbers" required />

      <label for="confirm">Confirm password</label>
      <input id="confirm" type="password" autocomplete="new-password"
        placeholder="Re-enter your new password" required />

      <div id="msg" class="msg"></div>
      <button id="submit" type="submit">Reset password</button>
    </form>

    <div id="done" class="msg ok hidden">
      Your password has been reset. Open the Kalba app and log in with your new password.
    </div>
  </div>

<script>
  (function () {
    var token = new URLSearchParams(window.location.search).get("token");
    var form = document.getElementById("form");
    var msg = document.getElementById("msg");
    var submit = document.getElementById("submit");
    var done = document.getElementById("done");

    function showError(text) {
      msg.textContent = text;
      msg.className = "msg error";
    }

    if (!token) {
      form.classList.add("hidden");
      showError("This reset link is invalid or has expired.");
      msg.classList.remove("hidden");
      return;
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      msg.textContent = "";
      msg.className = "msg";

      var password = document.getElementById("password").value;
      var confirm = document.getElementById("confirm").value;

      if (password !== confirm) {
        showError("Passwords don't match.");
        return;
      }

      submit.disabled = true;
      submit.textContent = "Resetting...";

      fetch("/api/v1/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token, password: password }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (result.ok) {
            form.classList.add("hidden");
            done.classList.remove("hidden");
            return;
          }
          var detail = result.data && result.data.detail;
          if (Array.isArray(detail)) {
            detail = detail.map(function (d) { return d.msg; }).filter(Boolean).join(" ");
          }
          showError(detail || "This reset link is invalid or has expired.");
          submit.disabled = false;
          submit.textContent = "Reset password";
        })
        .catch(function () {
          showError("Something went wrong. Please try again.");
          submit.disabled = false;
          submit.textContent = "Reset password";
        });
    });
  })();
</script>
</body>
</html>
"""


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page() -> str:
    """Serve the password-reset web page. The token is read client-side from the
    query string and posted to ``/api/v1/auth/reset-password``."""
    return _RESET_PASSWORD_HTML


_PRIVACY_HTML = """<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Kalba — Polityka prywatności</title>
<style>
  :root {
    --canvas: #F5F1EB; --surface: #FAF8F4; --primary: #566B52;
    --ink: #2B2A26; --ink-body: #57564F; --ink-muted: #8C8A82; --line: #E4DFD6;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; padding: 32px 18px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--canvas); color: var(--ink-body); line-height: 1.6;
  }
  .card {
    max-width: 720px; margin: 0 auto; background: var(--surface);
    border: 1px solid var(--line); border-radius: 20px; padding: 32px;
  }
  h1 { color: var(--ink); font-size: 26px; margin: 0 0 4px; }
  h2 { color: var(--ink); font-size: 18px; margin: 28px 0 8px; }
  .updated { color: var(--ink-muted); font-size: 13px; margin: 0 0 8px; }
  ul { padding-left: 20px; }
  li { margin: 6px 0; }
  a { color: var(--primary); }
  .muted { color: var(--ink-muted); font-size: 13px; margin-top: 28px; }
</style>
</head>
<body>
  <div class="card">
    <h1>Polityka prywatności</h1>
    <p class="updated">Kalba · Ostatnia aktualizacja: czerwiec 2026</p>

    <p>Niniejsza polityka wyjaśnia, jakie dane zbiera aplikacja Kalba, w jakim celu
    oraz jakie masz możliwości wyboru. Ograniczamy zbieranie danych do niezbędnego
    minimum potrzebnego do działania usługi i <strong>nie sprzedajemy Twoich danych
    ani nie wykorzystujemy ich do reklam czy śledzenia.</strong></p>

    <h2>Jakie dane zbieramy</h2>
    <ul>
      <li><strong>Dane konta</strong> — adres e-mail i imię. Podajesz je podczas
      rejestracji e-mailem i hasłem lub pobieramy je z Twojego konta Google przy
      logowaniu przez Google.</li>
      <li><strong>Aktywność w aplikacji</strong> — warsztaty i grupy, które tworzysz,
      do których dołączasz lub na które się zapisujesz; służą do działania
      podstawowych funkcji aplikacji.</li>
      <li><strong>Token powiadomień push</strong> — token urządzenia, tylko jeśli
      wyrazisz zgodę na powiadomienia; służy do wysyłania przypomnień o warsztatach.</li>
    </ul>

    <h2>Jak wykorzystujemy dane</h2>
    <ul>
      <li>Do utworzenia i zabezpieczenia Twojego konta oraz logowania.</li>
      <li>Do obsługi warsztatów, grup, sesji wideo i przypomnień.</li>
      <li>Do wysyłania wiadomości e-mail z resetem hasła, gdy o to poprosisz.</li>
    </ul>
    <p>Nie korzystamy z żadnych zewnętrznych narzędzi reklamowych ani analitycznych
    służących do śledzenia.</p>

    <h2>Udostępnianie</h2>
    <p>Dane udostępniamy wyłącznie dostawcom usług niezbędnych do działania aplikacji
    (hosting, dostawca wideorozmów dla sesji na żywo, dostawca poczty do resetu hasła
    oraz dostarczanie powiadomień push), wyłącznie w celu świadczenia usługi. Nie
    sprzedajemy danych osobowych.</p>

    <h2>Usuwanie konta</h2>
    <p>W każdej chwili możesz trwale usunąć swoje konto i wszystkie powiązane dane
    bezpośrednio w aplikacji, w zakładce <strong>Profil → Delete account</strong>.
    Usuwa to Twój profil, sesje, zapisy i powiązane dane; tej operacji nie można
    cofnąć.</p>

    <h2>Przechowywanie danych</h2>
    <p>Przechowujemy Twoje dane, dopóki konto jest aktywne. Po usunięciu konta
    powiązane dane osobowe są usuwane.</p>

    <h2>Kontakt</h2>
    <p>Masz pytania dotyczące tej polityki lub swoich danych? Napisz na
    <a href="mailto:kalba.poland@gmail.com">kalba.poland@gmail.com</a>.</p>

    <p class="muted">Korzystając z aplikacji Kalba, akceptujesz niniejszą Politykę
    prywatności.</p>
  </div>
</body>
</html>
"""


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy_page() -> str:
    """Serve the privacy policy. Linked from the app and referenced in App Store
    Connect (we have no separate marketing site to host it on)."""
    return _PRIVACY_HTML
