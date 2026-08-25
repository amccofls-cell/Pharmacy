import csv
import io
import json
import os
import re
import time
import html as html_lib
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

# ─────────────────────────────────────────────────────────────
# 의약품 허가정보·약가 통합 조회 — Streamlit version
# ─────────────────────────────────────────────────────────────
MFDS_LIST_URL = "http://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07/getDrugPrdtPrmsnInq07"
MFDS_DETAIL_URL = "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07/getDrugPrdtPrmsnDtlInq06"
HIRA_PRICE_URL = "https://apis.data.go.kr/B551182/dgamtCrtrInfoService1.2/getDgamtList"
FIELD_BAR_CODE = "BAR_CODE"
LIST_NUM_OF_ROWS = 500
HIRA_CALL_LIMIT = 600
MFDS_CALL_LIMIT = 1000
LIST_CSV_FIELDS = ["ITEM_SEQ", "ITEM_NAME", "ENTP_NAME", "CANCEL_NAME", "ITEM_PERMIT_DATE"]

# 📌 요청사항 반영: 제품코드 및 보관방법 기본 컬럼 포함
BASE_COLUMNS = ["허가제품명", "제약사한글명", "제품코드", "약가", "약효분류", "주성분영문명", "성분명", "효능효과", "용법용량", "보관방법"]
HIRA_MEFT_FIELD = "meftDivNo"

EXTRA_FIELD_SPECS = {
    "영문제품명": {"label": "영문 제품명", "source": "ITEM_ENG_NAME", "transform": "direct"},
    "주성분영문명": {"label": "주성분 영문명", "source": "MAIN_INGR_ENG", "transform": "direct"},
    "보관방법": {"label": "보관방법", "source": "STORAGE_METHOD", "transform": "direct"},
    "전문일반구분": {"label": "전문·일반의약품 구분", "source": "ETC_OTC_CODE", "transform": "direct"},
    "ATC코드": {"label": "ATC 코드", "source": "ATC_CODE", "transform": "direct"},
    "원료약품및분량": {"label": "원료약품 및 분량", "source": "MATERIAL_NAME", "transform": "direct"},
    "소아_고령자투여": {"label": "소아·고령자 투여", "source": "NB_DOC_DATA", "keywords": ["소아에 대한 투여", "소아투여", "고령자에 대한 투여", "고령자투여"], "transform": "section"},
    "임부_수유부투여": {"label": "임부 및 수유부 투여", "source": "NB_DOC_DATA", "keywords": ["임부 및 수유부에 대한 투여", "임부에 대한 투여", "수유부에 대한 투여", "임부투여", "수유부투여"], "transform": "section"},
    "금기사항": {"label": "금기사항", "source": "NB_DOC_DATA", "keywords": ["다음 환자에게는 투여하지 말 것", "투여하지 말 것", "금기"], "transform": "section"},
    "신중투여": {"label": "신중히 투여할 환자", "source": "NB_DOC_DATA", "keywords": ["다음 환자에는 신중히 투여할 것", "신중히 투여"], "transform": "section"},
    "일반적주의": {"label": "일반적 주의", "source": "NB_DOC_DATA", "keywords": ["일반적 주의"], "transform": "section"},
    "상호작용": {"label": "상호작용", "source": "NB_DOC_DATA", "keywords": ["상호작용"], "transform": "section"},
    "이상반응": {"label": "이상반응", "source": "NB_DOC_DATA", "keywords": ["이상반응", "이상 반응"], "transform": "section"},
    "과량투여처치": {"label": "과량투여시의 처치", "source": "NB_DOC_DATA", "keywords": ["과량투여시의 처치", "과량투여", "과량 투여"], "transform": "section"},
    "적용상의주의사항": {"label": "적용상의 주의사항", "source": "NB_DOC_DATA", "keywords": ["적용상의 주의", "적용상 주의"], "transform": "section"},
    "기타주의사항": {"label": "기타 사용상 주의사항", "source": "NB_DOC_DATA", "keywords": ["기타"], "transform": "section"},
    "포장단위": {"label": "포장단위", "source": "PACK_UNIT", "transform": "direct"},
    "유효기간": {"label": "유효기간", "source": "VALID_TERM", "transform": "direct"},
    "보관_취급주의사항": {"label": "보관 및 취급상의 주의사항", "source": "NB_DOC_DATA", "keywords": ["보관 및 취급상의 주의사항", "보관 및 취급상의 주의", "보관취급상의주의사항"], "transform": "section"},
    "성상": {"label": "성상", "source": "CHART", "transform": "direct"},
    "변경내용": {"label": "변경내용", "source": "GBN_NAME", "transform": "direct"},
    "변경일자": {"label": "변경일자", "source": "CHANGE_DATE", "transform": "direct"},
}
EXTRA_FIELD_ORDER = [
    "영문제품명", "주성분영문명", "보관방법", "전문일반구분", "ATC코드", "원료약품및분량",
    "소아_고령자투여", "임부_수유부투여",
    "금기사항", "신중투여", "일반적주의",
    "상호작용",
    "이상반응", "과량투여처치",
    "적용상의주의사항", "기타주의사항",
    "포장단위", "유효기간", "보관_취급주의사항", "성상", "변경내용", "변경일자",
]
EXTRA_FIELD_LABELS = {key: EXTRA_FIELD_SPECS[key]["label"] for key in EXTRA_FIELD_ORDER}
EXTRA_FIELD_KEYWORDS = {key: EXTRA_FIELD_SPECS[key]["keywords"] for key in EXTRA_FIELD_ORDER if "keywords" in EXTRA_FIELD_SPECS[key]}
EXTRA_DIRECT_FIELDS = {key: EXTRA_FIELD_SPECS[key]["source"] for key in EXTRA_FIELD_ORDER if EXTRA_FIELD_SPECS[key]["transform"] == "direct"}

