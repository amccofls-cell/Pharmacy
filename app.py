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
# 식약처 상세 응답에서 실제 확인된 직접 필드와 NB_DOC_DATA 문서 섹션입니다.
# 사용자가 체크한 항목만 API 응답/캐시에서 결과로 펼칩니다.
EXTRA_FIELD_SPECS = {
    "소아_고령자투여": {"label": "소아·고령자 투여", "source": "NB_DOC_DATA", "keywords": ["소아에 대한 투여", "소아투여", "고령자에 대한 투여", "고령자투여"], "transform": "section"},
    "적용상의주의사항": {"label": "적용상의 주의사항", "source": "NB_DOC_DATA", "keywords": ["적용상의 주의", "적용상 주의"], "transform": "section"},
    "임부_수유부투여": {"label": "임부 및 수유부 투여", "source": "NB_DOC_DATA", "keywords": ["임부 및 수유부에 대한 투여", "임부에 대한 투여", "수유부에 대한 투여", "임부투여", "수유부투여"], "transform": "section"},
    "보관_취급주의사항": {"label": "보관 및 취급상의 주의사항", "source": "NB_DOC_DATA", "keywords": ["보관 및 취급상의 주의사항", "보관 및 취급상의 주의", "보관취급상의주의사항"], "transform": "section"},
    "금기사항": {"label": "금기사항", "source": "NB_DOC_DATA", "keywords": ["다음 환자에게는 투여하지 말 것", "투여하지 말 것", "금기"], "transform": "section"},
    "신중투여": {"label": "신중히 투여할 환자", "source": "NB_DOC_DATA", "keywords": ["다음 환자에는 신중히 투여할 것", "신중히 투여"], "transform": "section"},
    "이상반응": {"label": "이상반응", "source": "NB_DOC_DATA", "keywords": ["이상반응", "이상 반응"], "transform": "section"},
    "일반적주의": {"label": "일반적 주의", "source": "NB_DOC_DATA", "keywords": ["일반적 주의"], "transform": "section"},
    "상호작용": {"label": "상호작용", "source": "NB_DOC_DATA", "keywords": ["상호작용"], "transform": "section"},
    "과량투여처치": {"label": "과량투여시의 처치", "source": "NB_DOC_DATA", "keywords": ["과량투여시의 처치", "과량투여", "과량 투여"], "transform": "section"},
    "기타주의사항": {"label": "기타 사용상 주의사항", "source": "NB_DOC_DATA", "keywords": ["기타"], "transform": "section"},
    "위탁제조원": {"label": "위탁제조원", "source": "CNSGN_MANUF", "transform": "direct"},
    "전문일반구분": {"label": "전문·일반의약품 구분", "source": "ETC_OTC_CODE", "transform": "direct"},
    "성상": {"label": "성상", "source": "CHART", "transform": "direct"},
    "원료약품및분량": {"label": "원료약품 및 분량", "source": "MATERIAL_NAME", "transform": "direct"},
    "유효기간": {"label": "유효기간", "source": "VALID_TERM", "transform": "direct"},
    "포장단위": {"label": "포장단위", "source": "PACK_UNIT", "transform": "direct"},
    "품목허가종류": {"label": "품목허가 종류", "source": "PERMIT_KIND_NAME", "transform": "direct"},
    "제조수입구분": {"label": "제조·수입 구분", "source": "MAKE_MATERIAL_FLAG", "transform": "direct"},
    "업종": {"label": "업종", "source": "INDUTY_TYPE", "transform": "direct"},
    "변경일자": {"label": "변경일자", "source": "CHANGE_DATE", "transform": "direct"},
    "변경내용": {"label": "변경내용", "source": "GBN_NAME", "transform": "direct"},
    "ATC코드": {"label": "ATC 코드", "source": "ATC_CODE", "transform": "direct"},
    "영문제품명": {"label": "영문 제품명", "source": "ITEM_ENG_NAME", "transform": "direct"},
    "영문제조사명": {"label": "영문 제약사명", "source": "ENTP_ENG_NAME", "transform": "direct"},
    "주성분영문명": {"label": "주성분 영문명", "source": "MAIN_INGR_ENG", "transform": "direct"},
    "희귀의약품여부": {"label": "희귀의약품 여부", "source": "RARE_DRUG_YN", "transform": "direct"},
    "재심사대상": {"label": "재심사 대상", "source": "REEXAM_TARGET", "transform": "direct"},
    "재심사일자": {"label": "재심사 일자", "source": "REEXAM_DATE", "transform": "direct"},
    "허가일자": {"label": "허가일자", "source": "ITEM_PERMIT_DATE", "transform": "direct"},
    "허가취소일자": {"label": "허가취소일자", "source": "CANCEL_DATE", "transform": "direct"},
}
EXTRA_FIELD_ORDER = list(EXTRA_FIELD_SPECS)
EXTRA_FIELD_LABELS = {key: spec["label"] for key, spec in EXTRA_FIELD_SPECS.items()}
EXTRA_FIELD_KEYWORDS = {key: spec["keywords"] for key, spec in EXTRA_FIELD_SPECS.items() if "keywords" in spec}
EXTRA_DIRECT_FIELDS = {key: spec["source"] for key, spec in EXTRA_FIELD_SPECS.items() if spec["transform"] == "direct"}
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


