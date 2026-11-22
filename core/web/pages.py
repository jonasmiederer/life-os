"""HTML pages. German UI text. Every dynamic value is escaped."""

from __future__ import annotations

from html import escape

_STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:32rem;margin:1rem auto;padding:0 1rem}"
    "label,select,input,button{display:block;margin:.6rem 0;font-size:1rem}"
    "button{padding:.6rem 1rem}.err{color:#b00020}"
)


def page(title: str, body: str) -> bytes:
    # No inline style or script attributes: CSP is default-src 'self'. The style tag is a file.
    return (
        '<!doctype html><html lang="de"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(title)}</title><link rel="stylesheet" href="/style.css"></head>'
        f"<body><h1>{escape(title)}</h1>{body}</body></html>"
    ).encode()


STYLE_CSS = _STYLE.encode()


def login_page(error: str = "") -> bytes:
    msg = f'<p class="err">{escape(error)}</p>' if error else ""
    return page(
        "Anmelden",
        f'{msg}<form method="post" action="/login">'
        '<label>Passwort<input type="password" name="password" autocomplete="current-password" '
        "required autofocus></label><button>Anmelden</button></form>",
    )


def upload_page(csrf: str, error: str = "") -> bytes:
    msg = f'<p class="err">{escape(error)}</p>' if error else ""
    return page(
        "Dokument hochladen",
        f'{msg}<form method="post" action="/upload" enctype="multipart/form-data">'
        f'<input type="hidden" name="csrf" value="{escape(csrf)}">'
        '<label>Foto oder PDF<input type="file" name="file" '
        'accept="image/*,application/pdf" capture required></label>'
        "<label>Datenklasse (bitte bei jedem Upload bestätigen)"
        '<select name="class" required><option value="">Bitte wählen</option>'
        '<option value="allow">Cloud erlaubt</option>'
        '<option value="block">Keine Cloud (gesperrt)</option>'
        '<option value="local">Nur auf diesem Rechner</option></select></label>'
        '<label><input type="checkbox" name="local_only" value="1"> nur lokal</label>'
        "<button>Hochladen</button></form>"
        '<form method="post" action="/logout">'
        f'<input type="hidden" name="csrf" value="{escape(csrf)}"><button>Abmelden</button></form>',
    )


def done_page(
    slug: str, sha: str, ext: str, duplicate: bool, quarantined: tuple[str, ...]
) -> bytes:
    if duplicate:
        text = "Dieses Dokument ist schon vorhanden. Nichts geändert."
    elif quarantined:
        text = "Gespeichert, aber die Notiz liegt zur Prüfung im Ordner review."
    else:
        text = f"Gespeichert als Entwurf: {escape(slug)}"
    link = "" if duplicate else f'<p><a href="/files/{sha}.{ext}">Bild ansehen</a></p>'
    return page("Fertig", f'<p>{text}</p>{link}<p><a href="/">Noch eins hochladen</a></p>')


def error_page(message: str) -> bytes:
    return page("Fehler", f'<p class="err">{escape(message)}</p><p><a href="/">Zurück</a></p>')
