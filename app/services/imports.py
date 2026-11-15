"""Импорт CSV/XLSX: предпросмотр на сервере, сопоставление колонок, дубли и идемпотентный коммит."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from datetime import timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import ImportKind
from app.models import City, Company, Country, ImportPreview, Journal, Niche, User
from app.services.common import (
    ensure_user,
    is_supervisor,
    normalize_domain,
    normalize_name,
    touch,
)
from app.timeutils import utcnow

FIELD_ALIASES: dict[str, list[str]] = {
    "name": ["name", "название", "наименование", "компания", "company"],
    "country": ["country", "страна"],
    "city": ["city", "город"],
    "website_url": ["website_url", "сайт", "website", "url", "домен", "domain", "сайт компании"],
    "niche": ["niche", "ниша"],
    "observed_need": ["observed_need", "потребность", "заметки", "notes", "комментарий"],
}
REQUIRED_FIELDS = ("name", "country")
STATUS_OK, STATUS_DUP, STATUS_ERROR = "ok", "dup", "error"


def _clean_header(value) -> str:
    return str(value).strip().lower().replace("ё", "е")


def _decode(file_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=422, detail={"file": "Не удалось прочитать файл: неизвестная кодировка"})


def _parse_csv(file_bytes: bytes) -> tuple[list[str], list[dict]]:
    text = _decode(file_bytes)
    sample = text[:4096]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise HTTPException(status_code=422, detail={"file": "Пустой файл или нет строки заголовков"})
    headers = [h.strip() for h in reader.fieldnames if h is not None]
    rows = []
    for raw in reader:
        rows.append({_clean_header(k): (v or "").strip() for k, v in raw.items() if k is not None})
    return headers, rows


def _parse_xlsx(file_bytes: bytes) -> tuple[list[str], list[dict]]:
    import pandas as pd

    try:
        frame = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    except Exception as exc:  # noqa: BLE001 - сообщение уходит пользователю
        raise HTTPException(status_code=422, detail={"file": f"Не удалось прочитать XLSX: {exc}"})
    headers = [str(c).strip() for c in frame.columns]
    rows: list[dict] = []
    for _, row in frame.iterrows():
        item = {}
        for column in frame.columns:
            value = row[column]
            item[_clean_header(column)] = "" if value is None or pd.isna(value) else str(value).strip()
        rows.append(item)
    return headers, rows


def _suggest_mapping(headers: list[str]) -> dict[str, str]:
    cleaned = {_clean_header(h): h for h in headers}
    mapping: dict[str, str] = {}
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in cleaned:
                mapping[field] = cleaned[alias]
                break
    return mapping


def _normalize_mapping(raw: Optional[dict]) -> dict[str, str]:
    if not raw:
        return {}
    mapping: dict[str, str] = {}
    for field, header in raw.items():
        if field in FIELD_ALIASES and header:
            mapping[field] = str(header)
    return mapping


def _get(row: dict, mapping: dict, field: str) -> str:
    header = mapping.get(field)
    if not header:
        return ""
    return str(row.get(_clean_header(header), "") or "").strip()


def _build_lookup(db: Session):
    countries = {normalize_name(c.name): c for c in db.scalars(select(Country)).all()}
    cities = list(db.scalars(select(City)).all())
    niches = {normalize_name(n.name): n for n in db.scalars(select(Niche)).all()}
    companies = list(db.scalars(select(Company)).all())
    by_domain: dict[str, Company] = {}
    by_name_country_city: dict[tuple[str, int, Optional[int]], Company] = {}
    by_name_country: dict[tuple[str, int], Company] = {}
    for company in companies:
        if company.normalized_domain and company.normalized_domain not in by_domain:
            by_domain[company.normalized_domain] = company
        by_name_country_city.setdefault((normalize_name(company.name), company.country_id, company.city_id), company)
        by_name_country.setdefault((normalize_name(company.name), company.country_id), company)
    return countries, cities, niches, by_domain, by_name_country_city, by_name_country


def preview_import(
    db: Session,
    file_bytes: bytes,
    filename: Optional[str],
    actor: User,
    mapping: Optional[dict] = None,
    owner_id: Optional[int] = None,
    source_kind: Optional[str] = None,
) -> ImportPreview:
    if not file_bytes:
        raise HTTPException(status_code=422, detail={"file": "Файл пуст"})
    kind = (source_kind or ("xlsx" if (filename or "").lower().endswith((".xlsx", ".xls")) else "csv")).lower()
    headers, raw_rows = _parse_xlsx(file_bytes) if kind == "xlsx" else _parse_csv(file_bytes)
    if len(raw_rows) > settings.MAX_IMPORT_ROWS:
        raise HTTPException(
            status_code=422,
            detail={"file": f"Слишком много строк: {len(raw_rows)} (максимум {settings.MAX_IMPORT_ROWS})"},
        )
    if not raw_rows:
        raise HTTPException(status_code=422, detail={"file": "В файле нет строк с данными"})

    suggested = _suggest_mapping(headers)
    user_mapping = _normalize_mapping(mapping)
    # Пользовательское сопоставление важнее автоматического, но неполное — дополняем.
    effective = {**suggested, **user_mapping}
    missing = [field for field in REQUIRED_FIELDS if not effective.get(field)]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "mapping": "Сопоставьте обязательные колонки",
                "missing": missing,
                "headers": headers,
                "suggested": suggested,
            },
        )

    owner = actor.id
    if is_supervisor(actor) and owner_id:
        ensure_user(db, owner_id)
        owner = owner_id

    countries, cities, niches, by_domain, by_name_country_city, by_name_country = _build_lookup(db)
    cities_by_key = {(c.country_id, normalize_name(c.name)): c for c in cities}
    seen_domains: dict[str, int] = {}
    seen_keys: dict[tuple, int] = {}
    rows: list[dict] = []
    counts = {STATUS_OK: 0, STATUS_DUP: 0, STATUS_ERROR: 0}

    for index, raw in enumerate(raw_rows, start=2):
        name = _get(raw, effective, "name")
        country_name = _get(raw, effective, "country")
        city_name = _get(raw, effective, "city")
        site = _get(raw, effective, "website_url")
        niche_name = _get(raw, effective, "niche")
        need = _get(raw, effective, "observed_need")

        row = {
            "row_number": index,
            "name": name or None,
            "country": country_name or None,
            "city": city_name or None,
            "website_url": site or None,
            "niche": niche_name or None,
            "observed_need": need or None,
            "status": STATUS_OK,
            "reason": None,
            "matched_company_id": None,
            "warnings": [],
        }

        if not name:
            row["status"] = STATUS_ERROR
            row["reason"] = "Пустое название"
        elif not country_name:
            row["status"] = STATUS_ERROR
            row["reason"] = "Пустая страна"
        else:
            country = countries.get(normalize_name(country_name))
            if country is None:
                row["status"] = STATUS_ERROR
                row["reason"] = f"Страна не найдена: {country_name}"
            else:
                city_id = None
                if city_name:
                    city = cities_by_key.get((country.id, normalize_name(city_name)))
                    if city is None:
                        row["warnings"].append(f"Город не найден: {city_name} (импорт без города)")
                    else:
                        city_id = city.id
                if niche_name and normalize_name(niche_name) not in niches:
                    row["warnings"].append(f"Ниша не найдена: {niche_name} (импорт без ниши)")

                domain = normalize_domain(site) if site else None
                key_city = (normalize_name(name), country.id, city_id)
                key_country = (normalize_name(name), country.id)
                existing = None
                duplicate_reason = None

                if domain and domain in by_domain:
                    existing = by_domain[domain]
                    duplicate_reason = f"Домен уже есть: {domain}"
                elif domain and domain in seen_domains:
                    row["status"] = STATUS_DUP
                    duplicate_reason = f"Повтор внутри файла (строка {seen_domains[domain]})"
                else:
                    hit = None
                    if city_id is not None:
                        hit = by_name_country_city.get(key_city)
                        if hit is not None and hit.city_id is None:
                            hit = None
                    if hit is None:
                        hit = by_name_country.get(key_country)
                        if hit is not None and city_id is not None and hit.city_id not in (None, city_id):
                            hit = None
                    if hit is not None:
                        existing = hit
                        duplicate_reason = "Компания с таким названием уже есть"
                    else:
                        seen_key = key_city if city_id else key_country
                        if seen_key in seen_keys:
                            row["status"] = STATUS_DUP
                            duplicate_reason = f"Повтор внутри файла (строка {seen_keys[seen_key]})"
                        else:
                            seen_keys[seen_key] = index

                if existing is not None and row["status"] == STATUS_OK:
                    row["status"] = STATUS_DUP
                    row["reason"] = duplicate_reason
                    row["matched_company_id"] = existing.id
                    if existing.archived_at is not None:
                        row["reason"] = f"{duplicate_reason} (карточка в архиве)"
                elif row["status"] == STATUS_DUP:
                    row["reason"] = duplicate_reason
                if domain:
                    seen_domains.setdefault(domain, index)

        counts[row["status"]] += 1
        rows.append(row)

    preview = ImportPreview(
        id=str(uuid.uuid4()),
        actor_id=actor.id,
        owner_id=owner,
        filename=filename,
        source_kind=kind,
        file_sha256=hashlib.sha256(file_bytes).hexdigest(),
        headers_json=json.dumps(headers, ensure_ascii=False),
        mapping_json=json.dumps(effective, ensure_ascii=False),
        rows_json=json.dumps(rows, ensure_ascii=False),
        rows_total=len(rows),
        rows_ok=counts[STATUS_OK],
        rows_dup=counts[STATUS_DUP],
        rows_error=counts[STATUS_ERROR],
        expires_at=utcnow() + timedelta(minutes=settings.IMPORT_PREVIEW_TTL_MINUTES),
    )
    db.add(preview)
    db.commit()
    db.refresh(preview)
    return preview


def preview_to_dict(preview: ImportPreview) -> dict:
    rows = json.loads(preview.rows_json or "[]")
    return {
        "preview_id": preview.id,
        "filename": preview.filename,
        "source_kind": preview.source_kind,
        "headers": json.loads(preview.headers_json or "[]"),
        "mapping": json.loads(preview.mapping_json or "{}"),
        "owner_id": preview.owner_id,
        "rows": rows,
        "counts": {
            "total": preview.rows_total,
            "ok": preview.rows_ok,
            "dup": preview.rows_dup,
            "error": preview.rows_error,
        },
        "created_at": preview.created_at,
        "expires_at": preview.expires_at,
    }


def _get_preview_for_update(db: Session, preview_id: str, actor: User) -> ImportPreview:
    preview = db.get(ImportPreview, preview_id, with_for_update=True)
    if preview is None:
        raise HTTPException(status_code=404, detail="Предпросмотр импорта не найден")
    if preview.actor_id != actor.id and not is_supervisor(actor):
        raise HTTPException(status_code=403, detail="Нет доступа к этому импорту")
    return preview


def commit_import(
    db: Session,
    preview_id: str,
    actor: User,
    owner_id: Optional[int] = None,
    row_numbers: Optional[list[int]] = None,
) -> dict:
    preview = _get_preview_for_update(db, preview_id, actor)
    if preview.result_json:
        result = json.loads(preview.result_json)
        result["already_committed"] = True
        return result
    if preview.expires_at is not None and preview.expires_at < utcnow():
        raise HTTPException(status_code=409, detail="Срок действия предпросмотра истёк. Загрузите файл заново.")

    owner = preview.owner_id or actor.id
    if owner_id:
        ensure_user(db, owner_id)
        owner = owner_id

    rows = json.loads(preview.rows_json or "[]")
    selected = set(row_numbers) if row_numbers else None
    countries, cities, niches, by_domain, by_name_country_city, by_name_country = _build_lookup(db)
    cities_by_key = {(c.country_id, normalize_name(c.name)): c for c in cities}

    ok = skipped = failed = 0
    report_rows: list[dict] = []
    for row in rows:
        number = row.get("row_number")
        if selected is not None and number not in selected:
            continue
        if row.get("status") != STATUS_OK:
            if row.get("status") == STATUS_DUP:
                skipped += 1
            else:
                failed += 1
            report_rows.append({"row_number": number, "status": row.get("status"), "reason": row.get("reason")})
            continue

        country = countries.get(normalize_name(row.get("country")))
        if country is None:
            failed += 1
            report_rows.append({"row_number": number, "status": STATUS_ERROR, "reason": "Страна не найдена"})
            continue

        city_id = None
        city_name = row.get("city")
        if city_name:
            city = cities_by_key.get((country.id, normalize_name(city_name)))
            city_id = city.id if city else None

        domain = normalize_domain(row.get("website_url"))
        existing = None
        if domain and domain in by_domain:
            existing = by_domain[domain]
        elif (city_id is not None and (normalize_name(row.get("name")), country.id, city_id) in by_name_country_city):
            existing = by_name_country_city[(normalize_name(row.get("name")), country.id, city_id)]
        elif (normalize_name(row.get("name")), country.id) in by_name_country:
            existing = by_name_country[(normalize_name(row.get("name")), country.id)]

        if existing is not None:
            skipped += 1
            report_rows.append({
                "row_number": number, "status": STATUS_DUP,
                "reason": f"Компания уже существует (id {existing.id})",
            })
            continue

        niche = niches.get(normalize_name(row.get("niche"))) if row.get("niche") else None
        company = Company(
            name=row["name"].strip(),
            country_id=country.id,
            city_id=city_id,
            niche_id=niche.id if niche else None,
            website_url=row.get("website_url"),
            normalized_domain=domain,
            owner_id=owner,
            observed_need=row.get("observed_need"),
            version=1,
        )
        db.add(company)
        db.flush()
        by_domain[domain] = company if domain else by_domain.get(domain)
        by_name_country[(normalize_name(company.name), country.id)] = company
        by_name_country_city[(normalize_name(company.name), country.id, city_id)] = company
        ok += 1
        report_rows.append({"row_number": number, "status": "created", "reason": None, "company_id": company.id})

    result = {
        "preview_id": preview.id,
        "ok": ok,
        "skipped": skipped,
        "failed": failed,
        "rows": report_rows,
        "already_committed": False,
    }
    db.add(Journal(
        kind=ImportKind.IMPORT, entity="companies", actor_id=actor.id, filename=preview.filename,
        rows_total=len(report_rows), rows_ok=ok, rows_skipped=skipped, rows_failed=failed,
        report_json=json.dumps(result, ensure_ascii=False),
    ))
    preview.committed_at = utcnow()
    preview.result_json = json.dumps(result, ensure_ascii=False)
    preview.owner_id = owner
    touch(preview)
    db.commit()
    return result
