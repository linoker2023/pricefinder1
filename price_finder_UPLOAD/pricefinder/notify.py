"""Уведомления: системные уведомления Android (Termux), Telegram (Bot API) и e-mail (SMTP)."""

from __future__ import annotations

import shutil
import smtplib
import ssl
import subprocess
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


@dataclass
class Notifier:
    telegram_token: str = ""
    telegram_chat: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    smtp_ssl: bool = False
    enabled: bool = True
    termux: bool | None = None          # None = определить автоматически (Android/Termux)

    @classmethod
    def from_settings(cls, settings: dict) -> "Notifier":
        tg = settings.get("telegram") or {}
        smtp = settings.get("smtp") or {}
        termux = settings.get("termux_notification")
        return cls(
            telegram_token=str(tg.get("bot_token") or ""),
            telegram_chat=str(tg.get("chat_id") or ""),
            smtp_host=str(smtp.get("host") or ""),
            smtp_port=int(smtp.get("port") or 587),
            smtp_user=str(smtp.get("user") or ""),
            smtp_password=str(smtp.get("password") or ""),
            smtp_from=str(smtp.get("sender") or smtp.get("user") or ""),
            smtp_to=str(smtp.get("to") or ""),
            smtp_ssl=bool(smtp.get("ssl", False)),
            enabled=bool(settings.get("notify_enabled", True)),
            termux=None if termux is None else bool(termux),
        )

    # --- системные уведомления Android (Termux:API) -------------------------
    def termux_available(self) -> bool:
        if self.termux is not None:
            return self.termux and shutil.which("termux-notification") is not None
        return shutil.which("termux-notification") is not None

    def termux_notify(self, title: str, text: str, notification_id: str = "pricefinder") -> bool:
        """Показывает уведомление в шторке Android через Termux:API."""
        if not self.termux_available():
            return False
        cmd = [
            "termux-notification",
            "--title", title[:120],
            "--content", text[:900],
            "--id", notification_id,
            "--priority", "high",
        ]
        # вибрация и звук, если поддерживаются установленной версией Termux:API
        try:
            subprocess.run(cmd, check=False, timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False

    # --- Telegram ----------------------------------------------------------
    def telegram(self, text: str) -> bool:
        if not (self.telegram_token and self.telegram_chat):
            return False
        import requests

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(url, json=payload, timeout=15)
            return resp.status_code == 200
        except Exception:
            return False

    # --- E-mail ------------------------------------------------------------
    def email(self, subject: str, body_html: str, body_text: str = "") -> bool:
        if not (self.smtp_host and self.smtp_to):
            return False
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.smtp_from or self.smtp_user
        msg["To"] = self.smtp_to
        if body_text:
            msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        try:
            if self.smtp_ssl or self.smtp_port == 465:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context, timeout=25) as server:
                    if self.smtp_user:
                        server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=25) as server:
                    server.ehlo()
                    try:
                        server.starttls(context=ssl.create_default_context())
                        server.ehlo()
                    except smtplib.SMTPNotSupportedError:
                        pass
                    if self.smtp_user:
                        server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
            return True
        except Exception:
            return False

    def send(self, subject: str, html: str, text: str = "") -> dict[str, bool]:
        """Шлёт во все настроенные каналы. Возвращает статус по каждому.

        На Android дополнительно показывается системное уведомление в шторке
        (нужно приложение Termux:API); Telegram и e-mail работают везде.
        """
        result: dict[str, bool] = {}
        if not self.enabled:
            return {"disabled": True}
        plain = text or _html_to_text(html)
        if self.termux_available():
            result["android"] = self.termux_notify(subject, plain)
        if self.telegram_token:
            result["telegram"] = self.telegram(plain)
        if self.smtp_host:
            result["email"] = self.email(subject, html, text)
        return result

    def test(self) -> dict[str, bool]:
        """Проверка всех каналов (команда `python price_finder.py notify-test`)."""
        return self.send(
            "pricefinder: проверка уведомлений",
            "<b>Тест</b><br>Если вы видите это сообщение — канал работает.",
            "pricefinder: тестовое уведомление. Если видите — канал работает.",
        )


def _html_to_text(html: str) -> str:
    import re

    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</(p|div|li|tr|h\d)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
