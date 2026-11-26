import csv
import io
import re
import unicodedata
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from itertools import chain, islice
from typing import Any

from openpyxl import load_workbook

from backend.app.classification import classify


FIELD_ALIASES = {
    "external_id": {"id", "lead id", "record id", "salesforce id", "contact id"},
    "first_name": {"first name", "firstname"},
    "last_name": {"last name", "lastname", "sobrenome"},
    "full_name": {"name", "full name", "lead name", "contact name"},
    "company": {"company", "account name", "empresa"},
    "crm_created_at": {"created date", "createddate", "data de criacao", "data criacao"},
    "campaign": {"campaign", "campaign name", "campanha", "campanha bc"},
    "monthly_account_value": {
        "monthly account value",
        "valor mensal da conta",
        "valor mensal",
    },
    "email": {"email", "email address", "e mail"},
    "phone": {"phone", "mobile", "mobile phone", "telephone", "telefone", "celular"},
    "status": {"status", "lead status", "leadstatus", "lead status name", "status do lead"},
    "phase": {"phase", "stage", "stage name", "lead phase", "funnel stage", "fase"},
    "source": {"lead source", "source", "leadsource", "origem do lead"},
    "loss_reason": {"loss reason", "closed lost reason", "motivo de perda", "motivo da perda"},
    "disqualification_reason": {
        "reason description",
        "descricao do motivo",
        "disqualification reason",
        "disqualified reason",
        "motivo de desqualificacao",
    },
    "loss_reason_description": {"descricao motivo", "loss reason description"},
}

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_XLSX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_XLSX_ARCHIVE_ENTRIES = 10_000
MAX_IMPORT_COLUMNS = 256


class ImportLimitExceeded(ValueError):
    pass


@dataclass
class ParsedSheet:
    mapping: dict[str, str]
    rows: list[dict[str, Any]]


