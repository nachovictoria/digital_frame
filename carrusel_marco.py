#!/usr/bin/env python3
"""
Marco Digital — Raspberry Pi Digital Photo Frame
=================================================
Features:
  - Photo slideshow from 'fotos/' folder (tap to switch to calendar)
  - Shared calendar week view (iCal URL) with weather for 3 cities
  - Shopping list: email polling + manual input with Spanish keyboard
  - Event creation: sends .ics calendar invite to distribution list
  - Background email polling every 30s for "compra" and "foto" subjects
  - To do list

Dependencies:
  pip install Pillow icalendar recurring-ical-events requests
"""

import tkinter as tk
from tkinter import font as tkfont
import os
import sys
import json
import threading
import queue
import datetime
import time
import imaplib
import email as email_mod
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import smtplib
import uuid
import traceback
from urllib.request import urlopen, Request

try:
    from PIL import Image, ImageTk, ExifTags
except ImportError:
    sys.exit("ERROR: Pillow requerido → pip install Pillow")

try:
    from icalendar import Calendar as ICalCalendar, Event as ICalEvent
    from icalendar import vCalAddress, vText
    import recurring_ical_events
except ImportError:
    sys.exit("ERROR: icalendar requerido → pip install icalendar recurring-ical-events")

try:
    import requests
except ImportError:
    sys.exit("ERROR: requests requerido → pip install requests")


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FOTOS_DIR = os.path.join(SCRIPT_DIR, "fotos")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
SHOPPING_FILE = os.path.join(SCRIPT_DIR, "lista_compra.json")
TAREAS_FILE = os.path.join(SCRIPT_DIR, "tareas.json")

SCREEN_W, SCREEN_H = 1024, 600
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")

# Cities for weather are loaded from config.json ("cities" key)

# WMO Weather interpretation codes → (symbol, short description)
WMO_CODES = {
    0:  ("☀",  "Despejado"),
    1:  ("🌤", "Poco nub."),   2: ("⛅", "Parcial"),    3: ("☁", "Nublado"),
    45: ("🌫", "Niebla"),     48: ("🌫", "Niebla"),
    51: ("🌦", "Llovizna"),   53: ("🌦", "Llovizna"),  55: ("🌦", "Llovizna"),
    56: ("🌦", "Ll. helada"), 57: ("🌦", "Ll. helada"),
    61: ("🌧", "Lluvia"),     63: ("🌧", "Lluvia"),    65: ("🌧", "Lluvia +"),
    66: ("🌧", "Ll. helada"), 67: ("🌧", "Ll. helada"),
    71: ("❄",  "Nieve"),      73: ("❄",  "Nieve"),     75: ("❄",  "Nieve +"),
    77: ("❄",  "Granizo"),
    80: ("🌧", "Chubascos"),  81: ("🌧", "Chubascos"), 82: ("🌧", "Chubascos"),
    85: ("❄",  "Nieve"),      86: ("❄",  "Nieve +"),
    95: ("⛈",  "Tormenta"),   96: ("⛈",  "Tormenta"), 99: ("⛈",  "Tormenta"),
}

# Spanish day / month names
DIAS_CORTO  = ["LU", "MA", "MI", "JU", "VI", "SÁ", "DO"]
MESES_CORTO = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
               "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

# ── Colour palette (dark, modern, frame‑friendly) ─────────────────────
C = {
    "bg":          "#0f0f1a",
    "bg_card":     "#1a1a2e",
    "bg_header":   "#16213e",
    "accent":      "#e94560",
    "accent_hi":   "#ff6b81",
    "secondary":   "#0f3460",
    "text":        "#ffffff",
    "text_muted":  "#8888aa",
    "text_dim":    "#555577",
    "today_bg":    "#1a3a5c",
    "success":     "#4ecca3",
    "warning":     "#ffc857",
    "border":      "#2a2a4a",
    "key_bg":      "#2a2a4a",
    "key_sp":      "#3a3a5a",
    "checked_bg":  "#252540",
}

# ── Spanish on‑screen keyboard layouts ────────────────────────────────
KB_LOWER = [
    list("1234567890"),
    list("qwertyuiop"),
    list("asdfghjklñ"),
    ["⇧"] + list("zxcvbnm") + ["⌫"],
]
KB_UPPER = [
    list("!@#€%&/()="),
    list("QWERTYUIOP"),
    list("ASDFGHJKLÑ"),
    ["⇧"] + list("ZXCVBNM") + ["⌫"],
]
KB_ACCENT = [
    list("áéíóúü¿¡-_"),
    list("ÁÉÍÓÚÜ+*\"'"),
    list(".,;:@#€!?\\"),
    ["⇧"] + list("()[]{}<") + ["⌫"],
]


# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

def load_config():
    """Load config.json; create a template and exit if missing."""
    if not os.path.exists(CONFIG_FILE):
        default = {
            "ical_url": "",
            "gmail_user": "",
            "gmail_app_password": "",
            "smtp_server": "",
            "smtp_port": 465,
            "imap_server": "",
            "slideshow_interval_sec": 10,
            "email_poll_interval_sec": 30,
            "night_mode_start_h": 20,
            "night_mode_end_h": 8,
            "night_mode_timeout_sec": 60,
            "cities": [
                {"name": "", "code": "", "lat": 0, "lon": 0}
            ],
            "distribution_list": [
                {"name": "", "email": ""}
            ],
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2, ensure_ascii=False)
        print(f"[INFO] config.json creado en {CONFIG_FILE}")
        print("       Edítalo con tus credenciales antes de ejecutar de nuevo.")
        sys.exit(0)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════════════
# SHOPPING LIST PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════

class ShoppingListManager:
    """Thread‑safe JSON‑backed shopping list."""

    def __init__(self):
        self._lock = threading.Lock()
        self._load()

    # ── private ───────────────────────────────────────────────────────
    def _load(self):
        if os.path.exists(SHOPPING_FILE):
            try:
                with open(SHOPPING_FILE, "r", encoding="utf-8") as f:
                    self.items = json.load(f).get("items", [])
            except Exception:
                self.items = []
        else:
            self.items = []
            self._save()

    def _save(self):
        with open(SHOPPING_FILE, "w", encoding="utf-8") as f:
            json.dump({"items": self.items}, f, indent=2, ensure_ascii=False)

    # ── public ────────────────────────────────────────────────────────
    def add_item(self, text):
        with self._lock:
            text = text.strip()
            if text:
                self.items.append({"text": text, "checked": False,
                                   "added": datetime.datetime.now().isoformat()})
                self._save()

    def add_items(self, texts):
        with self._lock:
            for t in texts:
                t = t.strip()
                if t:
                    self.items.append({"text": t, "checked": False,
                                       "added": datetime.datetime.now().isoformat()})
            self._save()

    def toggle(self, idx):
        with self._lock:
            if 0 <= idx < len(self.items):
                self.items[idx]["checked"] = not self.items[idx]["checked"]
                self._save()

    def remove_checked(self):
        with self._lock:
            self.items = [i for i in self.items if not i["checked"]]
            self._save()

    def get_items(self):
        with self._lock:
            return list(self.items)

    def get_unchecked_texts(self):
        with self._lock:
            return [i["text"] for i in self.items if not i["checked"]]


# ═══════════════════════════════════════════════════════════════════════
# TAREAS PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════

