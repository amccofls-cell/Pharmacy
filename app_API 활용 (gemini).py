from urllib.parse import quote
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="DUR 통합 정보 다중 조회", layout="wide")
st.title("💊 DUR 통합 정보 다중 조회 서비스")

# 사이드바 설정
st.sidebar.header("⚙️ 서비스 설정")
hira_service_key = st.sidebar.text_input(
    "심평원 API 인증키 (Encoding)", type="password"
)
google_sheet_id = st.sidebar.text_input("구글 스프레드시트 ID")

SHEET_TABS = {
    "수유부주의": "수유부주의",
    "비대면진료처방금지": "비대면진료처방금지",
    "비용효과적함량": "비용효과적함량",
}

HIRA_DUR_BASE_URL = "https://apis.data.go.kr/1471000/DURPrdlstInfoService03"
MASTER_SEARCH_ENDPOINT = "/getDurPrdlstInfoList03"

API_ENDPOINTS = {
    "병용금기": "/getUsjntTabooInfoList03",
    "연령금기": "/getSpcifyAgrdeTabooInfoList03",
    "효능군중복": "/getEfficacyGroupDuplInfoList03",
    "임부금기": "/getPwnmTabooInfoList03",
}

# 세션 상태 초기화 (선택된 의약품 바구니)
if "selected_basket" not in st.session_state:
    st.session_state["selected_basket"] = {}


@st.cache_data(ttl=300)
def load_google_sheet_tab(doc_id, tab_name):
    """구글 시트 로드 및 품목코드 규격화"""
    encoded_tab = quote(tab_name)
    url = f"https://docs.google.com/spreadsheets/d/{doc_id}/gviz/tq?tqx=out:csv&sheet={encoded_tab}"
    try:
        df = pd.read_csv(url)
        if "품목코드" in df.columns:
            df["품목코드"] = df["품목코드"].astype(str).str.strip()
        return df
    except Exception:
        return pd.DataFrame()


def search_drug_candidates(keyword, service_key, sheet_id):
    """키워드(부분 단어)로 품목코드와 품목명을 매칭하여 후보 목록 반환"""
    candidates = {}

    # 1. 심평원 DUR Master 품목 검색 API
    if service_key:
        try:
            url = f"{HIRA_DUR_BASE_URL}{MASTER_SEARCH_ENDPOINT}"
            params = {
                "serviceKey": service_key,
                "type": "json",
                "itemName": keyword,
                "numOfRows": "50",
            }
            res = requests.get(url, params=params, timeout=5).json()
            body = res.get("body") or res.get("response", {}).get("body", {})
            items = body.get("items", [])
            if isinstance(items, dict):
                items = [items]

            for item in items:
                code = str(item.get("ITEM_SEQ", "")).strip()
                name = str(item.get("ITEM_NAME", "")).strip()
                if code and name:
                    label = f"[{code}] {name}"
                    candidates[label] = {"code": code, "name": name}
        except Exception:
            pass

    # 2. 구글 시트에서 품목명 부분 일치 검색
    if sheet_id:
        for _, tab_name in SHEET_TABS.items():
            sheet_df = load_google_sheet_tab(sheet_id, tab_name)
            if (
                not sheet_df.empty
                and "품목명" in sheet_df.columns
                and "품목코드" in sheet_df.columns
            ):
                matched = sheet_df[
                    sheet_df["품목명"]
                    .astype(str)
                    .str.contains(keyword, case=False, na=False)
                ]
                for _, row in matched.iterrows():
                    code = str(row.get("품목코드", "")).strip()
                    name = str(row.get("품목명", "")).strip()
                    if code and name:
                        label = f"[{code}] {name}"
                        candidates[label] = {"code": code, "name": name}

    return candidates


