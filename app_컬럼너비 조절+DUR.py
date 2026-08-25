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
BASE_COLUMNS = ["허가제품명", "제약사한글명", "제품코드", "약가", "약효분류", "주성분영문명", "성분명", "효능효과", "용법용량", "보관방법"]
HIRA_MEFT_FIELD = "meftDivNo"

EXTRA_FIELD_SPECS = {
    "영문제품명": {"label": "영문 제품명", "source": "ITEM_ENG_NAME", "transform": "direct"},
    "주성분영문명": {"label": "주성분 영문명", "source": "MAIN_INGR_ENG", "transform": "direct"},
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
    "영문제품명", "주성분영문명", "전문일반구분", "ATC코드", "원료약품및분량",
    "소아_고령자투여", "임부_수유부투여", "금기사항", "신중투여", "일반적주의",
    "상호작용", "이상반응", "과량투여처치", "적용상의주의사항", "기타주의사항",
    "포장단위", "유효기간", "보관_취급주의사항", "성상", "변경내용", "변경일자",
]
EXTRA_FIELD_LABELS = {key: EXTRA_FIELD_SPECS[key]["label"] for key in EXTRA_FIELD_ORDER}
EXTRA_FIELD_KEYWORDS = {key: EXTRA_FIELD_SPECS[key]["keywords"] for key in EXTRA_FIELD_ORDER if "keywords" in EXTRA_FIELD_SPECS[key]}
EXTRA_DIRECT_FIELDS = {key: EXTRA_FIELD_SPECS[key]["source"] for key in EXTRA_FIELD_ORDER if EXTRA_FIELD_SPECS[key]["transform"] == "direct"}

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
    if not xml_str or not xml_str.strip() or not keywords:
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


def read_dur_excel(file_bytes, filename):
    engine = _excel_engine_for(filename)
    all_sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, header=None, engine=engine)
    
    parsed_dfs = []
    for sheet_name, sheet_raw in all_sheets.items():
        if sheet_raw.empty:
            continue
        header_row = 0
        for i in range(min(len(sheet_raw), 15)):
            row_vals = [str(v) for v in sheet_raw.iloc[i].tolist()]
            if any(DUR_CODE_COLUMN_PATTERN.search(v) for v in row_vals):
                header_row = i
                break
        
        sheet_df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name, header=header_row, engine=engine)
        sheet_df.columns = [str(c).strip() for c in sheet_df.columns]
        parsed_dfs.append(sheet_df)

    if not parsed_dfs:
        return pd.DataFrame(), 0
    return pd.concat(parsed_dfs, ignore_index=True), 0


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
            }
            for key in code_lookup_keys(digits):
                idx.setdefault(key, []).append(payload)
    return idx, code_cols


@st.cache_data(show_spinner="DUR 파일을 읽는 중입니다…")
def parse_dur_excel_cached(file_bytes, filename):
    df, header_row = read_dur_excel(file_bytes, filename)
    index, code_columns = build_dur_index(df)
    return df, header_row, index, code_columns


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
            elif key in EXTRA_FIELD_KEYWORDS:
                cached[key] = parse_doc_sections(cached["_raw_nb_xml"], EXTRA_FIELD_KEYWORDS[key])
            else:
                cached[key] = ""
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

    cached["제품코드"] = barcode_key8(cached["_bar_code"]) or clean_whitespace(item_seq)
    cached["보관방법"] = item.get("STORAGE_METHOD", "")

    for key, field in EXTRA_DIRECT_FIELDS.items():
        cached["_raw_" + key] = clean_whitespace(item.get(field, ""))

    for key in wanted_extras:
        if key in EXTRA_DIRECT_FIELDS:
            cached[key] = cached.get("_raw_" + key, "")
        elif key in EXTRA_FIELD_KEYWORDS:
            cached[key] = parse_doc_sections(nb_xml, EXTRA_FIELD_KEYWORDS[key])
        else:
            cached[key] = ""

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


