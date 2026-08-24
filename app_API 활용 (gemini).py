from urllib.parse import quote
import pandas as pd
import requests
import streamlit as st

# 페이지 기본 설정
st.set_page_config(page_title="DUR 통합 정보 조회", layout="wide")
st.title("💊 DUR 통합 정보 조회 서비스")

# 사이드바: 인증키 및 시트 ID 입력
st.sidebar.header("⚙️ 서비스 설정")
hira_service_key = st.sidebar.text_input("심평원 API 인증키 (Encoding)", type="password")
google_sheet_id = st.sidebar.text_input("구글 스프레드시트 ID")

# 구글 시트 탭 매핑 설정
SHEET_TABS = {
    "수유부주의": "수유부주의",
    "비대면진료처방금지": "비대면진료처방금지",
    "비용효과적함량": "비용효과적함량",
}

# 심평원 API 엔드포인트
HIRA_DUR_BASE_URL = "https://apis.data.go.kr/1471000/DURPrdlstInfoService03"
API_ENDPOINTS = {
    "병용금기": "/getUsjntTabooInfoList03",
    "연령금기": "/getSpcifyAgrdeTabooInfoList03",
    "효능군중복": "/getEfficacyGroupDuplInfoList03",
    "임부금기": "/getPwnmTabooInfoList03",
}


@st.cache_data(ttl=300)
def load_google_sheet_tab(doc_id, tab_name):
    """구글 시트의 특정 탭 데이터를 읽어옵니다."""
    encoded_tab = quote(tab_name)
    url = f"https://docs.google.com/spreadsheets/d/{doc_id}/gviz/tq?tqx=out:csv&sheet={encoded_tab}"
    try:
        df = pd.read_csv(url)
        # 품목코드 컬럼 문자열 변환
        if "품목코드" in df.columns:
            df["품목코드"] = df["품목코드"].astype(str).str.strip()
        return df
    except Exception:
        return pd.DataFrame()


def fetch_hira_dur(endpoint, service_key, item_seq):
    """심평원 DUR API 호출 함수"""
    url = f"{HIRA_DUR_BASE_URL}{endpoint}"
    params = {"serviceKey": service_key, "type": "json", "itemSeq": item_seq}
    try:
        res = requests.get(url, params=params, timeout=5).json()
        body = res.get("body") or res.get("response", {}).get("body", {})
        items = body.get("items", [])
        return items if isinstance(items, list) else [items]
    except Exception:
        return []


# 메인 조회 화면
item_seq_input = st.text_input(
    "조회할 의약품 품목코드(ITEM_SEQ)를 입력하세요 (쉼표로 여러 개 입력 가능)",
    placeholder="예: 199900001, 200000002",
)

if st.button("DUR 통합 정보 조회", type="primary"):
    if not hira_service_key or not google_sheet_id:
        st.error("좌측 사이드바에 심평원 API 인증키와 구글 시트 ID를 입력해 주세요.")
    elif not item_seq_input:
        st.warning("조회할 품목코드를 입력해 주세요.")
    else:
        target_seqs = [s.strip() for s in item_seq_input.split(",") if s.strip()]
        results = []

        with st.spinner("API 및 구글 시트 데이터를 통합 조회 중입니다..."):
            for seq in target_seqs:
                # 1. 심평원 API 조회 (4개 카테고리)
                for category, endpoint in API_ENDPOINTS.items():
                    api_data = fetch_hira_dur(endpoint, hira_service_key, seq)
                    for item in api_data:
                        results.append(
                            {
                                "품목코드": seq,
                                "DUR 구분": category,
                                "금기/주의 내용": item.get("PROHBT_CONTENT")
                                or item.get("REMARK")
                                or item.get("TYPE_NAME", "내용 있음"),
                                "데이터 출처": "심평원 API",
                            }
                        )

                # 2. 구글 시트 탭별 조회 (3개 카테고리)
                for category, tab_name in SHEET_TABS.items():
                    sheet_df = load_google_sheet_tab(google_sheet_id, tab_name)
                    if not sheet_df.empty and "품목코드" in sheet_df.columns:
                        matched = sheet_df[sheet_df["품목코드"] == str(seq)]
                        for _, row in matched.iterrows():
                            results.append(
                                {
                                    "품목코드": seq,
                                    "DUR 구분": category,
                                    "금기/주의 내용": row.get("금기/주의내용", "-"),
                                    "데이터 출처": f"구글시트 ({tab_name})",
                                }
                            )

        # 결과 출력
        if results:
            result_df = pd.DataFrame(results)
            st.success(f"총 {len(result_df)}건의 DUR 정보가 확인되었습니다.")
            st.dataframe(result_df, use_container_width=True)
        else:
            st.info("해당 품목코드에 대한 DUR 금기/주의 정보가 없습니다.")