# 📌 요청사항 반영
ALWAYS_FETCH_DETAIL_KEYS = ["주성분영문명", "보관방법"]
RESULT_COLUMN_ORDER = ["허가제품명", "제약사한글명", "제품코드", "약가", "약효분류", "주성분영문명", "성분명", "효능효과", "용법용량", "보관방법"]

HEADING_PATTERN = re.compile(r"^\s*\d+\s*[.\-]")
MAX_RETRY = 5

DUR_CATEGORIES = [
    "병용금기(급여)", "병용금기(비급여)", "임부금기", "연령금기", "효능군중복",
    "수유부주의", "비대면진료처방금지", "비용효과적인함량의약품",
]
DUR_EXTRA_COLUMNS = {
    "임부금기": ["금기등급", "상세정보"],
    "연령금기": ["특정연령", "특정연령단위코드", "연령처리조건", "상세정보"],
    "효능군중복": ["효능군", "Group"],
}
DUR_CODE_COLUMN_PATTERN = re.compile(r"(제품코드|약품코드|품목코드|EDI)", re.IGNORECASE)

DATA_DIR = Path(os.environ.get("DRUG_APP_DATA_DIR", "."))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LIST_FILE = DATA_DIR / "허가목록_원본.csv"
TEMP_FILE = DATA_DIR / "허가목록_임시.json"
CACHE_CODE_FILE = DATA_DIR / "cache_약가_코드별.json"
CACHE_NAME_FILE = DATA_DIR / "cache_약가_이름별.json"
CACHE_DETAIL_FILE = DATA_DIR / "cache_상세정보.json"
CACHE_MEFT_FILE = DATA_DIR / "cache_약효분류.json"
LIST_META_FILE = DATA_DIR / "허가목록_메타.json"
KST = timezone(timedelta(hours=9))


def clean_whitespace(text):
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def clean_ingredient(text):
    if not text:
        return ""
    return clean_whitespace(re.sub(r"\[[A-Za-z0-9]+\]", "", text))


def clean_markup(text):
    if not text:
        return ""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = html_lib.unescape(text)
    text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)
    return clean_whitespace(text)


def parse_nested_doc_xml(xml_str):
    if not xml_str or not xml_str.strip():
        return ""
    try:
        root = ET.fromstring(xml_str.strip())
    except ET.ParseError:
        return clean_markup(xml_str)
    parts = []
    for el in root.iter():
        title = el.get("title")
        if title:
            parts.append(title.strip())
        if el.text and el.text.strip():
            parts.append(el.text.strip())
    return clean_markup(" ".join(parts))


def parse_doc_sections(xml_str, keywords):
    if not xml_str or not xml_str.strip():
        return ""
    try:
        root = ET.fromstring(xml_str.strip())
    except ET.ParseError:
        return ""
    chunks = []
    for el in root.iter():
        title = el.get("title")
        if title and title.strip():
            chunks.append((bool(HEADING_PATTERN.match(title.strip())), title.strip()))
        if el.text and el.text.strip():
            chunks.append((False, el.text.strip()))
    heading_idx = [i for i, (heading, _) in enumerate(chunks) if heading]
    picked = []
    if heading_idx:
        for n, idx in enumerate(heading_idx):
            heading_text = chunks[idx][1]
            if any(keyword in heading_text for keyword in keywords):
                end = heading_idx[n + 1] if n + 1 < len(heading_idx) else len(chunks)
                picked.extend(text for _, text in chunks[idx:end])
    else:
        picked.extend(text for _, text in chunks if any(keyword in text for keyword in keywords))
    return clean_markup(" ".join(picked))


def summarize_text(text, max_chars=420, max_sentences=3):
    text = clean_whitespace(text)
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+|(?=\d+\.)", text) if part.strip()]
    selected = []
    for sentence in sentences:
        if sentence not in selected:
            selected.append(sentence)
        if len(selected) >= max_sentences:
            break
    summary = " ".join(selected)
    if len(summary) < 80:
        summary = text[:max_chars]
    return summary[:max_chars].rstrip() + ("…" if len(summary) > max_chars else "")