def render_resizable_wrapped_table(display_df, show_index=False, height=720, table_key="result"):
    table_df = display_df.reset_index() if show_index else display_df.reset_index(drop=True)
    if show_index:
        table_df = table_df.rename(columns={table_df.columns[0]: str(display_df.index.name or "항목")})
    headers = [str(column) for column in table_df.columns]
    long_columns = {"효능효과", "용법용량", "성분명", "이상반응", "상호작용", "금기사항", "원료약품및분량"}
    narrow_columns = {"약가", "제약사한글명", "약효분류"}

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
    if "허가제품명" in comparison.columns:
        names = comparison["허가제품명"].tolist()
        deduped_names = []
        name_counts = {}
        for name in names:
            if name in name_counts:
                name_counts[name] += 1
                deduped_names.append(f"{name} ({name_counts[name]})")
            else:
                name_counts[name] = 1
                deduped_names.append(name)
        comparison.index = deduped_names
        comparison = comparison.drop(columns=["허가제품명"])
    
    comparison_df = comparison.T
    comparison_df.index.name = "조회항목"
    return comparison_df


def lookup_selected(rows, mfds_key, hira_key, wanted_extras):
    cache_code = load_json_cache(CACHE_CODE_FILE)
    cache_name = load_json_cache(CACHE_NAME_FILE)
    cache_detail = load_json_cache(CACHE_DETAIL_FILE)
    cache_meft = load_json_cache(CACHE_MEFT_FILE)
    call_counter = {"hira": 0, "mfds": 0}
    errors = []
    output = []
    progress = st.progress(0, text="조회 중입니다…")
    for index, row in enumerate(rows, start=1):
        item_seq = row.get("ITEM_SEQ", "")
        item_name = clean_whitespace(row.get("ITEM_NAME", ""))
        entp_name = clean_whitespace(row.get("ENTP_NAME", ""))
        fetch_keys = list(dict.fromkeys(ALWAYS_FETCH_DETAIL_KEYS + wanted_extras))
        detail = fetch_detail(item_seq, mfds_key, call_counter, cache_detail, fetch_keys, errors)
        bar_code = detail.get("_bar_code", "")
        price, method = match_price(item_name, bar_code, hira_key, call_counter, cache_code, cache_name, errors)
        effect_classification = get_effect_classification(item_name, bar_code, hira_key, call_counter, cache_meft, errors)
        
        out_row = {
            "허가제품명": item_name,
            "제약사한글명": entp_name,
            "제품코드": detail.get("제품코드", barcode_key8(bar_code) or clean_whitespace(item_seq)),
            "약가": price,
            "약효분류": effect_classification,
            "주성분영문명": detail.get("주성분영문명", ""),
            "성분명": detail.get("성분명", ""),
            "효능효과": detail.get("효능효과", ""),
            "용법용량": detail.get("용법용량", ""),
            "보관방법": detail.get("보관방법", ""),
        }
        for key in wanted_extras:
            out_row[key] = detail.get(key, "")
        output.append(out_row)
        progress.progress(index / len(rows), text=f"조회 중: {index}/{len(rows)}")
    progress.empty()
    save_json_cache(CACHE_CODE_FILE, cache_code)
    save_json_cache(CACHE_NAME_FILE, cache_name)
    save_json_cache(CACHE_DETAIL_FILE, cache_detail)
    save_json_cache(CACHE_MEFT_FILE, cache_meft)
    return order_result_columns(pd.DataFrame(output)), errors


