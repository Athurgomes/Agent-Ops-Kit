"""Envio de e-mail por SMTP (stdlib), opcional e configurável por ambiente. `send_mail` é a única função
que fala com a rede: os testes a trocam por um coletor.

AOK_SMTP_HOST, AOK_SMTP_PORT (587), AOK_SMTP_USER / AOK_SMTP_PASSWORD (opcionais), AOK_SMTP_STARTTLS
(padrão true), AOK_SMTP_FROM (padrão no-reply@<host>) e AOK_PUBLIC_URL (base dos links; nunca vem de
cabeçalho da requisição).
"""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage


class MailError(Exception):
    pass


@dataclass(frozen=True)
class MailConfig:
    host: str
    port: int
    user: str | None
    password: str | None
    starttls: bool
    sender: str


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def mail_config() -> MailConfig | None:
    """None se AOK_SMTP_HOST não estiver definida (e-mail desligado)."""
    host = _env("AOK_SMTP_HOST")
    if not host:
        return None
    try:
        port = int(_env("AOK_SMTP_PORT") or 587)
    except ValueError:
        return None
    return MailConfig(
        host=host,
        port=port,
        user=_env("AOK_SMTP_USER") or None,
        password=os.environ.get("AOK_SMTP_PASSWORD") or None,
        starttls=_env("AOK_SMTP_STARTTLS").lower() not in {"0", "false", "no", "off"},
        sender=_env("AOK_SMTP_FROM") or f"no-reply@{host}",
    )


def public_url() -> str | None:
    """Base dos links enviados por e-mail. Vem SÓ da configuração (evita host header poisoning)."""
    url = _env("AOK_PUBLIC_URL").rstrip("/")
    return url if url.startswith(("http://", "https://")) else None


def recovery_enabled() -> bool:
    return mail_config() is not None and public_url() is not None


def send_mail(to: str, subject: str, text: str, html: str | None = None) -> None:
    """Envia um e-mail (text/plain, com alternativa HTML simples). Levanta MailError/OSError se falhar."""
    cfg = mail_config()
    if cfg is None:
        raise MailError("smtp not configured")
    msg = EmailMessage()
    msg["From"] = cfg.sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(cfg.host, cfg.port, timeout=10) as smtp:
        if cfg.starttls:
            smtp.starttls(context=ssl.create_default_context())
        if cfg.user:
            smtp.login(cfg.user, cfg.password or "")
        smtp.send_message(msg)