def summarize_usage(text, max_chars=520):
    text = clean_whitespace(text)
    if not text:
        return ""
    headings = list(re.finditer(r"<[^>]{1,20}>", text))
    if not headings:
        return summarize_text(text, max_chars=max_chars, max_sentences=4)
    parts = []
    for index, match in enumerate(headings):
        start = match.start()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[start:end].strip()
        if section:
            parts.append(summarize_text(section, max_chars=180, max_sentences=2))
    summary = " ".join(parts)
    return summary[:max_chars].rstrip() + ("…" if len(summary) > max_chars else "")


def make_summary_df(result_df):
    summary_df = result_df.copy()
    if "효능효과" in summary_df.columns:
        summary_df["효능효과"] = summary_df["효능효과"].map(lambda value: summarize_text(value))
    if "용법용량" in summary_df.columns:
        summary_df["용법용량"] = summary_df["용법용량"].map(lambda value: summarize_usage(value))
    for column in summary_df.columns:
        # 📌 요청사항 반영: 제외 대상에 제품코드, 보관방법 추가
        if column not in {"효능효과", "용법용량", "허가제품명", "제약사한글명", "제품코드", "약가", "약효분류", "주성분영문명", "보관방법"}:
            summary_df[column] = summary_df[column].map(lambda value: summarize_text(value, max_chars=260, max_sentences=2))
    return summary_df


def load_json_cache(path):
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                value = json.load(file)
                return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def save_json_cache(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    tmp.replace(path)


def barcode_key8(bar_code):
    if not bar_code:
        return None
    digits = re.sub(r"\D", "", str(bar_code))
    return digits[3:11] if len(digits) >= 11 else None


def mdscd_key8(mds_cd):
    if mds_cd is None:
        return None
    if isinstance(mds_cd, float):
        if pd.isna(mds_cd):
            return None
        mds_cd = str(int(mds_cd))
    elif not mds_cd:
        return None
    digits = re.sub(r"\D", "", str(mds_cd))
    return digits[:8] if len(digits) >= 8 else None


def normalize_code_digits(value):
    if value is None:
        return ""
    if isinstance(value, float):
        if pd.isna(value):
            return ""
        value = str(int(value)) if value.is_integer() else str(value)
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return re.sub(r"\D", "", text)


def code_lookup_keys(value):
    digits = normalize_code_digits(value)
    if not digits:
        return []
    keys = [digits]
    key8 = digits[:8] if len(digits) >= 8 else ""
    if key8 and key8 not in keys:
        keys.append(key8)
    return keys


def split_barcode_values(bar_code_text):
    raw = str(bar_code_text or "")
    parts = re.split(r"[,/;\n]+", raw)
    values = []
    for part in parts:
        digits = normalize_code_digits(part)
        if digits:
            values.append(digits)
    return values


def collect_dur_candidate_codes(item_seq, detail):
    candidates = []

    def add_codes(source, raw_value):
        digits = normalize_code_digits(raw_value)
        if not digits:
            return
        for key in code_lookup_keys(digits):
            candidates.append((key, source, digits))

    for barcode in split_barcode_values(detail.get("_bar_code", "")):
        add_codes("바코드", barcode)
    add_codes("EDI코드", detail.get("_edi_code", ""))
    add_codes("품목코드", item_seq)

    deduped = []
    seen = set()
    for item in candidates:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def _excel_engine_for(filename):
    return "pyxlsb" if filename.lower().endswith(".xlsb") else None


def _find_dur_header_row(file_bytes, filename, sheet_name=0, max_scan=15):
    """지정한 시트에서 '코드'가 들어간 열이 나오는 행을 헤더로 판단합니다."""
    engine = _excel_engine_for(filename)
    raw = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name, header=None, engine=engine, nrows=max_scan)
    for i in range(len(raw)):
        row_vals = [str(v) for v in raw.iloc[i].tolist()]
        if any(DUR_CODE_COLUMN_PATTERN.search(v) for v in row_vals):
            return i
    return 0


# 📌 요청사항 반영: 여러 시트(Sheet)를 가진 엑셀 파일도 통합하여 처리 가능하도록 구현
def read_dur_excel(file_bytes, filename):
    engine = _excel_engine_for(filename)
    excel_file = pd.ExcelFile(io.BytesIO(file_bytes), engine=engine)
    all_dfs = []
    header_rows = {}

    for sheet in excel_file.sheet_names:
        header_row = _find_dur_header_row(file_bytes, filename, sheet_name=sheet)
        header_rows[sheet] = header_row
        sheet_df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet, header=header_row, engine=engine)
        sheet_df.columns = [str(c).strip() for c in sheet_df.columns]
        sheet_df["_SHEET_NAME"] = str(sheet)
        all_dfs.append(sheet_df)

    combined_df = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    return combined_df, header_rows


