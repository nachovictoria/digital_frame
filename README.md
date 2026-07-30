<!-- 
  ⚠️ NOTICE:
  This code has been reviewed, restructured, and refactored with the assistance of Claude (Anthropic).
  This documentation was generated with AI assistance.
-->

# 🖼️ Marco Digital — Raspberry Pi Digital Photo Frame

A fullscreen **Tkinter** application for a touchscreen Raspberry Pi that combines a photo slideshow, a shared calendar with live weather, a collaborative shopping list, and event creation — all in a single Python script.

---

## ✨ Features

| Feature | Description |
|---|---|
| **📸 Photo Slideshow** | Cycles through images in the `fotos/` folder. Tap anywhere to switch to the calendar. New photos can be added remotely via email. |
| **📅 Calendar Week View** | Displays events from a shared iCal calendar (Google, Outlook, etc.) with week-by-week navigation and a "Today" button. |
| **🌤️ 3-City Weather** | Shows a 14-day forecast for three configurable cities using the free [Open-Meteo API](https://open-meteo.com) (no API key required). |
| **🛒 Shopping List** | Persistent JSON-backed list with checkboxes. Add items manually via a Spanish on-screen keyboard, or remotely by sending an email with subject **"compra"**. Send the list to selected family members. |
| **➕ Event Creation** | Create events with a touch-friendly date/time picker and send `.ics` calendar invites to the entire distribution list. |
| **📧 Background Email Poller** | A daemon thread checks Gmail every 30 seconds for new shopping items (subject: `compra`) and new photos (subject: `foto`). |
| **⌨️ Spanish Keyboard** | Built-in on-screen QWERTY keyboard with `Ñ`, accented vowels (`á é í ó ú`), `¿`, `¡`, and symbol layers. |

---

## 📐 Architecture

```
carrusel_marco.py      ← Single-file application (~1400 lines)
config.json            ← All credentials, URLs, locations (not tracked by git)
lista_compra.json      ← Shopping list data (auto-created)
fotos/                 ← Photo folder (auto-created, add your images here)
```

### Screen Flow

```
┌──────────────┐   tap    ┌──────────────┐
│  Slideshow   │ ───────► │   Calendar   │
│  (idle)      │ ◄─────── │  Week View   │
└──────────────┘  "Fotos" └──────┬───────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
             ┌───────────┐ ┌──────────┐ ┌──────────┐
             │  Event    │ │ Shopping │ │  Back to │
             │ Creation  │ │   List   │ │ Slideshow│
             └───────────┘ └──────────┘ └──────────┘
```

---

## 🚀 Setup

### 1. Prerequisites

- **Raspberry Pi** with a touchscreen (tested on the official 7" display, 800×480)
- **Python 3.9+** with `tkinter` (included in Raspberry Pi OS)
- A **Gmail account** with an [App Password](https://myaccount.google.com/apppasswords) (requires 2-Step Verification)
- A **shared iCal URL** from Google Calendar, Outlook, or similar

### 2. Install Dependencies

```bash
sudo apt update && sudo apt install python3-tk
pip3 install Pillow icalendar recurring-ical-events requests
```

### 3. Clone and Configure

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
```

Create a `config.json` file in the project root (a template is auto-generated on first run):

```json
{
  "ical_url": "https://your-calendar-provider/calendar.ics",
  "gmail_user": "your-email@gmail.com",
  "gmail_app_password": "xxxx xxxx xxxx xxxx",
  "smtp_server": "smtp.gmail.com",
  "smtp_port": 465,
  "imap_server": "imap.gmail.com",
  "slideshow_interval_sec": 10,
  "email_poll_interval_sec": 30,
  "cities": [
    { "name": "City One",   "code": "C1", "lat": 40.4739, "lon": -3.9450 },
    { "name": "City Two",   "code": "C2", "lat": 52.0406, "lon": -0.7594 },
    { "name": "City Three", "code": "C3", "lat": 57.7089, "lon": 11.9746 }
  ],
  "distribution_list": [
    { "name": "Alice", "email": "alice@example.com" },
    { "name": "Bob",   "email": "bob@example.com" }
  ]
}
```

> **⚠️ Security:** `config.json` contains credentials and is excluded from git via `.gitignore`. Never commit it to the repository.

### 4. Add Photos

Place image files (`.jpg`, `.png`, `.gif`, `.bmp`, `.webp`) into the `fotos/` folder:

```bash
mkdir -p fotos
cp ~/my-photos/*.jpg fotos/
```

### 5. Run

```bash
python3 carrusel_marco.py
```

The app launches in fullscreen. Press **Esc** to exit.

---

## ⚙️ Configuration Reference

| Key | Type | Description |
|---|---|---|
| `ical_url` | `string` | Shared calendar URL in iCal (.ics) format |
| `gmail_user` | `string` | Gmail address for IMAP polling and SMTP sending |
| `gmail_app_password` | `string` | 16-character Gmail App Password |
| `smtp_server` | `string` | SMTP server address (e.g. `smtp.gmail.com`) |
| `smtp_port` | `int` | SMTP SSL port (default: `465`) |
| `imap_server` | `string` | IMAP server address (e.g. `imap.gmail.com`) |
| `slideshow_interval_sec` | `int` | Seconds between photo transitions (default: `10`) |
| `email_poll_interval_sec` | `int` | Seconds between email checks (default: `30`) |
| `cities` | `array` | List of cities with `name`, `code`, `lat`, `lon` for weather |
| `distribution_list` | `array` | List of people with `name` and `email` for invites/shopping |

---

## 📧 Email Integration

The app monitors a Gmail inbox for two types of emails:

### Shopping List — Subject: `compra`

Send an email with subject **"compra"** to the configured Gmail address. Each line in the body becomes a separate shopping list item.

**Example email:**
```
Subject: compra

Leche
Pan integral
Huevos
Aceite de oliva
```

### Photos — Subject: `foto`

Send an email with subject **"foto"** with image attachments. The images are saved to the `fotos/` folder and will appear in the slideshow automatically.

---

## 🖥️ Auto-Start on Boot (Optional)

To have the frame start automatically when the Pi boots:

### Option A: Autostart Desktop Entry

```bash
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/marco.desktop << EOF
[Desktop Entry]
Type=Application
Name=Marco Digital
Exec=python3 /home/pi/marco-digital/carrusel_marco.py
EOF
```

### Option B: systemd Service

```bash
sudo tee /etc/systemd/system/marco-digital.service << EOF
[Unit]
Description=Marco Digital Photo Frame
After=graphical.target

[Service]
User=pi
Environment=DISPLAY=:0
WorkingDirectory=/home/pi/marco-digital
ExecStart=/usr/bin/python3 carrusel_marco.py
Restart=on-failure

[Install]
WantedBy=graphical.target
EOF

sudo systemctl enable marco-digital
sudo systemctl start marco-digital
```

---

## 🛠️ Raspberry Pi Tips

- **Disable screen blanking:** Go to `Preferences > Raspberry Pi Configuration > Display > Screen Blanking: Disabled`
- **Hide mouse cursor:** Install `unclutter` → `sudo apt install unclutter` (the app also auto-hides the cursor after 3 seconds)
- **Display rotation:** If your screen is upside down, add `display_rotate=2` to `/boot/config.txt`

---

## 📦 Dependencies

| Package | Purpose |
|---|---|
| [Pillow](https://python-pillow.org/) | Image loading, resizing, EXIF orientation |
| [icalendar](https://icalendar.readthedocs.io/) | iCal (.ics) parsing and creation |
| [recurring-ical-events](https://github.com/niccokunzmann/recurring-ical-events) | Expanding recurring calendar events |
| [requests](https://requests.readthedocs.io/) | HTTP requests for weather API |
| `tkinter` | GUI framework (built-in with Python on Raspberry Pi OS) |

---

## 📄 License

MIT License. See [LICENSE](LICENSE)
