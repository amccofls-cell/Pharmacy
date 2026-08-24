from urllib.parse import quote
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="DUR 통합 정보 다중 조회",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 눈이 편안한 커스텀 스타일 (강렬한 빨간색 제거 및 소프트 톤 설정)
st.markdown(
    """
    <style>
    /* 눈에 부담 없는 은은한 배경 */
    .stApp {
        background-color: #f9fbfd;
    }
    /* 경고/알림 상자의 자극적인 빨간색 제거 */
    .stAlert {
        background-color: #f1f3f5 !important;
        color: #212529 !important;
        border: 1px solid #dee2e6 !important;
    }
    /* 메인 버튼 스타일 강조 완화 */
    .stButton>button {
        border-radius: 6px;
    }
    </style>
""",
    unsafe_allow_html=True,
)

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

# 세션 상태 초기화
if "selected_basket" not in st.session_state:
    st.session_state["selected_basket"] = {}
if "last_selected_row" not in st.session_state:
    st.session_state["last_selected_row"] = None


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
    """키워드로 후보 목록 데이터프레임 생성"""
    candidates = []

    # 1. 심평원 DUR Master API
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
                    candidates.append({"품목코드": code, "품목명": name})
        except Exception:
            pass

    # 2. 구글 시트
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
                        candidates.append({"품목코드": code, "품목명": name})

    if candidates:
        return pd.DataFrame(candidates).drop_duplicates()
    return pd.DataFrame()


def fetch_dur_by_code(item_code, item_name, service_key, sheet_id):
    """품목코드 기준 DUR 통합 조회"""
    results = []

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

# 1단계: 검색 및 클릭으로 즉시 담기
st.subheader("1. 의약품 검색 및 선택")
search_keyword = st.text_input(
    "의약품명의 일부를 입력하세요", placeholder="예: 타이레놀"
)

if search_keyword.strip():
    with st.spinner(f"'{search_keyword}' 검색 중..."):
        cand_df = search_drug_candidates(
            search_keyword.strip(), hira_service_key, google_sheet_id
        )

    if not cand_df.empty:
        st.write("👉 **목록에서 원하는 의약품 행을 클릭하면 즉시 바구니에 담깁니다:**")

        # 클릭 이벤트 감지 지원 표
        event = st.dataframe(
            cand_df,
            on_select="rerun",
            selection_mode="single-row",
            use_container_width=True,
            hide_index=True,
            height=200,
        )

        selected_rows = event.selection.get("rows", [])
        if selected_rows:
            row_idx = selected_rows[0]
            # 연속 동일 클릭 중복 방지
            if st.session_state["last_selected_row"] != (
                search_keyword,
                row_idx,
            ):
                selected_item = cand_df.iloc[row_idx]
                code = str(selected_item["품목코드"])
                name = str(selected_item["품목명"])
                key_name = f"[{code}] {name}"

                st.session_state["selected_basket"][key_name] = {
                    "code": code,
                    "name": name,
                }
                st.session_state["last_selected_row"] = (
                    search_keyword,
                    row_idx,
                )
                st.success(f"'{name}' 의약품이 바구니에 담겼습니다.")
                st.rerun()
    else:
        st.info("검색 결과가 없습니다.")

st.divider()

# 2단계: 깔끔한 리스트 형태의 바구니
st.subheader("2. 선택된 의약품 바구니 (리스트)")
basket = st.session_state["selected_basket"]

if basket:
    st.caption("현재 담긴 의약품 목록입니다. (우측 ❌ 버튼을 눌러 삭제 가능)")

    keys_to_delete = []
    # 세로 리스트 형태로 출력
    for key, item_info in list(basket.items()):
        col_text, col_btn = st.columns([6, 1])
        with col_text:
            st.markdown(
                f"▪️ **[{item_info['code']}]** {item_info['name']}"
            )
        with col_btn:
            if st.button("❌ 삭제", key=f"del_{item_info['code']}"):
                keys_to_delete.append(key)

    if keys_to_delete:
        for k in keys_to_delete:
            del st.session_state["selected_basket"][k]
        st.rerun()

    st.write("")
    col_run, col_clear, _ = st.columns([2, 2, 6])
    with col_run:
        run_btn = st.button("⚡ DUR 통합 조회 실행", type="primary")
    with col_clear:
        if st.button("🗑️ 바구니 비우기"):
            st.session_state["selected_basket"] = {}
            st.session_state["last_selected_row"] = None
            st.rerun()

    # 3단계: 통합 조회 실행
    if run_btn:
        all_results = []
        with st.spinner("바구니의 의약품들에 대해 DUR 조회를 진행 중입니다..."):
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
                f"총 {len(st.session_state['selected_basket'])}개 품목에 대해 {len(res_df)}건의 DUR 정보가 조회되었습니다."
            )
            st.dataframe(res_df, use_container_width=True)
        else:
            st.info("선택한 품목들에 대한 DUR 금기/주의 정보가 없습니다.")
else:
    st.info("바구니가 비어있습니다. 상단에서 의약품을 검색한 뒤 목록의 행을 클릭해 주세요.")