def build_dur_index(df):
    code_cols = [c for c in df.columns if DUR_CODE_COLUMN_PATTERN.search(str(c))]
    if not code_cols:
        return {}, code_cols
    idx = {}
    for row_number, (_, row) in enumerate(df.iterrows(), start=1):
        row_dict = row.to_dict()
        for col in code_cols:
            digits = normalize_code_digits(row.get(col))
            if not digits:
                continue
            payload = {
                "row": row_dict,
                "_dur_code_column": str(col),
                "_dur_code_value": digits,
                "_dur_row_number": row_number,
                "_sheet_name": row_dict.get("_SHEET_NAME", ""),
            }
            for key in code_lookup_keys(digits):
                idx.setdefault(key, []).append(payload)
    return idx, code_cols


@st.cache_data(show_spinner="DUR 파일을 읽는 중입니다…")
def parse_dur_excel_cached(file_bytes, filename):
    df, header_rows = read_dur_excel(file_bytes, filename)
    index, code_columns = build_dur_index(df)
    return df, header_rows, index, code_columns


def _items_from_body(body):
    items = body.get("items", []) if isinstance(body, dict) else []
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return items or []


def _parse_response_items(resp, api_name):
    resp.raise_for_status()
    text = resp.text.strip()
    if text.startswith("<"):
        root = ET.fromstring(text)
        result_code = root.findtext(".//resultCode")
        if result_code and result_code != "00":
            raise ValueError(f"{api_name} API 오류: {root.findtext('.//resultMsg')}")
        return [{child.tag: (child.text or "") for child in item_el} for item_el in root.findall(".//items/item")]
    data = resp.json()
    body = data.get("body", data.get("response", {}).get("body", {}))
    return _items_from_body(body)


def hira_get(service_key, params):
    query = {"serviceKey": service_key, "type": "json"}
    query.update(params)
    return _parse_response_items(requests.get(HIRA_PRICE_URL, params=query, timeout=30), "HIRA")


def match_price(item_name, bar_code, service_key, call_counter, cache_code, cache_name, errors):
    key8 = barcode_key8(bar_code)
    if key8:
        if key8 in cache_code:
            cached = cache_code[key8]
            return (cached, "bar_code_8자리(캐시)") if cached else ("", "매칭없음(캐시)")
        if call_counter["hira"] < HIRA_CALL_LIMIT:
            call_counter["hira"] += 1
            try:
                items = hira_get(service_key, {"mdsCd": key8})
            except (requests.RequestException, ValueError) as exc:
                errors.append(f"HIRA mdsCd={key8}: {exc}")
                items = []
            valid = [it for it in items if it.get("payTpNm") != "삭제"]
            exact = [it for it in valid if mdscd_key8(it.get("mdsCd")) == key8]
            if exact:
                price = exact[0].get("mxCprc", "")
                cache_code[key8] = price
                return price, "bar_code_8자리(직접조회)"
    name_key = re.sub(r"_\(.*?\)\s*$", "", item_name or "").strip()
    if name_key in cache_name:
        cached = cache_name[name_key]
    else:
        if call_counter["hira"] >= HIRA_CALL_LIMIT:
            return "", "호출한도초과"
        call_counter["hira"] += 1
        call_ok = True
        try:
            items = hira_get(service_key, {"itmNm": name_key})
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"HIRA itmNm={name_key}: {exc}")
            items, call_ok = [], False
        valid = [it for it in items if it.get("payTpNm") != "삭제"]
        cached = ""
        if key8:
            exact = [it for it in valid if mdscd_key8(it.get("mdsCd")) == key8]
            if exact:
                cached = exact[0].get("mxCprc", "")
                cache_code[key8] = cached
        if not cached:
            def norm(name):
                return re.sub(r"_\(.*?\)\s*$", "", name or "").strip()
            exact_name = [it for it in valid if norm(it.get("itmNm")) == name_key]
            if exact_name:
                cached = exact_name[0].get("mxCprc", "")
        if call_ok:
            cache_name[name_key] = cached
    if cached:
        return cached, "품목명검색(8자리검증 또는 완전일치)"
    return "", "매칭없음"


def get_effect_classification(item_name, bar_code, service_key, call_counter, cache_meft, errors):
    key8 = barcode_key8(bar_code)
    cache_key = f"mdsCd:{key8}" if key8 else f"itmNm:{re.sub(r'_\(.*?\)\s*$', '', item_name or '').strip()}"
    if cache_key in cache_meft:
        return cache_meft[cache_key]
    if call_counter["hira"] >= HIRA_CALL_LIMIT:
        return ""
    call_counter["hira"] += 1
    try:
        params = {"mdsCd": key8} if key8 else {"itmNm": re.sub(r"_\(.*?\)\s*$", "", item_name or "").strip()}
        items = hira_get(service_key, params)
    except (requests.RequestException, ValueError) as exc:
        errors.append(f"HIRA 약효분류 {cache_key}: {exc}")
        return ""
    valid = [item for item in items if item.get("payTpNm") != "삭제"]
    if key8:
        valid = [item for item in valid if mdscd_key8(item.get("mdsCd")) == key8] or valid
    value = clean_whitespace(valid[0].get(HIRA_MEFT_FIELD, "")) if valid else ""
    cache_meft[cache_key] = value
    return value


