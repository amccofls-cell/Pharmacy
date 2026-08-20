import csv
import io
import json
import os
import re
import time
import html as html_lib
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

# ─────────────────────────────────────────────────────────────
# 의약품 허가정보·약가 통합 조회 — Streamlit version
# 기존 Colab 노트북의 API 엔드포인트/필드명/매칭 규칙을 유지합니다.
# ─────────────────────────────────────────────────────────────
MFDS_LIST_URL = "http://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07/getDrugPrdtPrmsnInq07"
MFDS_DETAIL_URL = "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07/getDrugPrdtPrmsnDtlInq06"
HIRA_PRICE_URL = "https://apis.data.go.kr/B551182/dgamtCrtrInfoService1.2/getDgamtList"
FIELD_BAR_CODE = "BAR_CODE"
LIST_NUM_OF_ROWS = 500
HIRA_CALL_LIMIT = 600
MFDS_CALL_LIMIT = 1000
LIST_CSV_FIELDS = ["ITEM_SEQ", "ITEM_NAME", "ENTP_NAME", FIELD_BAR_CODE, "CANCEL_NAME", "ITEM_PERMIT_DATE"]
BASE_COLUMNS = ["허가제품명", "제약사한글명", "제품코드", "약가", "성분명", "효능효과", "용법용량"]
EXTRA_FIELD_ORDER = ["소아_고령자투여", "적용상의주의사항", "임부_수유부투여", "보관_취급주의사항", "저장방법"]
EXTRA_FIELD_LABELS = {
    "소아_고령자투여": "소아·고령자 투여",
    "적용상의주의사항": "적용상의 주의사항",
    "임부_수유부투여": "임부 및 수유부 투여",
    "보관_취급주의사항": "보관 및 취급상의 주의사항",
    "저장방법": "저장방법",
}
EXTRA_FIELD_KEYWORDS = {
    "소아_고령자투여": ["소아에 대한 투여", "소아투여", "고령자에 대한 투여", "고령자투여"],
    "적용상의주의사항": ["적용상의 주의", "적용상 주의"],
    "임부_수유부투여": ["임부 및 수유부에 대한 투여", "임부에 대한 투여", "수유부에 대한 투여", "임부투여", "수유부투여"],
    "보관_취급주의사항": ["보관 및 취급상의 주의사항", "보관 및 취급상의 주의", "보관취급상의주의사항"],
}
EXTRA_DIRECT_FIELDS = {"저장방법": "STORAGE_METHOD"}
HEADING_PATTERN = re.compile(r"^\s*\d+\s*[.\-]")
MAX_RETRY = 5

DATA_DIR = Path(os.environ.get("DRUG_APP_DATA_DIR", "."))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LIST_FILE = DATA_DIR / "허가목록_원본.csv"
TEMP_FILE = DATA_DIR / "허가목록_임시.json"
CACHE_CODE_FILE = DATA_DIR / "cache_약가_코드별.json"
CACHE_NAME_FILE = DATA_DIR / "cache_약가_이름별.json"
CACHE_DETAIL_FILE = DATA_DIR / "cache_상세정보.json"


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
    """중첩 XML에서 title에 특정 키워드가 포함된 상위 항목과 하위 내용 추출."""
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
    if not mds_cd:
        return None
    digits = re.sub(r"\D", "", str(mds_cd))
    return digits[:8] if len(digits) >= 8 else None


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