def check_dur(rows, mfds_key, dur_indices, cache_detail, call_counter, errors):
    result_rows = []
    seen_extra_cols = []
    seen_matches = set()
    for row in rows:
        item_seq = row.get("ITEM_SEQ", "")
        item_name = clean_whitespace(row.get("ITEM_NAME", ""))
        entp_name = clean_whitespace(row.get("ENTP_NAME", ""))
        detail = fetch_detail(item_seq, mfds_key, call_counter, cache_detail, [], errors)
        candidates = collect_dur_candidate_codes(item_seq, detail)
        if not candidates:
            continue
        for category in DUR_CATEGORIES:
            index = dur_indices.get(category, {})
            for lookup_key, match_source, raw_code in candidates:
                if lookup_key not in index:
                    continue
                for payload in index[lookup_key]:
                    row_dict = payload["row"]
                    dedupe_key = (
                        item_seq,
                        category,
                        payload.get("_dur_code_column", ""),
                        payload.get("_dur_code_value", ""),
                        payload.get("_dur_row_number", 0),
                    )
                    if dedupe_key in seen_matches:
                        continue
                    seen_matches.add(dedupe_key)
                    result_row = {
                        "허가제품명": item_name,
                        "제약사한글명": entp_name,
                        "DUR종류": category,
                        "매칭근거": match_source,
                        "매칭코드": raw_code,
                        "DUR코드열": payload.get("_dur_code_column", ""),
                    }
                    for column in DUR_EXTRA_COLUMNS.get(category, []):
                        value = row_dict.get(column, "")
                        result_row[column] = "" if pd.isna(value) else str(value)
                        if column not in seen_extra_cols:
                            seen_extra_cols.append(column)
                    result_rows.append(result_row)
    columns = ["허가제품명", "제약사한글명", "DUR종류", "매칭근거", "매칭코드", "DUR코드열"] + seen_extra_cols
    return pd.DataFrame(result_rows, columns=columns)


st.set_page_config(page_title="의약품 통합 조회", page_icon="💊", layout="wide")
st.title("💊 의약품 허가정보·약가 통합 조회")
st.caption("식약처 허가·상세정보와 심평원 약가를 결합해 조회합니다. 데이터의 기준일과 API 응답을 함께 확인하세요.")

with st.sidebar:
    st.header("설정")
    st.markdown("API 키는 코드에 저장하지 말고 아래 입력란 또는 Streamlit secrets를 사용하세요.")
    try:
        secret_mfds = st.secrets.get("MFDS_KEY", "")
        secret_hira = st.secrets.get("HIRA_KEY", "")
    except Exception:
        secret_mfds, secret_hira = "", ""
    mfds_key = st.text_input("식약처 인증키 (디코딩된 키)", value=secret_mfds, type="password")
    hira_key = st.text_input("심평원 인증키 (디코딩된 키)", value=secret_hira, type="password")
    if st.button("허가목록 캐시 새로고침"):
        st.cache_data.clear()
        for cache_path in (LIST_FILE, LIST_META_FILE, TEMP_FILE):
            if cache_path.exists():
                cache_path.unlink()
        st.rerun()
    st.caption("허가목록은 KST 기준 하루 1회만 자동 갱신합니다. API 키는 파일에 저장하지 않고 Streamlit Secrets/입력값으로만 재사용합니다.")
    st.divider()
    st.markdown("**저장 위치**")
    st.code(str(DATA_DIR), language="text")
    st.divider()
    st.markdown("**DUR 품목리스트 업로드**")
    st.caption("엑셀에 '제품코드'(또는 제품코드A/B, 약품코드) 열이 있어야 합니다. 매달 새 파일로 다시 올리면 그 종류만 갱신됩니다.")
    if "dur_indices" not in st.session_state:
        st.session_state.dur_indices = {}
    for category in DUR_CATEGORIES:
        uploaded = st.file_uploader(category, type=["xlsx", "xls", "xlsb"], key=f"dur_upload_{category}")
        if uploaded is not None:
            try:
                dur_df, header_row, dur_index, code_columns = parse_dur_excel_cached(uploaded.getvalue(), uploaded.name)
            except Exception as exc:
                st.error(f"[{category}] '{uploaded.name}' 읽기 실패: {exc}")
            else:
                if not code_columns:
                    st.warning(
                        f"[{category}] '{uploaded.name}'에서 제품코드/약품코드 열을 찾지 못했습니다. "
                        f"(헤더로 인식한 행: {header_row}, 전체 열: {list(dur_df.columns)})"
                    )
                else:
                    st.session_state.dur_indices[category] = dur_index
                    st.success(f"[{category}] {len(dur_df):,}행, 코드열 {code_columns}, 매칭 제품코드 {len(dur_index):,}종 적용됨")

cache_day = current_kst_date()
cache_fresh = list_cache_is_fresh()
if not cache_fresh and not mfds_key:
    st.warning("오늘 날짜의 허가목록 캐시가 없어 식약처 인증키가 필요합니다. 심평원 인증키는 실제 조회 시 필요합니다.")
    st.stop()