def fetch_detail(item_seq, service_key, call_counter, cache_detail, wanted_extras, errors):
    cached = cache_detail.get(item_seq, {})
    have_base = "성분명" in cached
    missing_extras = [key for key in wanted_extras if key not in cached]
    if have_base and not missing_extras:
        return cached
    cached_direct_ready = all(
        key not in EXTRA_DIRECT_FIELDS or ("_raw_" + key) in cached
        for key in missing_extras
    )
    if have_base and "_raw_nb_xml" in cached and cached_direct_ready:
        for key in missing_extras:
            if key in EXTRA_DIRECT_FIELDS:
                cached[key] = cached.get("_raw_" + key, "")
            else:
                cached[key] = parse_doc_sections(cached["_raw_nb_xml"], EXTRA_FIELD_KEYWORDS[key])
        cache_detail[item_seq] = cached
        return cached
    if call_counter["mfds"] >= MFDS_CALL_LIMIT:
        return cached if cached else {"성분명": "", "효능효과": "", "용법용량": ""}
    call_counter["mfds"] += 1
    params = {"serviceKey": service_key, "item_seq": item_seq, "type": "json"}
    try:
        items = _parse_response_items(requests.get(MFDS_DETAIL_URL, params=params, timeout=30), "MFDS 상세")
        if not items:
            errors.append(f"MFDS 상세 item_seq={item_seq}: items 없음")
            return cached if cached else {"성분명": "", "효능효과": "", "용법용량": ""}
        item = items[0]
    except (requests.RequestException, ValueError, ET.ParseError) as exc:
        errors.append(f"MFDS 상세 item_seq={item_seq}: {exc}")
        return cached if cached else {"성분명": "", "효능효과": "", "용법용량": ""}
    nb_xml = item.get("NB_DOC_DATA", "")
    cached["성분명"] = clean_ingredient(item.get("MAIN_ITEM_INGR", ""))
    cached["효능효과"] = parse_nested_doc_xml(item.get("EE_DOC_DATA", ""))
    cached["용법용량"] = parse_nested_doc_xml(item.get("UD_DOC_DATA", ""))
    cached["_bar_code"] = item.get("BAR_CODE", "")
    cached["_edi_code"] = item.get("EDI_CODE", "")
    cached["_raw_nb_xml"] = nb_xml
    
    # 📌 요청사항 반영: 제품코드 및 보관방법 설정
    cached["제품코드"] = barcode_key8(cached["_bar_code"]) or clean_whitespace(item_seq)
    cached["보관방법"] = clean_whitespace(item.get("STORAGE_METHOD", ""))

    for key, field in EXTRA_DIRECT_FIELDS.items():
        cached["_raw_" + key] = clean_whitespace(item.get(field, ""))
    for key in wanted_extras:
        cached[key] = cached.get("_raw_" + key, "") if key in EXTRA_DIRECT_FIELDS else parse_doc_sections(nb_xml, EXTRA_FIELD_KEYWORDS[key])
    cache_detail[item_seq] = cached
    return cached


def current_kst_date():
    return datetime.now(KST).date().isoformat()


def list_cache_is_fresh():
    if not LIST_FILE.exists() or not LIST_META_FILE.exists():
        return False
    try:
        with LIST_META_FILE.open("r", encoding="utf-8") as file:
            meta = json.load(file)
        return meta.get("collected_date_kst") == current_kst_date()
    except (OSError, json.JSONDecodeError):
        return False