def fetch_detail(item_seq, service_key, call_counter, cache_detail, wanted_extras, errors):
    cached = cache_detail.get(item_seq, {})
    have_base = "성분명" in cached
    missing_extras = [key for key in wanted_extras if key not in cached]
    if have_base and not missing_extras:
        return cached
    if have_base and "_raw_nb_xml" in cached:
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
    cached["_raw_nb_xml"] = nb_xml
    for key, field in EXTRA_DIRECT_FIELDS.items():
        cached["_raw_" + key] = clean_whitespace(item.get(field, ""))
    for key in wanted_extras:
        cached[key] = cached.get("_raw_" + key, "") if key in EXTRA_DIRECT_FIELDS else parse_doc_sections(nb_xml, EXTRA_FIELD_KEYWORDS[key])
    cache_detail[item_seq] = cached
    return cached


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
def load_permitted_drugs(mfds_key, data_dir_string):
    list_file = Path(data_dir_string) / "허가목록_원본.csv"
    temp_file = Path(data_dir_string) / "허가목록_임시.json"
    if list_file.exists():
        with list_file.open("r", encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        return rows
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
    return all_rows


def lookup_selected(rows, mfds_key, hira_key, wanted_extras):
    cache_code = load_json_cache(CACHE_CODE_FILE)
    cache_name = load_json_cache(CACHE_NAME_FILE)
    cache_detail = load_json_cache(CACHE_DETAIL_FILE)
    call_counter = {"hira": 0, "mfds": 0}
    errors = []
    columns = BASE_COLUMNS + wanted_extras
    output = []
    progress = st.progress(0, text="조회 중입니다…")
    for index, row in enumerate(rows, start=1):
        item_seq = row.get("ITEM_SEQ", "")
        item_name = clean_whitespace(row.get("ITEM_NAME", ""))
        entp_name = clean_whitespace(row.get("ENTP_NAME", ""))
        price, method = match_price(item_name, row.get(FIELD_BAR_CODE, ""), hira_key, call_counter, cache_code, cache_name, errors)
        detail = fetch_detail(item_seq, mfds_key, call_counter, cache_detail, wanted_extras, errors)
        out_row = {"허가제품명": item_name, "제약사한글명": entp_name, "제품코드": item_seq, "약가": price, "성분명": detail.get("성분명", ""), "효능효과": detail.get("효능효과", ""), "용법용량": detail.get("용법용량", ""), "약가조회방법": method}
        for key in wanted_extras:
            out_row[key] = detail.get(key, "")
        output.append(out_row)
        progress.progress(index / len(rows), text=f"조회 중: {index}/{len(rows)}")
    progress.empty()
    save_json_cache(CACHE_CODE_FILE, cache_code)
    save_json_cache(CACHE_NAME_FILE, cache_name)
    save_json_cache(CACHE_DETAIL_FILE, cache_detail)
    return pd.DataFrame(output), errors


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
        if LIST_FILE.exists():
            LIST_FILE.unlink()
        st.rerun()
    st.divider()
    st.markdown("**저장 위치**")
    st.code(str(DATA_DIR), language="text")

if not mfds_key or not hira_key:
    st.info("사이드바에 식약처와 심평원 인증키를 입력하면 조회를 시작할 수 있습니다.")
    st.stop()

try:
    all_rows = load_permitted_drugs(mfds_key, str(DATA_DIR))
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

match_options = {f"{row.get('ITEM_NAME','')} | {row.get('ENTP_NAME','')} | {row.get('ITEM_SEQ','')}": row.get("ITEM_SEQ", "") for row in matches}
selected_from_search = st.multiselect("검색 결과에서 품목 선택", list(match_options.keys()))
if st.button("선택 목록에 추가", disabled=not selected_from_search):
    for label in selected_from_search:
        seq = match_options[label]
        if seq and seq not in st.session_state.selection:
            st.session_state.selection.append(seq)
    st.rerun()

st.subheader("2. 조회할 품목")
selected_labels = [f"{by_seq[seq].get('ITEM_NAME','')} | {by_seq[seq].get('ENTP_NAME','')} | {seq}" for seq in st.session_state.selection if seq in by_seq]
removed_labels = st.multiselect("선택 목록에서 제거할 품목", selected_labels)
if st.button("선택 목록에서 제거", disabled=not removed_labels):
    removed_seq = {label.rsplit(" | ", 1)[-1] for label in removed_labels}
    st.session_state.selection = [seq for seq in st.session_state.selection if seq not in removed_seq]
    st.rerun()
st.write(f"현재 선택된 품목: **{len(st.session_state.selection)}건**")

st.subheader("3. 추가 조회 항목")
selected_extras = []
for key in EXTRA_FIELD_ORDER:
    if st.checkbox(EXTRA_FIELD_LABELS[key], key=f"extra_{key}"):
        selected_extras.append(key)

if st.button("선택한 품목 조회", type="primary", disabled=not st.session_state.selection):
    selected_rows = [by_seq[seq] for seq in st.session_state.selection if seq in by_seq]
    with st.spinner("식약처 상세정보와 심평원 약가를 조회하는 중입니다…"):
        result_df, errors = lookup_selected(selected_rows, mfds_key, hira_key, selected_extras)
    st.session_state.last_result = result_df
    st.session_state.last_errors = errors
    st.rerun()

if st.session_state.last_result is not None:
    st.subheader("조회 결과")
    result_df = st.session_state.last_result
    st.dataframe(result_df, use_container_width=True, hide_index=True)
    csv_bytes = result_df.to_csv(index=False).encode("utf-8-sig")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    st.download_button("결과 CSV 다운로드", data=csv_bytes, file_name=f"의약품조회결과_{timestamp}.csv", mime="text/csv")
    if st.session_state.last_errors:
        with st.expander(f"API 경고/오류 {len(st.session_state.last_errors)}건"):
            for error in st.session_state.last_errors:
                st.warning(error)