if not hira_key:
    st.info("검색목록은 열 수 있지만, 약가·상세정보 조회에는 심평원 인증키가 필요합니다.")

try:
    all_rows = load_permitted_drugs(mfds_key, str(DATA_DIR), cache_day)
except Exception as exc:
    st.error(f"허가목록 수집에 실패했습니다: {exc}")
    st.exception(exc)
    st.stop()

normal_rows = [row for row in all_rows if row.get("CANCEL_NAME") == "정상"]
by_seq = {row.get("ITEM_SEQ", ""): row for row in normal_rows}
st.success(f"정상 품목 {len(normal_rows):,}건 준비 완료")

if "selection" not in st.session_state:
    st.session_state.selection = []
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "last_errors" not in st.session_state:
    st.session_state.last_errors = []

st.subheader("1. 의약품 검색")
query = st.text_input("의약품명 또는 제약사명", placeholder="예: 타이레놀, 한미약품")
matches = []
if query.strip():
    q = query.strip().casefold()
    matches = [row for row in normal_rows if q in row.get("ITEM_NAME", "").casefold() or q in row.get("ENTP_NAME", "").casefold()][:200]
    st.caption(f"검색결과 {len(matches)}건 표시 (최대 200건)")

if matches:
    search_df = pd.DataFrame([
        {"의약품명": row.get("ITEM_NAME", ""), "제약사": row.get("ENTP_NAME", ""), "품목코드": row.get("ITEM_SEQ", "")}
        for row in matches
    ])
    search_event = st.dataframe(
        search_df,
        use_container_width=True,
        hide_index=True,
        height=min(520, 36 + len(search_df) * 35),
        selection_mode="multi-row",
        on_select="rerun",
        key=f"search_results_table_{query.strip().casefold()}",
    )
    search_selected_seqs = [
        str(search_df.iloc[index]["품목코드"])
        for index in search_event.selection.rows
        if 0 <= index < len(search_df)
    ]
    st.caption(f"검색 결과에서 선택한 품목: **{len(search_selected_seqs)}건**")
    if st.button("선택한 검색 결과를 조회 목록에 추가", disabled=not search_selected_seqs, key="add_search_selection"):
        for seq in search_selected_seqs:
            if seq and seq not in st.session_state.selection:
                st.session_state.selection.append(seq)
        st.rerun()

st.subheader("2. 조회할 품목")
selected_rows = [by_seq[seq] for seq in st.session_state.selection if seq in by_seq]
if selected_rows:
    selected_df = pd.DataFrame([
        {"의약품명": row.get("ITEM_NAME", ""), "제약사": row.get("ENTP_NAME", ""), "품목코드": row.get("ITEM_SEQ", "")}
        for row in selected_rows
    ])
    st.caption("아래 표에서 제거할 행을 선택한 뒤 버튼을 누르세요.")
    selected_event = st.dataframe(
        selected_df,
        use_container_width=True,
        hide_index=True,
        height=min(360, 36 + len(selected_df) * 35),
        selection_mode="multi-row",
        on_select="rerun",
        key="selected_items_table",
    )
    if st.button("선택한 품목 제거", disabled=not selected_event.selection.rows):
        remove_seq = {str(selected_df.iloc[index]["품목코드"]) for index in selected_event.selection.rows}
        st.session_state.selection = [seq for seq in st.session_state.selection if seq not in remove_seq]
        st.rerun()
else:
    st.info("1번 검색 결과 표에서 조회할 행을 클릭하세요.")
st.write(f"현재 선택된 품목: **{len(st.session_state.selection)}건**")

st.subheader("3. 추가 조회 항목")
selected_extras = []
extra_columns = st.columns(3)
for index, key in enumerate(EXTRA_FIELD_ORDER):
    with extra_columns[index % 3]:
        if st.checkbox(EXTRA_FIELD_LABELS[key], key=f"extra_{key}"):
            selected_extras.append(key)

summary_view = st.checkbox(
    "요약 버전으로 보기",
    help="AI가 새로운 의학적 판단을 생성하지 않고, 원문에서 앞부분과 문장 단위 내용을 발췌해 짧게 표시합니다.",
)