def _normalize_header(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _mapping_for(headers: list[Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for header in headers:
        normalized = _normalize_header(header)
        for field, aliases in FIELD_ALIASES.items():
            if normalized in {_normalize_header(alias) for alias in aliases} and field not in mapping:
                mapping[field] = str(header).strip()
                break
    return mapping


def _score(mapping: dict[str, str]) -> int:
    return len(mapping)


def _cell_string(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    return "" if value is None else str(value).strip()


def _parse_rows(rows: Iterable[Iterable[Any]], max_rows: int) -> ParsedSheet:
    if max_rows < 1:
        raise ValueError("O limite de linhas deve ser maior que zero.")

    sample = [list(row) for row in islice(rows, 30)]
    best_index = -1
    best_mapping: dict[str, str] = {}
    for index, row in enumerate(sample):
        candidate = _mapping_for(row)
        if _score(candidate) > _score(best_mapping):
            best_index, best_mapping = index, candidate
    if best_index < 0 or _score(best_mapping) < 2:
        raise ValueError(
            "Não foi possível identificar o cabeçalho Salesforce nas primeiras 30 linhas."
        )

    headers = [
        str(value).strip() if value is not None else "" for value in sample[best_index]
    ]
    parsed_rows = []
    data_rows = chain(sample[best_index + 1 :], rows)
    for row in data_rows:
        row = list(row)
        if not any(value is not None and str(value).strip() for value in row):
            continue
        if len(parsed_rows) >= max_rows:
            raise ImportLimitExceeded("Planilha acima do limite de linhas configurado.")
        parsed_rows.append(
            {
                header: (_cell_string(row[index]) if index < len(row) else "")
                for index, header in enumerate(headers)
                if header
            }
        )
    return ParsedSheet(mapping=best_mapping, rows=parsed_rows)


def _csv_delimiter(text: str) -> str:
    def candidate_score(delimiter: str) -> int:
        rows = csv.reader(io.StringIO(text), delimiter=delimiter)
        return max(
            (_score(_mapping_for(row)) for row in islice(rows, 30)),
            default=0,
        )

    return max((",", ";", "\t", "|"), key=candidate_score)


def _validate_xlsx_archive(content: bytes, max_uncompressed_bytes: int) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("Arquivo XLSX inválido.") from exc

    if len(entries) > MAX_XLSX_ARCHIVE_ENTRIES:
        raise ImportLimitExceeded("Arquivo XLSX contém arquivos internos em excesso.")
    if sum(entry.file_size for entry in entries) > max_uncompressed_bytes:
        raise ImportLimitExceeded("Arquivo XLSX excede o limite de expansão configurado.")


def parse_file(
    filename: str,
    content: bytes,
    *,
    max_rows: int = 10_000,
    max_uncompressed_bytes: int = MAX_XLSX_UNCOMPRESSED_BYTES,
) -> ParsedSheet:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "csv":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("cp1252")
        try:
            delimiter = _csv_delimiter(text)
            return _parse_rows(
                csv.reader(io.StringIO(text), delimiter=delimiter),
                max_rows,
            )
        except csv.Error as exc:
            raise ValueError("Arquivo CSV inválido.") from exc
    elif suffix in {"xlsx", "xlsm"}:
        _validate_xlsx_archive(content, max_uncompressed_bytes)
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            sheet = workbook.active
            if sheet.max_column is not None and sheet.max_column > MAX_IMPORT_COLUMNS:
                raise ImportLimitExceeded("Arquivo XLSX excede o limite de colunas configurado.")
            if sheet.max_row is not None and sheet.max_row > max_rows + 30:
                raise ImportLimitExceeded("Arquivo XLSX excede o limite de linhas configurado.")
            return _parse_rows(sheet.iter_rows(values_only=True), max_rows)
        finally:
            workbook.close()
    else:
        raise ValueError("Formato não suportado. Envie um arquivo CSV ou XLSX.")


def _mapped_value(row: dict[str, Any], mapping: dict[str, str], field: str) -> str | None:
    header = mapping.get(field)
    value = row.get(header) if header else None
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def _normalize_email(value: str | None) -> str | None:
    return value.strip().casefold() if value else None


def _normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return digits or None


def _parse_salesforce_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso_text)
        return parsed
    except ValueError:
        pass
    for pattern in (
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    raise ValueError


def _parse_money(value: str) -> Decimal:
    text = re.sub(r"[^\d,.\-]", "", value)
    if not text or text in {"-", ".", ","}:
        raise InvalidOperation
    if "," in text and "." in text:
        decimal_separator = "," if text.rfind(",") > text.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        text = text.replace(thousands_separator, "")
        text = text.replace(decimal_separator, ".")
    elif "," in text:
        tail = text.rsplit(",", 1)[-1]
        text = text.replace(",", "") if len(tail) == 3 else text.replace(".", "").replace(",", ".")
    elif "." in text and len(text.rsplit(".", 1)[-1]) == 3:
        text = text.replace(".", "")
    elif text.count(".") > 1:
        head, tail = text.rsplit(".", 1)
        text = head.replace(".", "") + "." + tail
    return Decimal(text).quantize(Decimal("0.01"))


def validate_rows(rows: list[dict[str, Any]], mapping: dict[str, str]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    results = []
    for row_number, raw in enumerate(rows, start=1):
        first_name = _mapped_value(raw, mapping, "first_name")
        last_name = _mapped_value(raw, mapping, "last_name")
        full_name = _mapped_value(raw, mapping, "full_name")
        if full_name and not (first_name or last_name):
            pieces = full_name.split(maxsplit=1)
            first_name = pieces[0]
            last_name = pieces[1] if len(pieces) > 1 else None

        email = _mapped_value(raw, mapping, "email")
        phone = _mapped_value(raw, mapping, "phone")
        external_id = _mapped_value(raw, mapping, "external_id")
        status = _mapped_value(raw, mapping, "status")
        phase = _mapped_value(raw, mapping, "phase")
        created_at_raw = _mapped_value(raw, mapping, "crm_created_at")
        monthly_value_raw = _mapped_value(raw, mapping, "monthly_account_value")
        errors: list[str] = []
        warnings: list[str] = []
        if email and not EMAIL_PATTERN.match(email):
            errors.append("E-mail inválido.")
        phone_normalized = _normalize_phone(phone)
        if phone and (not phone_normalized or not 7 <= len(phone_normalized) <= 15):
            errors.append("Telefone deve conter de 7 a 15 dígitos.")
        if not email and not phone:
            warnings.append("Registro sem e-mail e telefone.")
        created_at = None
        if created_at_raw:
            try:
                created_at = _parse_salesforce_datetime(created_at_raw)
            except ValueError:
                errors.append("Data de criação inválida.")
        monthly_value = None
        if monthly_value_raw:
            try:
                monthly_value = _parse_money(monthly_value_raw)
            except (InvalidOperation, ValueError):
                errors.append("Valor mensal da conta inválido.")
        classification = classify(status, phase)
        if classification == "unknown" and (status or phase):
            warnings.append("Status/fase não reconhecido; classificação pendente de revisão.")
        dedupe_keys = [
            f"id:{external_id.casefold()}" if external_id else None,
            f"email:{_normalize_email(email)}" if email else None,
            f"phone:{phone_normalized}" if phone_normalized else None,
        ]
        dedupe_keys = [key for key in dedupe_keys if key]
        duplicate = any(key in seen for key in dedupe_keys)
        seen.update(dedupe_keys)
        values = {
            "external_id": external_id,
            "first_name": first_name,
            "last_name": last_name,
            "company": _mapped_value(raw, mapping, "company"),
            "crm_created_at": created_at.isoformat() if created_at else None,
            "campaign": _mapped_value(raw, mapping, "campaign"),
            "monthly_account_value": str(monthly_value) if monthly_value is not None else None,
            "email": email,
            "email_normalized": _normalize_email(email),
            "phone": phone,
            "phone_normalized": phone_normalized,
            "source": _mapped_value(raw, mapping, "source"),
            "status": status,
            "phase": phase,
            "classification": classification,
            "loss_reason": _mapped_value(raw, mapping, "loss_reason"),
            "disqualification_reason": _mapped_value(raw, mapping, "disqualification_reason"),
            "loss_reason_description": _mapped_value(raw, mapping, "loss_reason_description"),
            "raw_fields": {
                field: _mapped_value(raw, mapping, field)
                for field in mapping
                if field != "full_name" and _mapped_value(raw, mapping, field) is not None
            },
        }
        results.append(
            {
                "row_number": row_number,
                "values": values,
                "errors": errors,
                "warnings": warnings,
                "duplicate_in_file": duplicate,
            }
        )
    return results