def fetch_list_page(page, mfds_key):
    params = {"serviceKey": mfds_key, "pageNo": page, "numOfRows": LIST_NUM_OF_ROWS, "type": "json"}
    last_err = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = requests.get(MFDS_LIST_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            body = data.get("body", data.get("response", {}).get("body", {}))
            return body, _items_from_body(body)
        except (requests.RequestException, ValueError) as exc:
            last_err = exc
            time.sleep(min(2 ** attempt, 30))
    raise last_err


@st.cache_data(show_spinner=False)
def load_permitted_drugs(mfds_key, data_dir_string, cache_day, force_refresh_token=0):
    list_file = Path(data_dir_string) / "허가목록_원본.csv"
    temp_file = Path(data_dir_string) / "허가목록_임시.json"
    meta_file = Path(data_dir_string) / "허가목록_메타.json"
    cache_is_fresh = list_file.exists() and meta_file.exists()
    if cache_is_fresh:
        try:
            with meta_file.open("r", encoding="utf-8") as file:
                cache_is_fresh = json.load(file).get("collected_date_kst") == cache_day
        except (OSError, json.JSONDecodeError):
            cache_is_fresh = False
    if cache_is_fresh:
        with list_file.open("r", encoding="utf-8-sig", newline="") as file:
            return list(csv.DictReader(file))
    if not mfds_key:
        raise ValueError("오늘 날짜의 허가목록 캐시가 없습니다. 식약처 인증키를 입력해야 허가목록을 갱신할 수 있습니다.")
    if temp_file.exists():
        with temp_file.open("r", encoding="utf-8") as file:
            resume = json.load(file)
        all_rows, page, total_count = resume["rows"], resume["next_page"], resume.get("total_count")
    else:
        all_rows, page, total_count = [], 1, None
    progress = st.progress(0, text="식약처 허가목록을 수집하는 중입니다…")
    while True:
        body, items = fetch_list_page(page, mfds_key)
        if total_count is None:
            total_count = int(body.get("totalCount", 0))
        if not items:
            break
        all_rows.extend(items)
        page += 1
        if total_count:
            progress.progress(min(len(all_rows) / total_count, 1.0), text=f"허가목록 수집 중: {len(all_rows):,}/{total_count:,}")
        if page % 10 == 0 or (total_count and len(all_rows) >= total_count):
            with temp_file.open("w", encoding="utf-8") as file:
                json.dump({"rows": all_rows, "next_page": page, "total_count": total_count}, file, ensure_ascii=False)
        if total_count and len(all_rows) >= total_count:
            break
        time.sleep(0.1)
    progress.empty()
    with list_file.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=LIST_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in LIST_CSV_FIELDS} for row in all_rows)
    if temp_file.exists():
        temp_file.unlink()
    with meta_file.open("w", encoding="utf-8") as file:
        json.dump({"collected_date_kst": cache_day, "updated_at": datetime.now(KST).isoformat()}, file, ensure_ascii=False, indent=2)
    return all_rows


def order_result_columns(df):
    ordered = [column for column in RESULT_COLUMN_ORDER if column in df.columns]
    ordered += [column for column in EXTRA_FIELD_ORDER if column in df.columns and column not in ordered]
    ordered += [column for column in df.columns if column not in ordered]
    return df[ordered]


def make_display_df(result_df, summary_view=False, transpose_view=False):
    display_df = make_summary_df(result_df) if summary_view else result_df.copy()
    display_df = order_result_columns(display_df)
    if transpose_view:
        display_df = display_df.T
        display_df.index.name = "항목"
    return display_df


def result_column_config(df):
    config = {}
    long_columns = {"효능효과", "용법용량", "성분명", "이상반응", "상호작용", "금기사항", "원료약품및분량"}
    for column in df.columns:
        config[column] = st.column_config.TextColumn(
            label=str(column),
            width="large" if column in long_columns else "medium",
            help="헤더 경계를 드래그해 컬럼 너비를 조절할 수 있습니다.",
        )
    return config


def filter_result_dataframe(df, widget_prefix="result_filter"):
    filtered = df.copy()
    with st.expander("컬럼별 필터", expanded=False):
        st.caption("문자열은 포함 검색, 범주형은 여러 값 선택, 숫자형은 범위 필터를 사용합니다.")
        filter_columns = st.columns(2)
        for index, column in enumerate(df.columns):
            series = df[column].fillna("")
            numeric = pd.to_numeric(series.astype(str).str.replace(",", "", regex=False), errors="coerce")
            numeric_ratio = numeric.notna().mean() if len(series) else 0
            with filter_columns[index % 2]:
                if numeric_ratio >= 0.8 and numeric.notna().any():
                    minimum, maximum = float(numeric.min()), float(numeric.max())
                    if minimum < maximum:
                        selected_range = st.slider(
                            str(column), minimum, maximum, (minimum, maximum), key=f"{widget_prefix}_num_{index}"
                        )
                        filtered = filtered[numeric.loc[filtered.index].between(*selected_range)]
                    else:
                        st.caption(f"{column}: {minimum:g}")
                else:
                    values = sorted({str(value) for value in series if str(value).strip()})
                    if 0 < len(values) <= 30:
                        selected_values = st.multiselect(
                            str(column), values, key=f"{widget_prefix}_cat_{index}"
                        )
                        if selected_values:
                            filtered = filtered[filtered[column].astype(str).isin(selected_values)]
                    else:
                        text = st.text_input(f"{column} 포함 검색", key=f"{widget_prefix}_text_{index}")
                        if text.strip():
                            filtered = filtered[filtered[column].astype(str).str.contains(text.strip(), case=False, na=False)]
    return filtered


