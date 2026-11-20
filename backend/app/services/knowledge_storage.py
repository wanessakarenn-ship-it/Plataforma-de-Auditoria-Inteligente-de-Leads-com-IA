import hashlib
import io
import re
import zipfile
from pathlib import PurePath

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from lxml.etree import XMLSyntaxError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from backend.app.config import get_settings


def _safe_filename(filename: str) -> str:
    name = re.split(r"[\\/]", filename.strip())[-1]
    if not name or len(name) > 255 or PurePath(name).name != name:
        raise ValueError("Nome de arquivo inválido.")
    return name


def _extract_pdf(data: bytes, max_chars: int) -> str:
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ValueError("PDF protegido por senha não pode ser indexado.")
        if len(reader.pages) > 200:
            raise ValueError("PDF acima do limite de 200 páginas.")
        pages = []
        total_chars = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            total_chars += len(text)
            if total_chars > max_chars:
                raise ValueError("Texto extraído excede o limite configurado.")
            pages.append(text)
        return "\n".join(pages).strip()
    except (PdfReadError, OSError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith(
            ("PDF protegido", "PDF acima", "Texto extraído")
        ):
            raise
        raise ValueError("PDF inválido ou não legível.") from exc


def _extract_docx(data: bytes, max_chars: int, max_bytes: int) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if (
                len(members) > 200
                or sum(item.file_size for item in members) > max_bytes * 10
                or "word/document.xml" not in archive.namelist()
            ):
                raise ValueError("DOCX inválido ou acima dos limites de conteúdo.")
            if archive.getinfo("word/document.xml").file_size > max_chars * 10:
                raise ValueError("DOCX excede o limite de texto extraível.")
        document = Document(io.BytesIO(data))
        parts = [paragraph.text for paragraph in document.paragraphs]
        parts.extend(
            cell.text
            for table in document.tables
            for row in table.rows
            for cell in row.cells
        )
        text = "\n".join(part for part in parts if part.strip()).strip()
    except (PackageNotFoundError, zipfile.BadZipFile, XMLSyntaxError, OSError) as exc:
        raise ValueError("DOCX inválido ou não legível.") from exc
    if len(text) > max_chars:
        raise ValueError("Texto extraído excede o limite configurado.")
    return text


def extract_document_text(filename: str, data: bytes) -> tuple[str, str, str, str]:
    settings = get_settings()
    safe_name = _safe_filename(filename)
    max_bytes = settings.knowledge_max_file_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise ValueError("Arquivo acima do limite configurado.")
    if not data:
        raise ValueError("Arquivo vazio.")

    extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    max_chars = settings.knowledge_max_extracted_chars
    if extension == "txt":
        if b"\x00" in data:
            raise ValueError("Arquivo TXT contém bytes inválidos.")
        try:
            text = data.decode("utf-8-sig").strip()
        except UnicodeDecodeError as exc:
            raise ValueError("TXT precisa estar codificado em UTF-8.") from exc
    elif extension == "pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("Assinatura do arquivo PDF inválida.")
        text = _extract_pdf(data, max_chars)
    elif extension == "docx":
        text = _extract_docx(data, max_chars, max_bytes)
    else:
        raise ValueError("Formato não permitido. Use PDF, DOCX ou TXT.")

    if not text:
        raise ValueError("O arquivo não contém texto extraível; OCR não está habilitado.")
    if len(text) > max_chars:
        raise ValueError("Texto extraído excede o limite configurado.")
    return text, extension, safe_name, hashlib.sha256(data).hexdigest()
