from urllib.parse import quote
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="DUR 통합 정보 조회", layout="wide")
st.title("💊 DUR 통합 정보 조회 서비스")

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


@st.cache_data(ttl=300)
def load_google_sheet_tab(doc_id, tab_name):
    """구글 시트 데이터를 로드합니다."""
    encoded_tab = quote(tab_name)
    url = f"https://docs.google.com/spreadsheets/d/{doc_id}/gviz/tq?tqx=out:csv&sheet={encoded_tab}"
    try:
        df = pd.read_csv(url)
        return df
    except Exception:
        return pd.DataFrame()


def fetch_hira_dur_by_name(endpoint, service_key, item_name):
    """품목명(itemName) 기반 심평원 DUR API 호출"""
    url = f"{HIRA_DUR_BASE_URL}{endpoint}"
    # itemSeq 대신 itemName 사용
    params = {"serviceKey": service_key, "type": "json", "itemName": item_name}
    try:
        res = requests.get(url, params=params, timeout=5).json()
        body = res.get("body") or res.get("response", {}).get("body", {})
        items = body.get("items", [])
        return items if isinstance(items, list) else [items]
    except Exception:
        return []


# 사용자 입력 (의약품명)
search_keyword = st.text_input(
    "조회할 의약품명을 입력하세요 (부분 단어 검색 가능)",
    placeholder="예: 타이레놀, 아스피린",
)

if st.button("DUR 통합 정보 조회", type="primary"):
    if not hira_service_key or not google_sheet_id:
        st.error("좌측 사이드바에 심평원 API 인증키와 구글 시트 ID를 입력해 주세요.")
    elif not search_keyword.strip():
        st.warning("조회할 의약품명을 입력해 주세요.")
    else:
        keyword = search_keyword.strip()
        results = []

        with st.spinner(f"'{keyword}' 검색 결과 통합 조회 중..."):
            # 1. 심평원 API 조회 (품목명 기준)
            for category, endpoint in API_ENDPOINTS.items():
                api_data = fetch_hira_dur_by_name(endpoint, hira_service_key, keyword)
                for item in api_data:
                    results.append(
                        {
                            "품목명": item.get("ITEM_NAME", keyword),
                            "품목코드": item.get("ITEM_SEQ", "-"),
                            "DUR 구분": category,
                            "금기/주의 내용": item.get("PROHBT_CONTENT")
                            or item.get("REMARK")
                            or item.get("TYPE_NAME", "내용 있음"),
                            "데이터 출처": "심평원 API",
                        }
                    )

            # 2. 구글 시트 조회 (품목명 부분 일치 검색)
            for category, tab_name in SHEET_TABS.items():
                sheet_df = load_google_sheet_tab(google_sheet_id, tab_name)
                if not sheet_df.empty and "품목명" in sheet_df.columns:
                    # 대소문자 구분 없이 입력한 키워드가 포함된 행 필터링
                    matched = sheet_df[
                        sheet_df["품목명"]
                        .astype(str)
                        .str.contains(keyword, case=False, na=False)
                    ]
                    for _, row in matched.iterrows():
                        results.append(
                            {
                                "품목명": row.get("품목명", keyword),
                                "품목코드": row.get("품목코드", "-"),
                                "DUR 구분": category,
                                "금기/주의 내용": row.get("금기/주의내용", "-"),
                                "데이터 출처": f"구글시트 ({tab_name})",
                            }
                        )

        # 결과 출력
        if results:
            result_df = pd.DataFrame(results)
            # 중복 결과 제거 (필요 시)
            result_df = result_df.drop_duplicates()
            st.success(f"총 {len(result_df)}건의 DUR 정보가 확인되었습니다.")
            st.dataframe(result_df, use_container_width=True)
        else:
            st.info(f"'{keyword}'에 대한 DUR 금기/주의 정보가 없습니다.")