class TareasManager:
    """Thread-safe JSON-backed tasks list, resets monthly."""
    def __init__(self):
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        now = datetime.datetime.now()
        current_month = f"{now.year}-{now.month:02d}"
        if os.path.exists(TAREAS_FILE):
            try:
                with open(TAREAS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.items = data.get("items", [])
                    self.last_reset = data.get("last_reset", current_month)
            except Exception:
                self.items = []
                self.last_reset = current_month
        else:
            self.items = []
            self.last_reset = current_month
            self._save()
            
        self._check_reset(current_month)

    def _check_reset(self, current_month):
        if self.last_reset != current_month:
            for item in self.items:
                item["checked"] = False
            self.last_reset = current_month
            self._save()

    def _save(self):
        with open(TAREAS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "items": self.items,
                "last_reset": self.last_reset
            }, f, indent=2, ensure_ascii=False)

    def toggle(self, idx):
        with self._lock:
            now = datetime.datetime.now()
            self._check_reset(f"{now.year}-{now.month:02d}")
            if 0 <= idx < len(self.items):
                self.items[idx]["checked"] = not self.items[idx]["checked"]
                self._save()

    def get_items(self):
        with self._lock:
            now = datetime.datetime.now()
            self._check_reset(f"{now.year}-{now.month:02d}")
            return list(self.items)

    def add_item(self, text):
        with self._lock:
            text = text.strip()
            if text:
                now = datetime.datetime.now()
                self._check_reset(f"{now.year}-{now.month:02d}")
                self.items.append({"text": text, "checked": False,
                                   "added": datetime.datetime.now().isoformat()})
                self._save()

    def remove_checked(self):
        with self._lock:
            self.items = [i for i in self.items if not i["checked"]]
            self._save()


# ═══════════════════════════════════════════════════════════════════════
# WEATHER CACHE (Open‑Meteo, no API key)
# ═══════════════════════════════════════════════════════════════════════

class WeatherCache:
    def __init__(self, cities=None):
        self.cities = cities or []
        self.data = {}          # city_code → {date_str → {...}}
        self.last_fetch = 0.0
        self.ttl = 3600         # refresh every hour

    def fetch_all(self):
        now = time.time()
        if self.data and (now - self.last_fetch) < self.ttl:
            return self.data

        new_data = {}
        for city in self.cities:
            try:
                url = (
                    f"https://api.open-meteo.com/v1/forecast?"
                    f"latitude={city['lat']}&longitude={city['lon']}"
                    f"&daily=temperature_2m_max,temperature_2m_min,weather_code"
                    f"&forecast_days=14&timezone=auto"
                )
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                daily = resp.json().get("daily", {})

                dates  = daily.get("time", [])
                t_max  = daily.get("temperature_2m_max", [])
                t_min  = daily.get("temperature_2m_min", [])
                codes  = daily.get("weather_code", [])

                city_dict = {}
                for i, ds in enumerate(dates):
                    wmo = codes[i] if i < len(codes) else 0
                    icon, desc = WMO_CODES.get(wmo, ("?", "?"))
                    city_dict[ds] = {
                        "max": round(t_max[i]) if i < len(t_max) else "?",
                        "min": round(t_min[i]) if i < len(t_min) else "?",
                        "icon": icon, "desc": desc,
                    }
                new_data[city["code"]] = city_dict
            except Exception as e:
                print(f"[WEATHER] Error {city['name']}: {e}")
                new_data[city["code"]] = {}

        self.data = new_data
        self.last_fetch = now
        return self.data

    def get(self, city_code, date_str):
        return self.data.get(city_code, {}).get(date_str)


# ═══════════════════════════════════════════════════════════════════════
# ICAL CALENDAR FETCHER
# ═══════════════════════════════════════════════════════════════════════

