"""HTML pages. German UI text. Every dynamic value is escaped."""

from __future__ import annotations

from html import escape

_STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:32rem;margin:1rem auto;padding:0 1rem}"
    "label,select,input,button{display:block;margin:.6rem 0;font-size:1rem}"
    "button{padding:.6rem 1rem}.err{color:#b00020}"
    ".wide{max-width:64rem}.review{display:flex;gap:1rem;flex-wrap:wrap;align-items:flex-start}"
    ".review>*{flex:1 1 20rem;min-width:0}.review img{max-width:100%;height:auto}"
)


def page(title: str, body: str, wide: str = "") -> bytes:
    # No inline style or script attributes: CSP is default-src 'self'. The style tag is a file.
    cls = f' class="{wide}"' if wide else ""
    return (
        '<!doctype html><html lang="de"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(title)}</title><link rel="stylesheet" href="/style.css"></head>'
        f"<body{cls}><h1>{escape(title)}</h1>{body}</body></html>"
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
        '<p><a href="/review">Entwürfe prüfen</a></p>'
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
    if not duplicate and not quarantined:
        link += f'<p><a href="/review/{escape(slug)}">Prüfen und bestätigen</a></p>'
    return page("Fertig", f'<p>{text}</p>{link}<p><a href="/">Noch eins hochladen</a></p>')


def error_page(message: str) -> bytes:
    return page("Fehler", f'<p class="err">{escape(message)}</p><p><a href="/">Zurück</a></p>')


_TYPE_LABELS = {
    "steuerbescheid": "Steuerbescheid",
    "rechnung": "Rechnung",
    "mahnung": "Mahnung",
    "kuendigung_vertrag": "Kündigung / Vertrag",
    "versicherung": "Versicherung",
    "sonstiges": "Sonstiges",
}


def review_list_page(slugs: list[str]) -> bytes:
    items = "".join(f'<li><a href="/review/{escape(s)}">{escape(s)}</a></li>' for s in slugs)
    body = f"<ul>{items}</ul>" if items else "<p>Keine Entwürfe offen.</p>"
    return page("Entwürfe", body + '<p><a href="/">Zurück</a></p>')


def _val(meta: dict[str, object], key: str) -> str:
    value = meta.get(key)
    return "" if value is None else escape(str(value), quote=True)


def review_page(csrf: str, slug: str, meta: dict[str, object], file: str, error: str = "") -> bytes:
    msg = f'<p class="err">{escape(error)}</p>' if error else ""
    url = f"/{escape(file)}"
    if file.endswith(".pdf"):
        shown = f'<p><a href="{url}">PDF öffnen</a></p>'
    else:
        shown = f'<img src="{url}" alt="Dokumentseite">'
    options = "".join(
        f'<option value="{k}"{" selected" if k == meta.get("type") else ""}>{v}</option>'
        for k, v in _TYPE_LABELS.items()
    )
    form = (
        f'{msg}<form method="post" action="/review/{escape(slug)}/confirm">'
        f'<input type="hidden" name="csrf" value="{escape(csrf)}">'
        f'<label>Art<select name="doc_type">{options}</select></label>'
        f'<label>Absender<input name="sender" value="{_val(meta, "from")}" required></label>'
        f'<label>Datum des Schreibens<input type="date" name="doc_date" '
        f'value="{_val(meta, "date")}" required></label>'
        f'<label>Betrag<input name="amount" value="{_val(meta, "amount")}"></label>'
        f'<label>Frist (leer = keine)<input type="date" name="deadline" '
        f'value="{_val(meta, "deadline")}"></label>'
        "<button>Bestätigen</button></form>"
        '<p><a href="/review">Zurück</a></p>'
    )
    return page("Prüfen", f'<div class="review"><div>{shown}</div><div>{form}</div></div>', "wide")


def confirmed_page(reminders: bool) -> bytes:
    note = " Erinnerungen sind eingeplant." if reminders else " Ohne Frist keine Erinnerung."
    return page(
        "Bestätigt",
        f'<p>Gespeichert.{note}</p><p><a href="/review">Weitere Entwürfe</a></p>'
        '<p><a href="/">Neues Dokument</a></p>',
    )