if st.button("선택한 품목 조회", type="primary", disabled=not st.session_state.selection or not (mfds_key and hira_key)):
    selected_rows = [by_seq[seq] for seq in st.session_state.selection if seq in by_seq]
    with st.spinner("식약처 상세정보와 심평원 약가를 조회하는 중입니다…"):
        result_df, errors = lookup_selected(selected_rows, mfds_key, hira_key, selected_extras)
    st.session_state.last_result = result_df
    st.session_state.last_errors = errors
    st.rerun()

if st.session_state.last_result is not None:
    st.subheader("조회 결과")
    result_df = st.session_state.last_result
    filtered_result_df = result_df
    result_tab, comparison_tab, dur_tab = st.tabs(["상세 결과", "여러 약품 비교표", "DUR 확인"])
    with result_tab:
        transpose_view = st.checkbox(
            "행/열 전환", key="result_transpose", value=True,
            help="표시와 CSV 다운로드 모두 행/열을 전환합니다.",
        )
        displayed_df = make_display_df(filtered_result_df, summary_view=summary_view, transpose_view=transpose_view)
        if summary_view:
            st.caption("요약 버전: 원문에서 문장 단위로 발췌한 표시용 요약입니다.")
        render_resizable_wrapped_table(displayed_df, show_index=transpose_view, height=720, table_key="detail")
        csv_bytes = displayed_df.to_csv(index=transpose_view, encoding="utf-8-sig").encode("utf-8-sig")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_suffix = "_행열전환" if transpose_view else ""
        st.download_button("결과 CSV 다운로드", data=csv_bytes, file_name=f"의약품조회결과_{timestamp}{csv_suffix}.csv", mime="text/csv")
    with comparison_tab:
        if len(filtered_result_df) < 2:
            st.info("두 품목 이상 조회하면 비교표가 표시됩니다.")
        else:
            comparison_df = make_comparison_df(make_summary_df(filtered_result_df) if summary_view else filtered_result_df)
            st.caption("행은 조회 항목, 열은 의약품입니다. 헤더 경계를 드래그해 약품별 컬럼 너비를 조절할 수 있습니다.")
            render_resizable_wrapped_table(comparison_df, show_index=True, height=760, table_key="comparison")
            comparison_csv = comparison_df.to_csv(index=True, encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button("비교표 CSV 다운로드", data=comparison_csv, file_name=f"의약품비교표_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv")
    with dur_tab:
        if not st.session_state.dur_indices:
            st.info("사이드바의 'DUR 품목리스트 업로드'에서 먼저 엑셀을 올려주세요.")
        else:
            if st.button("선택한 품목 DUR 확인", key="run_dur_check"):
                dur_call_counter = {"hira": 0, "mfds": 0}
                dur_errors = []
                dur_cache_detail = load_json_cache(CACHE_DETAIL_FILE)
                with st.spinner("DUR(병용금기 등) 확인 중입니다…"):
                    dur_result_df = check_dur(
                        selected_rows, mfds_key, st.session_state.dur_indices,
                        dur_cache_detail, dur_call_counter, dur_errors,
                    )
                save_json_cache(CACHE_DETAIL_FILE, dur_cache_detail)
                st.session_state.dur_result = dur_result_df
                st.session_state.dur_errors = dur_errors
            if "dur_result" in st.session_state:
                dur_result_df = st.session_state.dur_result
                if dur_result_df.empty:
                    st.success("선택한 품목 중 업로드된 DUR 리스트에 해당하는 품목이 없습니다.")
                else:
                    st.dataframe(dur_result_df, use_container_width=True, hide_index=True)
                    dur_csv = dur_result_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                    st.download_button(
                        "DUR 확인 결과 CSV 다운로드", data=dur_csv,
                        file_name=f"DUR확인결과_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv",
                    )
                if st.session_state.get("dur_errors"):
                    with st.expander(f"DUR 확인 중 경고/오류 {len(st.session_state.dur_errors)}건"):
                        for error in st.session_state.dur_errors:
                            st.warning(error)

    if st.session_state.last_errors:
        with st.expander(f"API 경고/오류 {len(st.session_state.last_errors)}건"):
            for error in st.session_state.last_errors:
                st.warning(error)
