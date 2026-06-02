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