def summarize_text(text, max_chars=420, max_sentences=3):
    """의학적 판단을 새로 생성하지 않고, 원문 앞부분과 핵심 문장만 발췌합니다."""
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
    """용법·용량에서 성인/소아/고령자 등 투여군별 문장을 우선 발췌합니다."""
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
    """용법·용량과 효능·효과를 짧게 표시하는 규칙 기반 요약본."""
    summary_df = result_df.copy()
    if "효능효과" in summary_df.columns:
        summary_df["효능효과"] = summary_df["효능효과"].map(lambda value: summarize_text(value))
    if "용법용량" in summary_df.columns:
        summary_df["용법용량"] = summary_df["용법용량"].map(lambda value: summarize_usage(value))
    for column in summary_df.columns:
        if column not in {"효능효과", "용법용량", "허가제품명", "제약사한글명", "제품코드", "약가"}:
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
        # 표시용 제품코드는 바코드 숫자에서 [3:11] 위치의 8자리로 생성합니다.
        # 바코드가 없거나 11자리보다 짧으면 원본 바코드(또는 빈 문자열)를 표시합니다.
        raw_barcode = clean_whitespace(row.get(FIELD_BAR_CODE, ""))
        # 바코드 매칭이 불가능하면 원래 품목코드로 되돌립니다.
        display_product_code = barcode_key8(raw_barcode) or clean_whitespace(row.get("ITEM_SEQ", ""))
        out_row = {"허가제품명": item_name, "제약사한글명": entp_name, "제품코드": display_product_code, "약가": price, "성분명": detail.get("성분명", ""), "효능효과": detail.get("효능효과", ""), "용법용량": detail.get("용법용량", "")}
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

# 검색 결과를 드롭다운이 아닌 전체 행이 보이는 선택 가능한 표로 표시합니다.
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
        # 검색어별로 위젯 상태를 분리해 첫 행이 자동 선택되지 않도록 합니다.
        key=f"search_results_table_{query.strip().casefold()}",
    )
    # selection.rows는 현재 검색표의 위치 인덱스이므로 반드시 iloc로 매핑합니다.
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
for key in EXTRA_FIELD_ORDER:
    if st.checkbox(EXTRA_FIELD_LABELS[key], key=f"extra_{key}"):
        selected_extras.append(key)

summary_view = st.checkbox(
    "요약 버전으로 보기",
    help="AI가 새로운 의학적 판단을 생성하지 않고, 원문에서 앞부분과 문장 단위 내용을 발췌해 짧게 표시합니다.",
)

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
    displayed_df = make_summary_df(result_df) if summary_view else result_df
    if summary_view:
        st.caption("요약 버전: 원문에서 문장 단위로 발췌한 표시용 요약입니다. 임상적 판단을 대신하지 않습니다.")
    st.dataframe(displayed_df, use_container_width=True, hide_index=True)
    csv_bytes = displayed_df.to_csv(index=False).encode("utf-8-sig")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    st.download_button("결과 CSV 다운로드", data=csv_bytes, file_name=f"의약품조회결과_{timestamp}.csv", mime="text/csv")
    if st.session_state.last_errors:
        with st.expander(f"API 경고/오류 {len(st.session_state.last_errors)}건"):
            for error in st.session_state.last_errors:
                st.warning(error)