def fetch_dur_by_code(item_code, item_name, service_key, sheet_id):
    """품목코드(itemSeq) 기준으로 API 및 구글시트 DUR 통합 조회"""
    results = []

    # 1. 심평원 API 조회
    if service_key:
        for category, endpoint in API_ENDPOINTS.items():
            try:
                url = f"{HIRA_DUR_BASE_URL}{endpoint}"
                params = {
                    "serviceKey": service_key,
                    "type": "json",
                    "itemSeq": item_code,
                }
                res = requests.get(url, params=params, timeout=5).json()
                body = res.get("body") or res.get("response", {}).get("body", {})
                items = body.get("items", [])
                if isinstance(items, dict):
                    items = [items]

                for item in items:
                    results.append(
                        {
                            "품목코드": item_code,
                            "품목명": item_name,
                            "DUR 구분": category,
                            "금기/주의 내용": item.get("PROHBT_CONTENT")
                            or item.get("REMARK")
                            or item.get("TYPE_NAME", "내용 있음"),
                            "데이터 출처": "심평원 API",
                        }
                    )
            except Exception:
                pass

    # 2. 구글 시트 조회
    if sheet_id:
        for category, tab_name in SHEET_TABS.items():
            sheet_df = load_google_sheet_tab(sheet_id, tab_name)
            if not sheet_df.empty and "품목코드" in sheet_df.columns:
                matched = sheet_df[sheet_df["품목코드"] == str(item_code)]
                for _, row in matched.iterrows():
                    results.append(
                        {
                            "품목코드": item_code,
                            "품목명": item_name,
                            "DUR 구분": category,
                            "금기/주의 내용": row.get("금기/주의내용", "-"),
                            "데이터 출처": f"구글시트 ({tab_name})",
                        }
                    )

    return results


# ------------------------------------------------------------------
# UI 구성
# ------------------------------------------------------------------

# 1단계: 검색 및 즉시 펼쳐지는 체크박스 목록
st.subheader("1. 의약품 검색 및 목록 담기")
search_keyword = st.text_input(
    "의약품명의 일부를 입력하세요", placeholder="예: 타이레놀"
)

if search_keyword.strip():
    with st.spinner(f"'{search_keyword}' 검색 중..."):
        candidates = search_drug_candidates(
            search_keyword.strip(), hira_service_key, google_sheet_id
        )

    if candidates:
        st.write("📋 **검색 결과 (조회할 항목을 아래에서 바로 체크하세요):**")

        selected_labels = []
        # 스크롤 가능한 고정 높이 상자 안에서 목록이 드롭다운 클릭 없이 바로 펼쳐집니다.
        with st.container(height=250):
            for label, info in candidates.items():
                is_already_in = label in st.session_state["selected_basket"]
                # 고유 Key 생성으로 충돌 방지
                chk_key = f"chk_{info['code']}_{hash(label)}"
                if st.checkbox(label, value=is_already_in, key=chk_key):
                    selected_labels.append(label)

        if st.button("선택한 의약품을 바구니에 담기"):
            added_count = 0
            for label in selected_labels:
                if label not in st.session_state["selected_basket"]:
                    st.session_state["selected_basket"][label] = candidates[
                        label
                    ]
                    added_count += 1
            st.success(f"{added_count}개 의약품이 바구니에 추가되었습니다.")
    else:
        st.warning(
            "검색 결과가 없습니다. API 인증키, 구글 시트 ID, 키워드를 확인해 주세요."
        )

st.divider()

# 2단계: 담긴 의약품 바구니 확인 및 일괄 조회
st.subheader("2. 선택된 의약품 바구니 (조회 대상)")
basket = st.session_state["selected_basket"]

if basket:
    current_labels = list(basket.keys())
    selected_in_basket = st.multiselect(
        "현재 담긴 의약품 목록 (제거하려면 X 버튼 클릭):",
        options=current_labels,
        default=current_labels,
    )

    # 바구니 실시간 동기화
    st.session_state["selected_basket"] = {
        k: basket[k] for k in selected_in_basket if k in basket
    }

    col1, col2 = st.columns([1, 4])
    with col1:
        run_btn = st.button("DUR 통합 조회 실행", type="primary")
    with col2:
        if st.button("바구니 비우기"):
            st.session_state["selected_basket"] = {}
            st.rerun()

    # 3단계: 품목코드 기준 일괄 조회 수행
    if run_btn:
        all_results = []
        with st.spinner("선택한 품목코드들의 DUR 정보를 가져오는 중..."):
            for label, info in st.session_state["selected_basket"].items():
                res = fetch_dur_by_code(
                    info["code"],
                    info["name"],
                    hira_service_key,
                    google_sheet_id,
                )
                all_results.extend(res)

        if all_results:
            res_df = pd.DataFrame(all_results).drop_duplicates()
            st.success(
                f"총 {len(st.session_state['selected_basket'])}개 품목에 대해 {len(res_df)}건의 DUR 정보 조회가 완료되었습니다."
            )
            st.dataframe(res_df, use_container_width=True)
        else:
            st.info("선택한 품목코드들에 해당하는 DUR 금기/주의 정보가 없습니다.")
else:
    st.info("상단에서 검색어 입력 후 의약품을 선택하여 바구니에 담아주세요.")