def render_resizable_wrapped_table(display_df, show_index=False, height=720, table_key="result"):
    table_df = display_df.reset_index() if show_index else display_df.reset_index(drop=True)
    if show_index:
        table_df = table_df.rename(columns={table_df.columns[0]: str(display_df.index.name or "항목")})
    headers = [str(column) for column in table_df.columns]
    long_columns = {"효능효과", "용법용량", "성분명", "이상반응", "상호작용", "금기사항", "원료약품및분량"}
    narrow_columns = {"약가", "제약사한글명", "약효분류", "제품코드"}

    def cell(value):
        if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
            value = ""
        return html_lib.escape(str(value)).replace("\\n", "<br>")

    if show_index:
        index_width_px = 160
        drug_column_count = max(len(headers) - 1, 1)
        col_widths = [f"{index_width_px}px"] + [
            f"calc((100% - {index_width_px}px) / {drug_column_count})"
        ] * drug_column_count
    else:
        def width_for(header):
            if header in narrow_columns:
                return 200
            if header == "허가제품명":
                return 1000
            if header in long_columns:
                return 720
            return 360

        col_widths = [f"{width_for(header)}px" for header in headers]

    colgroup = "".join(
        f'<col data-column="{index}" style="width:{width}">' for index, width in enumerate(col_widths)
    )
    header_html = "".join(f'<th data-column="{index}">{cell(header)}<span class="resize-handle" data-column="{index}"></span></th>' for index, header in enumerate(headers))
    body_html = []
    for row in table_df.itertuples(index=False, name=None):
        body_html.append("<tr>" + "".join(f"<td>{cell(value)}</td>" for value in row) + "</tr>")
    table_width_css = "width:100%;" if show_index else "width:max-content; min-width:100%;"
    markup = f"""
    <style>
      html, body {{ margin:0; padding:0; background:#fff; font-family:Arial, sans-serif; }}
      .table-wrap {{ width:100%; height:calc(100vh - 24px); overflow:auto; border:1px solid #d9dee7; }}
      table {{ border-collapse:collapse; table-layout:fixed; {table_width_css} font-size:13px; }}
      col {{ width:360px; }}
      th, td {{ border:1px solid #d9dee7; padding:8px; vertical-align:top; white-space:normal; overflow-wrap:anywhere; word-break:break-word; line-height:1.45; }}
      th {{ position:sticky; top:0; z-index:2; background:#f3f6fa; font-weight:700; text-align:left; user-select:none; }}
      .resize-handle {{ position:absolute; top:0; right:-4px; width:8px; height:100%; cursor:col-resize; z-index:3; }}
      .resize-handle:hover, .resizing {{ background:#5b8def; opacity:.55; }}
      body.resizing {{ cursor:col-resize; user-select:none; }}
    </style>
    <div class="table-wrap" id="wrap-{table_key}">
      <table id="table-{table_key}"><colgroup>{colgroup}</colgroup><thead><tr>{header_html}</tr></thead><tbody>{''.join(body_html)}</tbody></table>
    </div>
    <script>
      (() => {{
        const table = document.getElementById('table-{table_key}');
        const cols = table.querySelectorAll('col');
        table.querySelectorAll('.resize-handle').forEach(handle => {{
          handle.addEventListener('mousedown', event => {{
            event.preventDefault();
            const index = Number(handle.dataset.column);
            const startX = event.clientX;
            const startWidth = cols[index].getBoundingClientRect().width;
            document.body.classList.add('resizing');
            handle.classList.add('resizing');
            const move = moveEvent => {{
              const nextWidth = Math.max(120, startWidth + moveEvent.clientX - startX);
              cols[index].style.width = nextWidth + 'px';
            }};
            const stop = () => {{
              document.body.classList.remove('resizing');
              handle.classList.remove('resizing');
              document.removeEventListener('mousemove', move);
              document.removeEventListener('mouseup', stop);
            }};
            document.addEventListener('mousemove', move);
            document.addEventListener('mouseup', stop);
          }});
        }});
      }})();
    </script>
    """
    components.html(markup, height=height, scrolling=False)


def make_comparison_df(result_df):
    comparison = result_df.copy()
    item_names = comparison["허가제품명"].astype(str).tolist()
    deduped_names = []
    counts = {}
    for name in item_names:
        counts[name] = counts.get(name, 0) + 1
        if counts[name] > 1:
            deduped_names.append(f"{name} ({counts[name]})")
        else:
            deduped_names.append(name)
            
    comparison.index = deduped_names
    comparison = comparison.drop(columns=["허가제품명"], errors="ignore")
    comp_df = comparison.T
    comp_df.index.name = "항목"
    return comp_df


# ─────────────────────────────────────────────────────────────
# Streamlit UI & 메인 실행 부분
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="의약품 허가정보·약가 통합 조회", layout="wide")
st.title("💊 의약품 허가정보·약가 통합 서비스")

st.sidebar.header("🔑 API 인증키 및 옵션")
mfds_key = st.sidebar.text_input("식약처 API Key (Encoding)", type="password")
hira_key = st.sidebar.text_input("심평원 API Key (Encoding)", type="password")

cache_code = load_json_cache(CACHE_CODE_FILE)
cache_name = load_json_cache(CACHE_NAME_FILE)
cache_detail = load_json_cache(CACHE_DETAIL_FILE)
cache_meft = load_json_cache(CACHE_MEFT_FILE)

st.sidebar.subheader("📋 추가 확장 항목 선택")
wanted_extras = []
for extra_key in EXTRA_FIELD_ORDER:
    label = EXTRA_FIELD_LABELS[extra_key]
    if st.sidebar.checkbox(label, key=f"extra_{extra_key}"):
        wanted_extras.append(extra_key)

