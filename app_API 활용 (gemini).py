from urllib.parse import quote
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="DUR 통합 정보 조회", layout="wide")
st.title("💊 DUR 통합 정보 다중 조회 서비스")

# 사이드바 설정
st.sidebar.header("⚙️ 서비스 설정")
hira_service_key = st.sidebar.text_input("심평원 API 인증키 (Encoding)", type="password")
google_sheet_id = st.sidebar.text_input("구글 스프레드시트 ID")

SHEET_TABS = {
    "수유부주의": "수유부주의",
    "비대면진료처방금지": "비대면진료처방금지",
    "비용효과적함량": "비용효과적함량",
}

HIRA_DUR_BASE_URL = "https://apis.data.go.kr/1471000/DURPrdlstInfoService03"
API_ENDPOINTS = {
    "병용금기": "/getUsjntTabooInfoList03",
    "연령금기": "/getSpcifyAgrdeTabooInfoList03",
    "효능군중복": "/getEfficacyGroupDuplInfoList03",
    "임부금기": "/getPwnmTabooInfoList03",
}

# ------------------------------------------------------------------
# 세션 상태(Session State) 초기화: 선택된 의약품 바구니
# ------------------------------------------------------------------
if "selected_drugs" not in st.session_state:
    st.session_state["selected_drugs"] = []


@st.cache_data(ttl=300)
def load_google_sheet_tab(doc_id, tab_name):
    """구글 시트 로드"""
    encoded_tab = quote(tab_name)
    url = f"https://docs.google.com/spreadsheets/d/{doc_id}/gviz/tq?tqx=out:csv&sheet={encoded_tab}"
    try:
        return pd.read_csv(url)
    except Exception:
        return pd.DataFrame()


def search_drug_candidates(keyword, service_key, sheet_id):
    """키워드가 포함된 의약품명 후보들을 API와 구글 시트에서 수집"""
    candidates = set()

    # 1. 심평원 API에서 검색 (병용금기 엔드포인트 등을 활용하여 품목명 검색)
    if service_key:
        try:
            url = f"{HIRA_DUR_BASE_URL}{API_ENDPOINTS['병용금기']}"
            params = {
                "serviceKey": service_key,
                "type": "json",
                "itemName": keyword,
            }
            res = requests.get(url, params=params, timeout=5).json()
            body = res.get("body") or res.get("response", {}).get("body", {})
            items = body.get("items", [])
            if not isinstance(items, list):
                items = [items]
            for item in items:
                if item.get("ITEM_NAME"):
                    candidates.add(item.get("ITEM_NAME"))
        except Exception:
            pass

    # 2. 구글 시트에서 검색
    if sheet_id:
        for _, tab_name in SHEET_TABS.items():
            sheet_df = load_google_sheet_tab(sheet_id, tab_name)
            if not sheet_df.empty and "품목명" in sheet_df.columns:
                matched = sheet_df[
                    sheet_df["품목명"]
                    .astype(str)
                    .str.contains(keyword, case=False, na=False)
                ]
                for name in matched["품목명"].dropna().unique():
                    candidates.add(str(name))

    return sorted(list(candidates))


