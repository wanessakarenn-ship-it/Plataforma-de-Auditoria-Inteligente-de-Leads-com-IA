from io import BytesIO

from openpyxl import Workbook

import pytest

from backend.app.importer import ImportLimitExceeded, parse_file, validate_rows


def test_csv_header_detection_mapping_validation_and_deduplication():
    content = (
        "Salesforce report generated on 2026-01-01\n"
        "Id,First Name,Last Name,Email,Phone,Status,Stage,Company\n"
        "00Q1,Ana,Silva,ana@example.com,+1 415 555 0100,Qualified,Research,Acme\n"
        "00Q2,Bia,Lima,invalid-email,123,Lead,Connection,Example\n"
        "00Q3,Caio,Reis,ana@example.com,+1 415 555 0100,Qualified,Research,Acme\n"
    ).encode()
    parsed = parse_file("salesforce.csv", content)
    assert parsed.mapping["external_id"] == "Id"
    assert parsed.mapping["email"] == "Email"

    rows = validate_rows(parsed.rows, parsed.mapping)
    assert rows[0]["values"]["classification"] == "research"
    assert not rows[0]["errors"]
    assert rows[1]["errors"]
    assert rows[2]["duplicate_in_file"]


def test_excel_header_detection_and_full_name_split():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Salesforce Export"])
    sheet.append(["Id", "Name", "Email", "Lead Status"])
    sheet.append(["00Q4", "Dora Monteiro", "dora@example.com", "Levantada de Mão"])
    output = BytesIO()
    workbook.save(output)
    parsed = parse_file("salesforce.xlsx", output.getvalue())
    row = validate_rows(parsed.rows, parsed.mapping)[0]
    assert row["values"]["first_name"] == "Dora"
    assert row["values"]["last_name"] == "Monteiro"
    assert row["values"]["classification"] == "hand_raised"


def test_salesforce_november_export_maps_localized_columns_and_types():
    content = (
        "Salesforce report export; November 2026\n"
        "Lead Intelligence AI; informational row\n"
        "Data de criação;Fase;Status do lead;Campanha BC;Origem do Lead;"
        "Sobrenome;Email;Celular;Valor Mensal da Conta;Descrição do Motivo;"
        "Motivo da perda;Descrição Motivo\n"
        "2026-11-18T09:30:00;Perdido;Qualificado;BC - Sintético;Formulário;"
        "Synthetic-Lead;lead-001@example.invalid;+1 202 555 0101;R$ 1.234,56;"
        "Justificativa sintética;Orçamento;Detalhe sintético\n"
    ).encode()
    parsed = parse_file("salesforce-november-2026.csv", content)
    assert parsed.mapping["crm_created_at"] == "Data de criação"
    assert parsed.mapping["monthly_account_value"] == "Valor Mensal da Conta"
    assert parsed.mapping["phone"] == "Celular"
    assert parsed.mapping["disqualification_reason"] == "Descrição do Motivo"
    assert parsed.mapping["loss_reason_description"] == "Descrição Motivo"

    row = validate_rows(parsed.rows, parsed.mapping)[0]
    assert row["values"]["last_name"] == "Synthetic-Lead"
    assert row["values"]["crm_created_at"] == "2026-11-18T09:30:00"
    assert row["values"]["monthly_account_value"] == "1234.56"
    assert row["values"]["campaign"] == "BC - Sintético"
    assert row["values"]["source"] == "Formulário"
    assert row["values"]["classification"] == "qualified_lost"
    assert row["values"]["loss_reason"] == "Orçamento"
    assert row["values"]["disqualification_reason"] == "Justificativa sintética"
    assert row["values"]["loss_reason_description"] == "Detalhe sintético"
    assert not row["errors"]


def test_csv_row_limit_is_enforced_while_iterating():
    content = b"Id,Email\n1,a@example.test\n2,b@example.test\n"
    with pytest.raises(ImportLimitExceeded, match="limite de linhas"):
        parse_file("bounded.csv", content, max_rows=1)


def test_xlsx_expansion_limit_is_checked_before_workbook_parsing():
    workbook = Workbook()
    workbook.active.append(["Id", "Email"])
    output = BytesIO()
    workbook.save(output)

    with pytest.raises(ImportLimitExceeded, match="limite de expansão"):
        parse_file(
            "bounded.xlsx",
            output.getvalue(),
            max_uncompressed_bytes=1,
        )


def test_xlsx_rejects_excessive_declared_dimensions_before_iterating():
    workbook = Workbook()
    workbook.active["ZZ1000000"] = "synthetic"
    output = BytesIO()
    workbook.save(output)

    with pytest.raises(ImportLimitExceeded, match="limite de (linhas|colunas)"):
        parse_file("oversized-dimensions.xlsx", output.getvalue(), max_rows=10)