tab_search, tab_dur = st.tabs(["🔍 의약품 통합 검색", "⚠️ DUR Excel 비교"])

with tab_search:
    st.subheader("의약품 허가 및 약가 상세 조회")
    search_term = st.text_input("검색할 의약품명 또는 품목기준코드를 입력하세요:", "")

    if st.button("검색 실행", type="primary"):
        if not search_term.strip():
            st.warning("검색어를 입력해주세요.")
        else:
            try:
                kst_today = current_kst_date()
                raw_list = load_permitted_drugs(mfds_key, str(DATA_DIR), kst_today)
                
                matched = [
                    item for item in raw_list
                    if search_term.strip().lower() in item.get("ITEM_NAME", "").lower()
                    or search_term.strip() == item.get("ITEM_SEQ", "")
                ]
                
                if not matched:
                    st.info("검색 조건에 일치하는 의약품이 없습니다.")
                else:
                    st.success(f"총 {len(matched)}건의 의약품이 검색되었습니다.")
                    
                    call_counter = {"mfds": 0, "hira": 0}
                    errors = []
                    results = []

                    progress_bar = st.progress(0, text="상세 정보 및 약가 수집 중...")
                    for idx, item in enumerate(matched):
                        item_seq = item.get("ITEM_SEQ", "")
                        item_name = item.get("ITEM_NAME", "")
                        entp_name = item.get("ENTP_NAME", "")
                        
                        detail = fetch_detail(item_seq, mfds_key, call_counter, cache_detail, wanted_extras, errors)
                        bar_code = detail.get("_bar_code", "")
                        
                        price, match_type = match_price(item_name, bar_code, hira_key, call_counter, cache_code, cache_name, errors)
                        meft_class = get_effect_classification(item_name, bar_code, hira_key, call_counter, cache_meft, errors)
                        
                        # 📌 요청사항 반영: out_row 매핑 수정
                        row = {
                            "허가제품명": item_name,
                            "제약사한글명": entp_name,
                            "제품코드": detail.get("제품코드", barcode_key8(bar_code) or clean_whitespace(item_seq)),
                            "약가": price,
                            "약효분류": meft_class,
                            "주성분영문명": detail.get("주성분영문명", ""),
                            "성분명": detail.get("성분명", ""),
                            "효능효과": detail.get("효능효과", ""),
                            "용법용량": detail.get("용법용량", ""),
                            "보관방법": detail.get("보관방법", "")
                        }
                        
                        for extra in wanted_extras:
                            row[extra] = detail.get(extra, "")
                            
                        results.append(row)
                        progress_bar.progress((idx + 1) / len(matched))
                    
                    progress_bar.empty()
                    
                    save_json_cache(CACHE_CODE_FILE, cache_code)
                    save_json_cache(CACHE_NAME_FILE, cache_name)
                    save_json_cache(CACHE_DETAIL_FILE, cache_detail)
                    save_json_cache(CACHE_MEFT_FILE, cache_meft)
                    
                    res_df = pd.DataFrame(results)
                    st.session_state["search_result_df"] = res_df
                    
            except Exception as e:
                st.error(f"조회 중 오류가 발생했습니다: {e}")

    if "search_result_df" in st.session_state and not st.session_state["search_result_df"].empty:
        res_df = st.session_state["search_result_df"]
        
        view_mode = st.radio("보기 방식", ["기본 테이블", "요약본", "의약품 간 항목 비교 (Transpose)"], horizontal=True)
        filtered_df = filter_result_dataframe(res_df)

        if view_mode == "의약품 간 항목 비교 (Transpose)":
            comp_df = make_comparison_df(filtered_df)
            render_resizable_wrapped_table(comp_df, show_index=True, height=650, table_key="comp")
        elif view_mode == "요약본":
            disp_df = make_display_df(filtered_df, summary_view=True)
            render_resizable_wrapped_table(disp_df, show_index=False, height=650, table_key="summary")
        else:
            disp_df = make_display_df(filtered_df, summary_view=False)
            render_resizable_wrapped_table(disp_df, show_index=False, height=650, table_key="raw")

with tab_dur:
    st.subheader("DUR 엑셀 파일 검증 및 비교")
    uploaded_file = st.file_uploader("DUR Excel 파일을 업로드하세요 (.xlsx, .xls, .xlsb)", type=["xlsx", "xls", "xlsb"])
    
    if uploaded_file is not None:
        try:
            file_bytes = uploaded_file.getvalue()
            dur_df, header_rows, dur_idx, code_cols = parse_dur_excel_cached(file_bytes, uploaded_file.name)
            st.success(f"DUR 파일 파싱 완료! (인식된 시트 수: {len(header_rows)}개, 코드 컬럼: {', '.join(code_cols)})")
            
            with st.expander("DUR 통합 데이터 미리보기", expanded=False):
                st.dataframe(dur_df.head(20))
                
        except Exception as e:
            st.error(f"DUR 엑셀 파싱 오류: {e}")
