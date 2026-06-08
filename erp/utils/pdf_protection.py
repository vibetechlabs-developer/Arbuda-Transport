"""PDF file encryption (password required when opening in Acrobat/browser)."""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO

from django.conf import settings
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.platypus import SimpleDocTemplate

from erp.utils.security import (
    PDF_ZONE_OUTSIDE,
    get_client_ip,
    get_or_create_security_settings,
    get_pdf_access_zone,
    get_session_company,
)


def _fernet():
    from cryptography.fernet import Fernet

    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_pdf_secret(plain: str) -> str:
    if not plain:
        return ""
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_pdf_secret(token: str) -> str:
    if not token:
        return ""
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")


def get_pdf_embed_password_for_request(request) -> str:
    """Password baked into generated PDF files (fixed at download time)."""
    try:
        company = get_session_company(request)
    except Exception:
        return ""
    settings_obj = get_or_create_security_settings(company)
    if settings_obj.pdf_files_always_use_outside_password:
        zone = PDF_ZONE_OUTSIDE
    else:
        zone = get_pdf_access_zone(company, get_client_ip(request))
    return settings_obj.get_pdf_open_password(zone)


def get_pdf_open_password_for_request(request) -> str:
    """Alias for file embed password (kept for callers that predate the split)."""
    return get_pdf_embed_password_for_request(request)


def pdf_files_use_outside_password_always(request) -> bool:
    try:
        company = get_session_company(request)
    except Exception:
        return True
    settings_obj = get_or_create_security_settings(company)
    return bool(settings_obj.pdf_files_always_use_outside_password)


def get_reportlab_encryption_for_request(request) -> StandardEncryption | None:
    password = get_pdf_embed_password_for_request(request)
    if not password:
        return None
    return StandardEncryption(
        userPassword=password,
        ownerPassword=password,
        canPrint=1,
        canModify=0,
        canCopy=0,
        canAnnotate=0,
        strength=128,
    )


def create_pdf_document(buffer: BytesIO, request, **kwargs) -> SimpleDocTemplate:
    """SimpleDocTemplate with optional AES encryption from company PDF passwords."""
    encrypt = get_reportlab_encryption_for_request(request)
    if encrypt is not None:
        kwargs["encrypt"] = encrypt
    return SimpleDocTemplate(buffer, **kwargs)


def pdf_file_password_enabled_for_request(request) -> bool:
    return bool(get_pdf_embed_password_for_request(request))


def notify_pdf_password_hint(request) -> None:
    """One-time flash: PDF will ask for password when opened."""
    from django.contrib import messages

    if not pdf_file_password_enabled_for_request(request):
        return
    if request.session.get("pdf_open_password_hint_shown"):
        return
    if pdf_files_use_outside_password_always(request):
        messages.info(
            request,
            "This PDF uses the outside-office password (even if you downloaded it at the office). "
            "Anyone opening the file — including from WhatsApp at home — must enter that password. "
            "The inside password is only for unlocking PDFs in the ERP while on the office network.",
        )
    else:
        try:
            company = get_session_company(request)
            zone = get_pdf_access_zone(company, get_client_ip(request))
        except Exception:
            zone = PDF_ZONE_OUTSIDE
        label = "inside (office network)" if zone == "inside" else "outside (away from office)"
        messages.info(
            request,
            f"This PDF is password-protected with the {label} password. "
            "If you share the file and open it elsewhere, you may need a different password — "
            "enable “Always use outside password in PDF files” in Security Settings to avoid that.",
        )
    request.session["pdf_open_password_hint_shown"] = True
    request.session.modified = True