def fetch_dur_for_item(item_name, service_key, sheet_id):
    """단일 의약품명에 대한 API + 구글시트 DUR 통합 조회"""
    results = []

    # API 조회
    for category, endpoint in API_ENDPOINTS.items():
        if not service_key:
            continue
        try:
            url = f"{HIRA_DUR_BASE_URL}{endpoint}"
            params = {
                "serviceKey": service_key,
                "type": "json",
                "itemName": item_name,
            }
            res = requests.get(url, params=params, timeout=5).json()
            body = res.get("body") or res.get("response", {}).get("body", {})
            items = body.get("items", [])
            if not isinstance(items, list):
                items = [items]

            for item in items:
                results.append(
                    {
                        "조회 의약품명": item_name,
                        "DUR 구분": category,
                        "금기/주의 내용": item.get("PROHBT_CONTENT")
                        or item.get("REMARK")
                        or item.get("TYPE_NAME", "내용 있음"),
                        "데이터 출처": "심평원 API",
                    }
                )
        except Exception:
            pass

    # 구글 시트 조회
    if sheet_id:
        for category, tab_name in SHEET_TABS.items():
            sheet_df = load_google_sheet_tab(sheet_id, tab_name)
            if not sheet_df.empty and "품목명" in sheet_df.columns:
                matched = sheet_df[
                    sheet_df["품목명"].astype(str).str.strip()
                    == item_name.strip()
                ]
                for _, row in matched.iterrows():
                    results.append(
                        {
                            "조회 의약품명": item_name,
                            "DUR 구분": category,
                            "금기/주의 내용": row.get("금기/주의내용", "-"),
                            "데이터 출처": f"구글시트 ({tab_name})",
                        }
                    )

    return results


# ------------------------------------------------------------------
# UI 화면 구성
# ------------------------------------------------------------------

# 1단계: 키워드 검색 및 후보 드롭다운 선택
st.subheader("1. 의약품 검색 및 후보 선택")
search_keyword = st.text_input(
    "검색할 의약품 키워드를 입력하세요", placeholder="예: 타이레놀"
)

if search_keyword.strip():
    with st.spinner(f"'{search_keyword}' 관련 의약품 목록 찾는 중..."):
        candidate_list = search_drug_candidates(
            search_keyword.strip(), hira_service_key, google_sheet_id
        )

    if candidate_list:
        selected_candidates = st.multiselect(
            "검색된 의약품 목록 중 조회할 항목을 선택하세요:",
            options=candidate_list,
            help="여러 개를 동시에 선택할 수 있습니다.",
        )

        if st.button("선택한 의약품 목록에 추가"):
            # 기존 목록에 중복 없이 추가
            new_items = [
                item
                for item in selected_candidates
                if item not in st.session_state["selected_drugs"]
            ]
            st.session_state["selected_drugs"].extend(new_items)
            st.success(f"{len(new_items)}개 의약품이 조회 목록에 추가되었습니다.")
    else:
        st.info("검색 조건에 맞는 의약품 후보가 없습니다.")

st.divider()

# 2단계: 최종 선택된 의약품 목록 확인 및 DUR 실행
st.subheader("2. 최종 조회 대상 목록")

if st.session_state["selected_drugs"]:
    # 드롭다운 형태로 목록 관리 (삭제 가능)
    updated_basket = st.multiselect(
        "현재 선택된 의약품 (X를 눌러 제거 가능):",
        options=st.session_state["selected_drugs"],
        default=st.session_state["selected_drugs"],
    )
    st.session_state["selected_drugs"] = updated_basket

    col1, col2 = st.columns([1, 4])
    with col1:
        run_search = st.button("DUR 통합 조회 실행", type="primary")
    with col2:
        if st.button("목록 전체 비우기"):
            st.session_state["selected_drugs"] = []
            st.rerun()

    # 3단계: 조회 결과 출력
    if run_search:
        all_results = []
        with st.spinner("선택된 의약품들의 DUR 정보를 가져오는 중..."):
            for drug_name in st.session_state["selected_drugs"]:
                res = fetch_dur_for_item(
                    drug_name, hira_service_key, google_sheet_id
                )
                all_results.extend(res)

        if all_results:
            df_result = pd.DataFrame(all_results).drop_duplicates()
            st.success(
                f"총 {len(st.session_state['selected_drugs'])}개 의약품에 대해 {len(df_result)}건의 DUR 정보가 조회되었습니다."
            )
            st.dataframe(df_result, use_container_width=True)
        else:
            st.warning("선택한 의약품에 대한 DUR 주의/금기 사항이 없습니다.")
else:
    st.info("1단계에서 의약품을 검색하고 목록에 추가해 주세요.")