def fetch_ical_events(ical_url, start_date, end_date):
    """Return list of dicts {summary, start, end, all_day}."""
    if not ical_url:
        return []
    try:
        req = Request(ical_url, headers={"User-Agent": "MarcoDigital/1.0"})
        with urlopen(req, timeout=15) as resp:
            raw = resp.read()

        cal = ICalCalendar.from_ical(raw)
        events = recurring_ical_events.of(cal).between(start_date, end_date)

        out = []
        for ev in events:
            dt_start = ev.get("dtstart")
            dt_end   = ev.get("dtend")
            if dt_start:
                dt_start = dt_start.dt
            if dt_end:
                dt_end = dt_end.dt

            all_day = isinstance(dt_start, datetime.date) and \
                      not isinstance(dt_start, datetime.datetime)

            out.append({
                "summary": str(ev.get("summary", "Sin título")),
                "start":   dt_start,
                "end":     dt_end,
                "all_day": all_day,
            })
        return out
    except Exception as e:
        print(f"[ICAL] Error: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════
# EMAIL: SEND (SMTP)  &  CALENDAR INVITE (.ics)
# ═══════════════════════════════════════════════════════════════════════

def create_ics_invite(title, description, start_dt, end_dt,
                      organizer_email, attendee_emails):
    """Build a VCALENDAR with METHOD:REQUEST and return bytes."""
    cal = ICalCalendar()
    cal.add("prodid", "-//MarcoDigital//ES")
    cal.add("version", "2.0")
    cal.add("method", "REQUEST")

    event = ICalEvent()
    event.add("summary", title)
    event.add("description", description or "")
    event.add("dtstart", start_dt)
    event.add("dtend", end_dt)
    event.add("uid", f"{uuid.uuid4()}@marcodigital")
    event.add("dtstamp", datetime.datetime.now(datetime.timezone.utc))
    event.add("created", datetime.datetime.now(datetime.timezone.utc))
    event.add("status", "CONFIRMED")
    event.add("sequence", 0)

    org = vCalAddress(f"mailto:{organizer_email}")
    org.params["cn"] = vText("Marco Digital")
    event.add("organizer", org)

    for addr in attendee_emails:
        att = vCalAddress(f"mailto:{addr}")
        att.params["ROLE"]     = vText("REQ-PARTICIPANT")
        att.params["PARTSTAT"] = vText("NEEDS-ACTION")
        att.params["RSVP"]     = vText("TRUE")
        event.add("attendee", att)

    cal.add_component(event)
    return cal.to_ical()


def send_email(cfg, to_list, subject, body, ics_bytes=None):
    """Send plain‑text email, optionally with a .ics attachment."""
    user = cfg.get("gmail_user", "")
    pwd  = cfg.get("gmail_app_password", "")
    if not user or not pwd:
        print("[SMTP] No credentials configured.")
        return False

    msg = MIMEMultipart("mixed")
    msg["From"]    = user
    msg["To"]      = ", ".join(to_list)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if ics_bytes:
        part = MIMEBase("text", "calendar", method="REQUEST", charset="utf-8")
        part.set_payload(ics_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename="invite.ics")
        msg.attach(part)

    try:
        smtp_host = cfg.get("smtp_server", "")
        smtp_port = cfg.get("smtp_port", 465)
        if not smtp_host:
            print("[SMTP] No smtp_server configured.")
            return False
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as srv:
            srv.login(user, pwd)
            srv.sendmail(user, to_list, msg.as_string())
        print(f"[SMTP] Enviado a {to_list}")
        return True
    except Exception as e:
        print(f"[SMTP] Error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════
# EMAIL POLLER  (background daemon thread)
# ═══════════════════════════════════════════════════════════════════════

class EmailPoller(threading.Thread):
    """Every N seconds: check Gmail for 'compra' and 'foto' emails."""

    def __init__(self, cfg, shopping, msg_q):
        super().__init__(daemon=True)
        self.cfg      = cfg
        self.shopping = shopping
        self.q        = msg_q
        self.interval = cfg.get("email_poll_interval_sec", 30)
        self.running  = True

    def run(self):
        # Small initial delay so the GUI can start up
        time.sleep(5)
        while self.running:
            try:
                self._poll()
            except Exception:
                traceback.print_exc()
            time.sleep(self.interval)

    def stop(self):
        self.running = False

    # ── internals ─────────────────────────────────────────────────────
    def _poll(self):
        user = self.cfg.get("gmail_user", "")
        pwd  = self.cfg.get("gmail_app_password", "")
        if not user or not pwd:
            return

        try:
            imap_host = self.cfg.get("imap_server", "")
            if not imap_host:
                return
            mail = imaplib.IMAP4_SSL(imap_host)
            mail.login(user, pwd)
            mail.select("inbox")
        except Exception as e:
            print(f"[IMAP] Conexión fallida: {e}")
            return

        try:
            self._poll_shopping(mail)
            self._poll_photos(mail)
        finally:
            try:
                mail.logout()
            except Exception:
                pass

    def _poll_shopping(self, mail):
        ok, data = mail.search(None, '(UNSEEN SUBJECT "compra")')
        if ok != "OK":
            return
        for eid in data[0].split():
            if not eid:
                continue
            try:
                _, raw = mail.fetch(eid, "(RFC822)")
                for part in raw:
                    if isinstance(part, tuple):
                        msg  = email_mod.message_from_bytes(part[1])
                        body = self._body(msg)
                        if body:
                            lines = [l.strip() for l in body.splitlines() if l.strip()]
                            if lines:
                                self.shopping.add_items(lines)
                                self.q.put(("shopping", lines))
                mail.store(eid, "+FLAGS", "\\Seen")
            except Exception as e:
                print(f"[IMAP] shopping error: {e}")

    def _poll_photos(self, mail):
        ok, data = mail.search(None, '(UNSEEN SUBJECT "foto")')
        if ok != "OK":
            return
        os.makedirs(FOTOS_DIR, exist_ok=True)
        for eid in data[0].split():
            if not eid:
                continue
            try:
                _, raw = mail.fetch(eid, "(RFC822)")
                for part in raw:
                    if isinstance(part, tuple):
                        msg = email_mod.message_from_bytes(part[1])
                        self._save_images(msg)
                mail.store(eid, "+FLAGS", "\\Seen")
            except Exception as e:
                print(f"[IMAP] foto error: {e}")

    def _body(self, msg):
        if msg.is_multipart():
            for p in msg.walk():
                if p.get_content_type() == "text/plain" and \
                   "attachment" not in str(p.get("Content-Disposition", "")):
                    payload = p.get_payload(decode=True)
                    if payload:
                        return payload.decode(p.get_content_charset() or "utf-8",
                                              errors="replace")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode(msg.get_content_charset() or "utf-8",
                                      errors="replace")
        return ""

    def _save_images(self, msg):
        for p in msg.walk():
            ct = p.get_content_type()
            cd = str(p.get("Content-Disposition", ""))
            if not (ct.startswith("image/") or "attachment" in cd):
                continue
            fn = p.get_filename()
            if not fn:
                ext = ct.split("/")[-1].replace("jpeg", "jpg")
                if ext not in ("jpg", "png", "gif", "bmp", "webp"):
                    continue
                fn = f"foto_{int(time.time())}_{uuid.uuid4().hex[:6]}.{ext}"
            if not fn.lower().endswith(IMAGE_EXTENSIONS):
                continue
            data = p.get_payload(decode=True)
            if data:
                path = os.path.join(FOTOS_DIR, fn)
                with open(path, "wb") as f:
                    f.write(data)
                self.q.put(("photo", fn))
                print(f"[IMAP] Foto guardada: {fn}")


# ═══════════════════════════════════════════════════════════════════════
# WIDGET: SPANISH ON‑SCREEN KEYBOARD
# ═══════════════════════════════════════════════════════════════════════

class SpanishKeyboard(tk.Frame):
    """Touch‑friendly QWERTY keyboard with Ñ, accented vowels, ¿ ¡."""

    def __init__(self, parent, target_widget, on_enter=None, **kw):
        super().__init__(parent, bg=C["bg"], **kw)
        self.target   = target_widget
        self.on_enter = on_enter
        self._shifted = False
        self._accent  = False
        self._render()

    def set_target(self, widget):
        self.target = widget

    # ── build / rebuild ───────────────────────────────────────────────
    def _render(self):
        for w in self.winfo_children():
            w.destroy()

        rows = KB_ACCENT if self._accent else (KB_UPPER if self._shifted else KB_LOWER)

        for row in rows:
            rf = tk.Frame(self, bg=C["bg"])
            rf.pack(fill=tk.X, padx=2, pady=1)
            for key in row:
                if key == "⇧":
                    bg = C["accent"] if self._shifted else C["key_sp"]
                    cmd = self._toggle_shift
                    w = 4
                elif key == "⌫":
                    bg, cmd, w = C["key_sp"], self._bksp, 4
                else:
                    bg  = C["key_bg"]
                    cmd = lambda k=key: self._type(k)
                    w   = 3
                tk.Button(rf, text=key, font=("Arial", 19), bg=bg,
                          fg=C["text"], activebackground=C["accent_hi"],
                          relief=tk.FLAT, bd=0, width=w, height=1,
                          command=cmd).pack(side=tk.LEFT, padx=1, expand=True, fill=tk.X)

        # bottom row: accent‑toggle | space | enter
        bf = tk.Frame(self, bg=C["bg"])
        bf.pack(fill=tk.X, padx=2, pady=1)

        abg = C["accent"] if self._accent else C["key_sp"]
        tk.Button(bf, text="ÁÉÍ", font=("Arial", 17), bg=abg, fg=C["text"],
                  activebackground=C["accent_hi"], relief=tk.FLAT, bd=0,
                  width=5, height=1, command=self._toggle_accent
                  ).pack(side=tk.LEFT, padx=1)

        tk.Button(bf, text="", font=("Arial", 19), bg=C["key_bg"], fg=C["text"],
                  activebackground=C["accent_hi"], relief=tk.FLAT, bd=0,
                  height=1, command=lambda: self._type(" ")
                  ).pack(side=tk.LEFT, padx=1, expand=True, fill=tk.X)

        tk.Button(bf, text="↵", font=("Arial", 26, "bold"), bg=C["success"],
                  fg=C["bg"], activebackground=C["accent_hi"],
                  relief=tk.FLAT, bd=0, width=5, height=1,
                  command=self._enter).pack(side=tk.LEFT, padx=1)

    # ── actions ───────────────────────────────────────────────────────
    def _type(self, ch):
        if isinstance(self.target, tk.Entry):
            self.target.insert(tk.END, ch)
        elif isinstance(self.target, tk.Text):
            self.target.insert(tk.END, ch)
        # auto‑unshift after one letter
        if self._shifted and not self._accent:
            self._shifted = False
            self._render()

    def _bksp(self):
        if isinstance(self.target, tk.Entry):
            c = self.target.get()
            if c:
                self.target.delete(len(c) - 1, tk.END)
        elif isinstance(self.target, tk.Text):
            self.target.delete("end-2c", "end-1c")

    def _toggle_shift(self):
        self._shifted = not self._shifted
        self._accent  = False
        self._render()

    def _toggle_accent(self):
        self._accent  = not self._accent
        self._shifted = False
        self._render()

    def _enter(self):
        if self.on_enter:
            self.on_enter()


# ═══════════════════════════════════════════════════════════════════════
# SCREEN: PHOTO SLIDESHOW  (idle / default)
# ═══════════════════════════════════════════════════════════════════════

class SlideshowScreen(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg="black")
        self.app = app
        self.photos = []
        self.idx    = 0
        self._photo_ref = None      # prevent GC
        self._after_id  = None

        self.label = tk.Label(self, bg="black")
        self.label.pack(expand=True, fill=tk.BOTH)

        self.clock = tk.Label(self, text="", font=("Arial", 22, "bold"),
                              fg="white", bg="black")
        self.clock.place(relx=0.97, rely=0.96, anchor=tk.SE)

        # tap anywhere → calendar
        self.label.bind("<Button-1>", lambda e: self.app.show_calendar())
        self.bind("<Button-1>",       lambda e: self.app.show_calendar())

        self._tick_clock()

    # ── lifecycle ─────────────────────────────────────────────────────
    def start(self):
        self._scan()
        self._next()

    def stop(self):
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None

    # ── internals ─────────────────────────────────────────────────────
    def _scan(self):
        os.makedirs(FOTOS_DIR, exist_ok=True)
        self.photos = sorted(
            os.path.join(FOTOS_DIR, f)
            for f in os.listdir(FOTOS_DIR)
            if f.lower().endswith(IMAGE_EXTENSIONS)
               and os.path.isfile(os.path.join(FOTOS_DIR, f))
        )

    def _next(self):
        self._scan()                # pick up newly added photos

        if not self.photos:
            self.label.config(image="",
                              text="No hay fotos en 'fotos/'",
                              font=("Arial", 30), fg=C["text_muted"])
            self._after_id = self.after(5000, self._next)
            return

        if self.idx >= len(self.photos):
            self.idx = 0

        try:
            img = Image.open(self.photos[self.idx])
            img = self._fix_orientation(img)

            # get actual window size (fallback to constants if not rendered yet)
            sw = self.winfo_width()
            sh = self.winfo_height()
            if sw < 100 or sh < 100:
                sw, sh = SCREEN_W, SCREEN_H

            iw, ih = img.size
            
            if iw >= ih:
                # Landscape: scale to fill (no black bars), crop excess
                ratio  = max(sw / iw, sh / ih)
                new_w, new_h = int(iw * ratio), int(ih * ratio)
                img    = img.resize((new_w, new_h), Image.LANCZOS)
                
                # center crop to exact screen size
                left = (new_w - sw) // 2
                top = (new_h - sh) // 2
                img = img.crop((left, top, left + sw, top + sh))
            else:
                # Portrait: scale to fit (see whole photo), no cropping
                ratio  = min(sw / iw, sh / ih)
                new_w, new_h = int(iw * ratio), int(ih * ratio)
                img    = img.resize((new_w, new_h), Image.LANCZOS)

            self._photo_ref = ImageTk.PhotoImage(img)
            self.label.config(image=self._photo_ref, text="")
        except Exception as e:
            print(f"[SLIDE] Error {self.photos[self.idx]}: {e}")

        self.idx += 1
        ms = self.app.cfg.get("slideshow_interval_sec", 10) * 1000
        self._after_id = self.after(ms, self._next)

    @staticmethod
    def _fix_orientation(img):
        try:
            for tag, name in ExifTags.TAGS.items():
                if name == "Orientation":
                    break
            exif = img._getexif()
            if exif and tag in exif:
                o = exif[tag]
                if   o == 3: img = img.rotate(180, expand=True)
                elif o == 6: img = img.rotate(270, expand=True)
                elif o == 8: img = img.rotate(90,  expand=True)
        except Exception:
            pass
        return img

    def _tick_clock(self):
        self.clock.config(text=datetime.datetime.now().strftime("%H:%M"))
        self.after(30_000, self._tick_clock)


# ═══════════════════════════════════════════════════════════════════════
# SCREEN: CALENDAR WEEK VIEW
# ═══════════════════════════════════════════════════════════════════════

class CalendarScreen(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self.week_offset = 0
        self._ev_cache   = []
        self._ev_ts      = 0.0
        self._build_skeleton()

    # ── skeleton (header + grid + footer) ─────────────────────────────
    def _build_skeleton(self):
        # header
        hdr = tk.Frame(self, bg=C["bg_header"], height=48)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        self.btn_prev = tk.Button(hdr, text="◀", font=("Arial", 26, "bold"),
            bg=C["bg_header"], fg=C["text"], activebackground=C["secondary"],
            relief=tk.FLAT, bd=0, width=3, command=self._prev)
        self.btn_prev.pack(side=tk.LEFT, padx=4)

        self.lbl_week = tk.Label(hdr, text="", font=("Arial", 30, "bold"),
            bg=C["bg_header"], fg=C["text"])
        self.lbl_week.pack(side=tk.LEFT, expand=True)

        self.btn_next = tk.Button(hdr, text="▶", font=("Arial", 26, "bold"),
            bg=C["bg_header"], fg=C["text"], activebackground=C["secondary"],
            relief=tk.FLAT, bd=0, width=3, command=self._next)
        self.btn_next.pack(side=tk.LEFT, padx=4)

        tk.Button(hdr, text="HOY", font=("Arial", 22, "bold"),
            bg=C["accent"], fg=C["text"], activebackground=C["accent_hi"],
            relief=tk.FLAT, bd=0, padx=10,
            command=self._today).pack(side=tk.RIGHT, padx=8)

        # main grid
        self.grid_fr = tk.Frame(self, bg=C["bg"])
        self.grid_fr.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # footer
        foot = tk.Frame(self, bg=C["bg_header"], height=48)
        foot.pack(fill=tk.X, side=tk.BOTTOM)
        foot.pack_propagate(False)

        for txt, clr, fg, cmd in [
            ("🏠 Fotos",   C["secondary"], C["text"], self.app.show_slideshow),
            ("➕ Evento",  C["accent"],    C["text"], self.app.show_event_creation),
            ("🛒 Compra",  C["success"],   C["bg"],   self.app.show_shopping),
            ("📋 Tareas",  C["warning"],   C["bg"],   self.app.show_tareas),
        ]:
            tk.Button(foot, text=txt, font=("Arial", 22, "bold"),
                bg=clr, fg=fg, activebackground=C["accent_hi"],
                relief=tk.FLAT, bd=0, padx=12,
                command=cmd).pack(side=tk.LEFT, padx=4, pady=5, expand=True, fill=tk.X)

    # ── refresh ───────────────────────────────────────────────────────
    def refresh(self):
        self.week_offset = max(-8, min(8, self.week_offset))

        today  = datetime.date.today()
        monday = today - datetime.timedelta(days=today.weekday()) \
                       + datetime.timedelta(weeks=self.week_offset)
        sunday = monday + datetime.timedelta(days=6)

        # header label
        if monday.month == sunday.month:
            txt = f"{monday.day} — {sunday.day} {MESES_CORTO[monday.month-1]} {monday.year}"
        else:
            txt = (f"{monday.day} {MESES_CORTO[monday.month-1]} — "
                   f"{sunday.day} {MESES_CORTO[sunday.month-1]} {sunday.year}")
        self.lbl_week.config(text=txt)

        # weather (threaded first time, cached afterwards)
        self.app.weather.fetch_all()

        # calendar events (cache 5 min)
        if time.time() - self._ev_ts > 300:
            s = monday - datetime.timedelta(days=7)
            e = sunday + datetime.timedelta(days=8)
            self._ev_cache = fetch_ical_events(self.app.cfg.get("ical_url", ""), s, e)
            self._ev_ts = time.time()

        # rebuild grid
        for w in self.grid_fr.winfo_children():
            w.destroy()
        for col in range(7):
            self.grid_fr.columnconfigure(col, weight=1, uniform="d")
        self.grid_fr.rowconfigure(0, weight=1)

        for col in range(7):
            day = monday + datetime.timedelta(days=col)
            is_today = (day == today)
            bg = C["today_bg"] if is_today else C["bg_card"]

            cell = tk.Frame(self.grid_fr, bg=bg,
                            highlightbackground=C["border"], highlightthickness=1)
            cell.grid(row=0, column=col, sticky="nsew", padx=1, pady=1)

            # day header
            hbg = C["accent"] if is_today else C["bg_header"]
            dh  = tk.Frame(cell, bg=hbg)
            dh.pack(fill=tk.X)
            tk.Label(dh, text=f"{DIAS_CORTO[col]} {day.day}",
                     font=("Arial", 26, "bold"), bg=hbg, fg=C["text"]).pack(pady=2)

            # weather
            ds = day.strftime("%Y-%m-%d")
            wf = tk.Frame(cell, bg=bg)
            wf.pack(fill=tk.X, padx=2, pady=1)
            for city in self.app.cities:
                w = self.app.weather.get(city["code"], ds)
                if w:
                    t = f"{city['code']} {w['icon']}{w['max']}°"
                    fg = C["text"]
                else:
                    t  = f"{city['code']} —"
                    fg = C["text_dim"]
                tk.Label(wf, text=t, font=("Arial", 30), bg=bg, fg=fg,
                         anchor="w").pack(fill=tk.X)

            tk.Frame(cell, bg=C["border"], height=1).pack(fill=tk.X, pady=2)

            # events
            ef = tk.Frame(cell, bg=bg)
            ef.pack(fill=tk.BOTH, expand=True, padx=2)
            devs = self._day_events(day)
            for ev in devs[:6]:
                tstr = ""
                if not ev["all_day"] and isinstance(ev["start"], datetime.datetime):
                    tstr = ev["start"].strftime("%H:%M ")
                label = f"{tstr}{ev['summary']}"
                if len(label) > 16:
                    label = label[:15] + "…"
                fc = C["warning"] if ev["all_day"] else C["text"]
                tk.Label(ef, text=label, font=("Arial", 30), bg=bg, fg=fc,
                         anchor="w", wraplength=100).pack(fill=tk.X)
            if len(devs) > 6:
                tk.Label(ef, text=f"+{len(devs)-6} más", font=("Arial", 17),
                         bg=bg, fg=C["text_dim"]).pack(fill=tk.X)

    def _day_events(self, target):
        out = []
        for ev in self._ev_cache:
            s = ev["start"]
            if s is None:
                continue
            d = s.date() if isinstance(s, datetime.datetime) else s
            if d == target:
                out.append(ev)
        out.sort(key=lambda e: (
            not e["all_day"],
            e["start"] if isinstance(e["start"], datetime.datetime)
            else datetime.datetime.min
        ))
        return out

    def _prev(self):
        self.week_offset -= 1
        self.refresh()

    def _next(self):
        self.week_offset += 1
        self.refresh()

    def _today(self):
        self.week_offset = 0
        self.refresh()


# ═══════════════════════════════════════════════════════════════════════
# SCREEN: EVENT CREATION (sends .ics invite to distribution list)
# ═══════════════════════════════════════════════════════════════════════

class EventCreationScreen(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._active_entry = None
        self._spinner_labels = {}
        self._build()

    # ── build ─────────────────────────────────────────────────────────
    def _build(self):
        for w in self.winfo_children():
            w.destroy()
        self._spinner_labels = {}

        # header
        hdr = tk.Frame(self, bg=C["bg_header"], height=42)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="➕ Nuevo Evento", font=("Arial", 19, "bold"),
                 bg=C["bg_header"], fg=C["text"]).pack(side=tk.LEFT, padx=12)

        # form
        form = tk.Frame(self, bg=C["bg"])
        form.pack(fill=tk.X, padx=12, pady=4)
        form.columnconfigure(1, weight=1)

        now = datetime.datetime.now()

        # título
        tk.Label(form, text="Título:", font=("Arial", 17), bg=C["bg"],
                 fg=C["text"]).grid(row=0, column=0, sticky="w", pady=2)
        self.e_title = tk.Entry(form, font=("Arial", 30), bg=C["bg_card"],
                                fg=C["text"], insertbackground=C["text"],
                                relief=tk.FLAT, bd=2)
        self.e_title.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        self.e_title.bind("<FocusIn>", lambda e: self._focus(self.e_title))

        # fecha
        tk.Label(form, text="Fecha:", font=("Arial", 17), bg=C["bg"],
                 fg=C["text"]).grid(row=1, column=0, sticky="w", pady=2)
        df = tk.Frame(form, bg=C["bg"])
        df.grid(row=1, column=1, sticky="w", padx=5, pady=2)

        self.v_day   = tk.IntVar(value=now.day)
        self.v_month = tk.IntVar(value=now.month)
        self.v_year  = tk.IntVar(value=now.year)
        self._spinner(df, self.v_day,   1, 31,   w=3, key="day")
        tk.Label(df, text="/", font=("Arial", 19, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(side=tk.LEFT)
        self._spinner(df, self.v_month, 1, 12,   w=3, key="month")
        tk.Label(df, text="/", font=("Arial", 19, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(side=tk.LEFT)
        self._spinner(df, self.v_year,  2024, 2035, w=5, key="year")

        # hora inicio
        tk.Label(form, text="Inicio:", font=("Arial", 17), bg=C["bg"],
                 fg=C["text"]).grid(row=2, column=0, sticky="w", pady=2)
        tf1 = tk.Frame(form, bg=C["bg"])
        tf1.grid(row=2, column=1, sticky="w", padx=5, pady=2)
        self.v_sh = tk.IntVar(value=now.hour)
        self.v_sm = tk.IntVar(value=0)
        self._spinner(tf1, self.v_sh, 0, 23, w=3, key="sh")
        tk.Label(tf1, text=":", font=("Arial", 19, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(side=tk.LEFT)
        self._spinner(tf1, self.v_sm, 0, 59, w=3, step=15, key="sm")

        # hora fin
        tk.Label(form, text="Fin:", font=("Arial", 17), bg=C["bg"],
                 fg=C["text"]).grid(row=3, column=0, sticky="w", pady=2)
        tf2 = tk.Frame(form, bg=C["bg"])
        tf2.grid(row=3, column=1, sticky="w", padx=5, pady=2)
        self.v_eh = tk.IntVar(value=(now.hour + 1) % 24)
        self.v_em = tk.IntVar(value=0)
        self._spinner(tf2, self.v_eh, 0, 23, w=3, key="eh")
        tk.Label(tf2, text=":", font=("Arial", 19, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(side=tk.LEFT)
        self._spinner(tf2, self.v_em, 0, 59, w=3, step=15, key="em")

        # descripción
        tk.Label(form, text="Descripción:", font=("Arial", 17), bg=C["bg"],
                 fg=C["text"]).grid(row=4, column=0, sticky="w", pady=2)
        self.e_desc = tk.Entry(form, font=("Arial", 30), bg=C["bg_card"],
                               fg=C["text"], insertbackground=C["text"],
                               relief=tk.FLAT, bd=2)
        self.e_desc.grid(row=4, column=1, sticky="ew", padx=5, pady=2)
        self.e_desc.bind("<FocusIn>", lambda e: self._focus(self.e_desc))

        # buttons
        bf = tk.Frame(form, bg=C["bg"])
        bf.grid(row=5, column=0, columnspan=2, pady=4)
        tk.Button(bf, text="📧 Enviar Invitación", font=("Arial", 17, "bold"),
                  bg=C["success"], fg=C["bg"], activebackground=C["accent_hi"],
                  relief=tk.FLAT, bd=0, padx=16, pady=4,
                  command=self._submit).pack(side=tk.LEFT, padx=8)
        tk.Button(bf, text="Cancelar", font=("Arial", 17, "bold"),
                  bg=C["accent"], fg=C["text"], activebackground=C["accent_hi"],
                  relief=tk.FLAT, bd=0, padx=16, pady=4,
                  command=self.app.show_calendar).pack(side=tk.LEFT, padx=8)

        # status
        self.lbl_status = tk.Label(form, text="", font=("Arial", 22),
                                   bg=C["bg"], fg=C["success"])
        self.lbl_status.grid(row=6, column=0, columnspan=2, pady=1)

        # keyboard at the bottom
        self.kb = SpanishKeyboard(self, self.e_title)
        self.kb.pack(fill=tk.X, side=tk.BOTTOM, padx=2, pady=2)
        self._active_entry = self.e_title

    # ── spinner helper ────────────────────────────────────────────────
    def _spinner(self, parent, var, lo, hi, w=3, step=1, key=""):
        fr = tk.Frame(parent, bg=C["bg"])
        fr.pack(side=tk.LEFT, padx=2)

        def fmt():
            return f"{var.get():02d}" if hi < 100 else str(var.get())

        def inc():
            v = var.get() + step
            if v > hi:
                v = lo
            var.set(v)
            lbl.config(text=fmt())

        def dec():
            v = var.get() - step
            if v < lo:
                v = hi - (hi % step) if step > 1 else hi
            var.set(v)
            lbl.config(text=fmt())

        tk.Button(fr, text="▲", font=("Arial", 15), bg=C["key_sp"], fg=C["text"],
                  relief=tk.FLAT, bd=0, width=w, command=inc).pack()
        lbl = tk.Label(fr, text=fmt(), font=("Arial", 30, "bold"),
                       bg=C["bg_card"], fg=C["text"], width=w)
        lbl.pack(pady=1)
        tk.Button(fr, text="▼", font=("Arial", 15), bg=C["key_sp"], fg=C["text"],
                  relief=tk.FLAT, bd=0, width=w, command=dec).pack()

        if key:
            self._spinner_labels[key] = lbl

    def _focus(self, entry):
        self._active_entry = entry
        self.kb.set_target(entry)

    # ── submit ────────────────────────────────────────────────────────
    def _submit(self):
        title = self.e_title.get().strip()
        if not title:
            self.lbl_status.config(text="⚠ Escribe un título", fg=C["accent"])
            return

        try:
            sdt = datetime.datetime(self.v_year.get(), self.v_month.get(),
                                    self.v_day.get(), self.v_sh.get(), self.v_sm.get())
            edt = datetime.datetime(self.v_year.get(), self.v_month.get(),
                                    self.v_day.get(), self.v_eh.get(), self.v_em.get())
            if edt <= sdt:
                edt += datetime.timedelta(days=1)
        except ValueError:
            self.lbl_status.config(text="⚠ Fecha inválida", fg=C["accent"])
            return

        desc = self.e_desc.get().strip()
        dist = self.app.cfg.get("distribution_list", [])
        emails = [p["email"] for p in dist]
        org = self.app.cfg.get("gmail_user", "")

        if not emails:
            self.lbl_status.config(text="⚠ Lista de distribución vacía", fg=C["accent"])
            return

        ics = create_ics_invite(title, desc, sdt, edt, org, emails)
        body = (f"Nuevo evento:\n\n"
                f"  Título:      {title}\n"
                f"  Fecha:       {sdt.strftime('%d/%m/%Y')}\n"
                f"  Hora:        {sdt.strftime('%H:%M')} — {edt.strftime('%H:%M')}\n"
                f"  Descripción: {desc}\n\n"
                f"Enviado desde Marco Digital")

        self.lbl_status.config(text="Enviando…", fg=C["warning"])
        self.update()

        def worker():
            ok = send_email(self.app.cfg, emails, f"Invitación: {title}", body, ics)
            self.after(0, lambda: self._done(ok))
        threading.Thread(target=worker, daemon=True).start()

    def _done(self, ok):
        if ok:
            self.lbl_status.config(text="✓ Invitación enviada", fg=C["success"])
            self.after(2000, self.app.show_calendar)
        else:
            self.lbl_status.config(text="✗ Error al enviar", fg=C["accent"])

    def reset(self):
        self._build()


# ═══════════════════════════════════════════════════════════════════════
# SCREEN: SHOPPING LIST  ("Lista de la Compra")
# ═══════════════════════════════════════════════════════════════════════

class ShoppingListScreen(tk.Frame):
    ITEMS_PER_PAGE = 7

    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self.scroll = 0
        self._build_skeleton()

    def _build_skeleton(self):
        # header
        hdr = tk.Frame(self, bg=C["bg_header"], height=42)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🛒 Lista de la Compra", font=("Arial", 30, "bold"),
                 bg=C["bg_header"], fg=C["text"]).pack(side=tk.LEFT, padx=12)

        # body (dynamic)
        self.body = tk.Frame(self, bg=C["bg"])
        self.body.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # footer (dynamic)
        self.foot = tk.Frame(self, bg=C["bg_header"], height=48)
        self.foot.pack(fill=tk.X, side=tk.BOTTOM)
        self.foot.pack_propagate(False)

    # ── refresh (list view) ──────────────────────────────────────────
    def refresh(self):
        self._clear(self.body)
        self._build_footer_buttons()

        items = self.app.shopping.get_items()
        if not items:
            tk.Label(self.body, text="La lista está vacía",
                     font=("Arial", 30), bg=C["bg"],
                     fg=C["text_muted"]).pack(pady=50)
            return

        # unchecked first, then checked
        indexed = sorted(enumerate(items), key=lambda x: x[1]["checked"])
        total   = len(indexed)
        page    = indexed[self.scroll : self.scroll + self.ITEMS_PER_PAGE]

        # paging nav
        if total > self.ITEMS_PER_PAGE:
            nav = tk.Frame(self.body, bg=C["bg"])
            nav.pack(fill=tk.X, pady=1)
            if self.scroll > 0:
                tk.Button(nav, text="▲", font=("Arial", 22), bg=C["key_sp"],
                    fg=C["text"], relief=tk.FLAT, bd=0,
                    command=self._pgup).pack(side=tk.LEFT, padx=4)
            tk.Label(nav, text=f"{self.scroll+1}–{min(self.scroll+self.ITEMS_PER_PAGE, total)} / {total}",
                     font=("Arial", 20), bg=C["bg"], fg=C["text_muted"]).pack(side=tk.LEFT, expand=True)
            if self.scroll + self.ITEMS_PER_PAGE < total:
                tk.Button(nav, text="▼", font=("Arial", 22), bg=C["key_sp"],
                    fg=C["text"], relief=tk.FLAT, bd=0,
                    command=self._pgdn).pack(side=tk.RIGHT, padx=4)

        # items
        for orig_idx, item in page:
            chk = item["checked"]
            bg  = C["checked_bg"] if chk else C["bg_card"]

            row = tk.Frame(self.body, bg=bg,
                           highlightbackground=C["border"], highlightthickness=1)
            row.pack(fill=tk.X, pady=2)

            sym = "☑" if chk else "☐"
            tk.Button(row, text=sym, font=("Arial", 30), bg=bg,
                      fg=C["success"] if chk else C["text"],
                      relief=tk.FLAT, bd=0, width=2,
                      command=lambda i=orig_idx: self._toggle(i)
                      ).pack(side=tk.LEFT, padx=4, pady=2)

            fg = C["text_dim"] if chk else C["text"]
            tk.Label(row, text=f"  {item['text']}", font=("Arial", 30),
                     bg=bg, fg=fg, anchor="w"
                     ).pack(side=tk.LEFT, fill=tk.X, expand=True, pady=2)

    # ── footer buttons ────────────────────────────────────────────────
    def _build_footer_buttons(self):
        self._clear(self.foot)
        for txt, bg, fg, cmd in [
            ("◀ Volver",    C["secondary"], C["text"], self.app.show_calendar),
            ("➕ Añadir",   C["success"],   C["bg"],   self._show_add),
            ("📧 Enviar",   C["warning"],   C["bg"],   self._show_send),
            ("🗑 Borrar ✓", C["accent"],    C["text"], self._del_checked),
        ]:
            tk.Button(self.foot, text=txt, font=("Arial", 26, "bold"),
                bg=bg, fg=fg, activebackground=C["accent_hi"],
                relief=tk.FLAT, bd=0, padx=6,
                command=cmd).pack(side=tk.LEFT, padx=3, pady=5, expand=True, fill=tk.X)

    # ── actions ──────────────────────────────────────────────────────
    def _toggle(self, idx):
        self.app.shopping.toggle(idx)
        self.refresh()

    def _pgup(self):
        self.scroll = max(0, self.scroll - self.ITEMS_PER_PAGE)
        self.refresh()

    def _pgdn(self):
        self.scroll += self.ITEMS_PER_PAGE
        self.refresh()

    def _del_checked(self):
        self.app.shopping.remove_checked()
        self.scroll = 0
        self.refresh()

    # ── add item mode ─────────────────────────────────────────────────
    def _show_add(self):
        self._clear(self.body)
        self._clear(self.foot)

        tk.Label(self.body, text="Nuevo artículo:", font=("Arial", 22),
                 bg=C["bg"], fg=C["text"]).pack(anchor="w", padx=8, pady=(6, 2))

        self._add_entry = tk.Entry(self.body, font=("Arial", 30),
                                    bg=C["bg_card"], fg=C["text"],
                                    insertbackground=C["text"],
                                    relief=tk.FLAT, bd=2)
        self._add_entry.pack(fill=tk.X, padx=8, pady=4)
        self._add_entry.focus_set()

        self._add_kb = SpanishKeyboard(self.body, self._add_entry,
                                        on_enter=self._do_add)
        self._add_kb.pack(fill=tk.X, padx=4)

        tk.Button(self.foot, text="◀ Volver a la lista", font=("Arial", 22, "bold"),
                  bg=C["accent"], fg=C["text"], activebackground=C["accent_hi"],
                  relief=tk.FLAT, bd=0, padx=16,
                  command=self.refresh).pack(side=tk.LEFT, padx=4, pady=5,
                                             expand=True, fill=tk.X)

    def _do_add(self):
        txt = self._add_entry.get().strip()
        if txt:
            self.app.shopping.add_item(txt)
            self._add_entry.delete(0, tk.END)

    # ── send list mode ────────────────────────────────────────────────
    def _show_send(self):
        unchecked = self.app.shopping.get_unchecked_texts()
        if not unchecked:
            return
        self._clear(self.body)
        self._clear(self.foot)

        tk.Label(self.body, text="Enviar lista a:", font=("Arial", 30, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(anchor="w", padx=8, pady=4)

        dist = self.app.cfg.get("distribution_list", [])
        self._send_vars = {}
        for p in dist:
            v = tk.BooleanVar(value=True)
            self._send_vars[p["email"]] = v
            rf = tk.Frame(self.body, bg=C["bg_card"],
                          highlightbackground=C["border"], highlightthickness=1)
            rf.pack(fill=tk.X, padx=8, pady=2)
            tk.Checkbutton(rf, text=f"  {p['name']}  ({p['email']})",
                           variable=v, font=("Arial", 22),
                           bg=C["bg_card"], fg=C["text"],
                           selectcolor=C["bg"],
                           activebackground=C["bg_card"],
                           activeforeground=C["text"]).pack(anchor="w", padx=8, pady=4)

        # preview
        tk.Label(self.body, text="Artículos pendientes:", font=("Arial", 22),
                 bg=C["bg"], fg=C["text_muted"]).pack(anchor="w", padx=8, pady=(8, 2))
        preview = "\n".join(f"  • {i}" for i in unchecked[:6])
        if len(unchecked) > 6:
            preview += f"\n  … y {len(unchecked)-6} más"
        tk.Label(self.body, text=preview, font=("Arial", 20), bg=C["bg"],
                 fg=C["text"], justify=tk.LEFT, anchor="nw").pack(anchor="w", padx=8)

        # footer
        tk.Button(self.foot, text="◀ Cancelar", font=("Arial", 22, "bold"),
                  bg=C["accent"], fg=C["text"], relief=tk.FLAT, bd=0, padx=14,
                  command=self.refresh).pack(side=tk.LEFT, padx=4, pady=5,
                                             expand=True, fill=tk.X)
        tk.Button(self.foot, text="📧 Enviar", font=("Arial", 22, "bold"),
                  bg=C["success"], fg=C["bg"], relief=tk.FLAT, bd=0, padx=14,
                  command=self._do_send).pack(side=tk.LEFT, padx=4, pady=5,
                                              expand=True, fill=tk.X)

    def _do_send(self):
        sel = [e for e, v in self._send_vars.items() if v.get()]
        if not sel:
            return
        items = self.app.shopping.get_unchecked_texts()
        body  = "🛒 Lista de la Compra:\n\n"
        body += "\n".join(f"  • {i}" for i in items)
        body += f"\n\nTotal: {len(items)} artículos"
        body += "\n\nEnviado desde Marco Digital"

        def worker():
            ok = send_email(self.app.cfg, sel, "🛒 Lista de la Compra", body)
            self.after(0, lambda: self._send_done(ok))
        threading.Thread(target=worker, daemon=True).start()

    def _send_done(self, ok):
        self._clear(self.body)
        if ok:
            tk.Label(self.body, text="✓ Lista enviada", font=("Arial", 30, "bold"),
                     bg=C["bg"], fg=C["success"]).pack(pady=60)
        else:
            tk.Label(self.body, text="✗ Error al enviar", font=("Arial", 30, "bold"),
                     bg=C["bg"], fg=C["accent"]).pack(pady=60)
        self.after(1500, self.refresh)

    # ── util ──────────────────────────────────────────────────────────
    @staticmethod
    def _clear(frame):
        for w in frame.winfo_children():
            w.destroy()


# ═══════════════════════════════════════════════════════════════════════
# SCREEN: TAREAS (Tasks)
# ═══════════════════════════════════════════════════════════════════════

class TareasScreen(tk.Frame):
    ITEMS_PER_PAGE = 7

    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self.scroll = 0
        self._build_skeleton()

    def _build_skeleton(self):
        hdr = tk.Frame(self, bg=C["bg_header"], height=42)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="📋 Tareas Mensuales", font=("Arial", 30, "bold"),
                 bg=C["bg_header"], fg=C["text"]).pack(side=tk.LEFT, padx=12)

        self.body = tk.Frame(self, bg=C["bg"])
        self.body.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self.foot = tk.Frame(self, bg=C["bg_header"], height=48)
        self.foot.pack(fill=tk.X, side=tk.BOTTOM)
        self.foot.pack_propagate(False)

    def refresh(self):
        self._clear(self.body)
        self._build_footer_buttons()

        items = self.app.tareas_mgr.get_items()
        if not items:
            tk.Label(self.body, text="No hay tareas configuradas.",
                     font=("Arial", 30), bg=C["bg"],
                     fg=C["text_muted"]).pack(pady=50)
            return

        indexed = sorted(enumerate(items), key=lambda x: x[1]["checked"])
        total = len(indexed)
        page = indexed[self.scroll : self.scroll + self.ITEMS_PER_PAGE]

        if total > self.ITEMS_PER_PAGE:
            nav = tk.Frame(self.body, bg=C["bg"])
            nav.pack(fill=tk.X, pady=1)
            if self.scroll > 0:
                tk.Button(nav, text="▲", font=("Arial", 22), bg=C["key_sp"],
                    fg=C["text"], relief=tk.FLAT, bd=0,
                    command=self._pgup).pack(side=tk.LEFT, padx=4)
            tk.Label(nav, text=f"{self.scroll+1}–{min(self.scroll+self.ITEMS_PER_PAGE, total)} / {total}",
                     font=("Arial", 20), bg=C["bg"], fg=C["text_muted"]).pack(side=tk.LEFT, expand=True)
            if self.scroll + self.ITEMS_PER_PAGE < total:
                tk.Button(nav, text="▼", font=("Arial", 22), bg=C["key_sp"],
                    fg=C["text"], relief=tk.FLAT, bd=0,
                    command=self._pgdn).pack(side=tk.RIGHT, padx=4)

        for orig_idx, item in page:
            chk = item["checked"]
            bg = C["checked_bg"] if chk else C["bg_card"]

            row = tk.Frame(self.body, bg=bg,
                           highlightbackground=C["border"], highlightthickness=1)
            row.pack(fill=tk.X, pady=2)

            sym = "☑" if chk else "☐"
            tk.Button(row, text=sym, font=("Arial", 30), bg=bg,
                      fg=C["success"] if chk else C["text"],
                      relief=tk.FLAT, bd=0, width=2,
                      command=lambda i=orig_idx: self._toggle(i)
                      ).pack(side=tk.LEFT, padx=4, pady=2)

            fg = C["text_dim"] if chk else C["text"]
            tk.Label(row, text=f"  {item['text']}", font=("Arial", 30),
                     bg=bg, fg=fg, anchor="w"
                     ).pack(side=tk.LEFT, fill=tk.X, expand=True, pady=2)

    def _toggle(self, idx):
        self.app.tareas_mgr.toggle(idx)
        self.refresh()

    def _pgup(self):
        self.scroll = max(0, self.scroll - self.ITEMS_PER_PAGE)
        self.refresh()

    def _pgdn(self):
        self.scroll += self.ITEMS_PER_PAGE
        self.refresh()

    # ── footer buttons ────────────────────────────────────────────────
    def _build_footer_buttons(self):
        self._clear(self.foot)
        for txt, bg, fg, cmd in [
            ("◀ Volver",    C["secondary"], C["text"], self.app.show_calendar),
            ("➕ Añadir",   C["success"],   C["bg"],   self._show_add),
            ("🗑 Borrar ✓", C["accent"],    C["text"], self._del_checked),
        ]:
            tk.Button(self.foot, text=txt, font=("Arial", 26, "bold"),
                bg=bg, fg=fg, activebackground=C["accent_hi"],
                relief=tk.FLAT, bd=0, padx=6,
                command=cmd).pack(side=tk.LEFT, padx=3, pady=5, expand=True, fill=tk.X)

    def _del_checked(self):
        self.app.tareas_mgr.remove_checked()
        self.scroll = 0
        self.refresh()

    # ── add item mode ─────────────────────────────────────────────────
    def _show_add(self):
        self._clear(self.body)
        self._clear(self.foot)

        tk.Label(self.body, text="Nueva tarea:", font=("Arial", 22),
                 bg=C["bg"], fg=C["text"]).pack(anchor="w", padx=8, pady=(6, 2))

        self._add_entry = tk.Entry(self.body, font=("Arial", 30),
                                    bg=C["bg_card"], fg=C["text"],
                                    insertbackground=C["text"],
                                    relief=tk.FLAT, bd=2)
        self._add_entry.pack(fill=tk.X, padx=8, pady=4)
        self._add_entry.focus_set()

        self._add_kb = SpanishKeyboard(self.body, self._add_entry,
                                        on_enter=self._do_add)
        self._add_kb.pack(fill=tk.X, padx=4)

        tk.Button(self.foot, text="◀ Volver a la lista", font=("Arial", 22, "bold"),
                  bg=C["accent"], fg=C["text"], activebackground=C["accent_hi"],
                  relief=tk.FLAT, bd=0, padx=16,
                  command=self.refresh).pack(side=tk.LEFT, padx=4, pady=5,
                                             expand=True, fill=tk.X)

    def _do_add(self):
        txt = self._add_entry.get().strip()
        if txt:
            self.app.tareas_mgr.add_item(txt)
            self._add_entry.delete(0, tk.END)

    @staticmethod
    def _clear(frame):
        for w in frame.winfo_children():
            w.destroy()


# ═══════════════════════════════════════════════════════════════════════
# SCREEN: NIGHT MODE
# ═══════════════════════════════════════════════════════════════════════

class NightScreen(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg="black")
        self.app = app
        # Una pantalla completamente negra. Los toques se interceptan globalmente en DigitalFrame.


# ═══════════════════════════════════════════════════════════════════════
# MAIN APPLICATION (orchestrator)
# ═══════════════════════════════════════════════════════════════════════

class DigitalFrame(tk.Tk):
    def __init__(self):
        super().__init__()

        self.cfg      = load_config()
        self.cities   = self.cfg.get("cities", [])
        self.shopping = ShoppingListManager()
        self.tareas_mgr = TareasManager()
        self.weather  = WeatherCache(self.cities)
        self.msg_q    = queue.Queue()

        # ── window ────────────────────────────────────────────────────
        self.title("Marco Digital")
        self.geometry(f"{SCREEN_W}x{SCREEN_H}")
        self.configure(bg="black")
        try:
            self.attributes("-fullscreen", True)
        except Exception:
            pass
        self.bind("<Escape>", lambda e: self._quit())

        # handle inactivity for cursor and night mode
        self._cursor_job = None
        self._last_activity = time.time()
        self.bind_all("<Motion>", self._on_activity, add="+")
        self.bind_all("<Button-1>", self._on_activity, add="+")
        self.bind_all("<Key>", self._on_activity, add="+")

        # ── screens ──────────────────────────────────────────────────
        self.slideshow = SlideshowScreen(self, self)
        self.calendar  = CalendarScreen(self, self)
        self.event_scr = EventCreationScreen(self, self)
        self.shop_scr  = ShoppingListScreen(self, self)
        self.tareas_scr = TareasScreen(self, self)
        self.night_scr = NightScreen(self, self)

        self._screens = {
            "slide":    self.slideshow,
            "cal":      self.calendar,
            "event":    self.event_scr,
            "shop":     self.shop_scr,
            "tareas":   self.tareas_scr,
            "night":    self.night_scr,
        }
        self._current = None

        # start on slideshow
        self.show_slideshow()

        # ── background services ──────────────────────────────────────
        self.poller = EmailPoller(self.cfg, self.shopping, self.msg_q)
        self.poller.start()
        self._poll_queue()
        self._check_night_mode()

        # pre-fetch weather
        threading.Thread(target=self.weather.fetch_all, daemon=True).start()

    # ── screen switching ─────────────────────────────────────────────
    def _switch(self, name):
        if self._current == "slide":
            self.slideshow.stop()
        if self._current:
            self._screens[self._current].pack_forget()
        self._screens[name].pack(fill=tk.BOTH, expand=True)
        self._current = name

    def show_slideshow(self):
        self._switch("slide")
        self.slideshow.start()

    def show_calendar(self):
        self._switch("cal")
        self.calendar.refresh()

    def show_event_creation(self):
        self.event_scr.reset()
        self._switch("event")

    def show_shopping(self):
        self.shop_scr.scroll = 0
        self._switch("shop")
        self.shop_scr.refresh()

    def show_tareas(self):
        self.tareas_scr.scroll = 0
        self._switch("tareas")
        self.tareas_scr.refresh()

    def show_night(self):
        self._switch("night")

    # ── night mode ───────────────────────────────────────────────────
    def _check_night_mode(self):
        now = datetime.datetime.now()
        start = self.cfg.get("night_mode_start_h", 20)
        end = self.cfg.get("night_mode_end_h", 8)
        timeout = self.cfg.get("night_mode_timeout_sec", 60)
        
        if start > end:
            is_night = (now.hour >= start) or (now.hour < end)
        elif start < end:
            is_night = start <= now.hour < end
        else:
            is_night = False

        if is_night:
            if time.time() - self._last_activity > timeout:
                if self._current != "night":
                    self.show_night()
        else:
            if self._current == "night":
                self._last_activity = time.time()
                self.show_slideshow()
                
        self.after(5000, self._check_night_mode)

    # ── background queue ─────────────────────────────────────────────
    def _poll_queue(self):
        try:
            while True:
                kind, data = self.msg_q.get_nowait()
                if kind == "shopping" and self._current == "shop":
                    self.shop_scr.refresh()
                elif kind == "photo":
                    pass  # slideshow re-scans automatically
        except queue.Empty:
            pass
        self.after(1000, self._poll_queue)

    # ── interactivity & cursor auto-hide ─────────────────────────────
    def _on_activity(self, event=None):
        self._last_activity = time.time()
        
        self.configure(cursor="")
        if self._cursor_job:
            self.after_cancel(self._cursor_job)
        self._cursor_job = self.after(3000, lambda: self.configure(cursor="none"))
        
        if self._current == "night":
            self.show_slideshow()

    # ── cleanup ──────────────────────────────────────────────────────
    def _quit(self):
        self.poller.stop()
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    os.makedirs(FOTOS_DIR, exist_ok=True)
    app = DigitalFrame()
    app.mainloop()
