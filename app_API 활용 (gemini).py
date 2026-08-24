# ------------------------------------------------------------------
# 1단계: 검색 및 즉시 클릭 가능한 체크박스 목록
# ------------------------------------------------------------------
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
        st.write("📋 **검색 결과 (원하는 품목을 바로 체크하세요):**")

        # 체크박스로 선택된 라벨들을 담을 리스트
        selected_labels = []

        # 드롭다운 없이 화면에 바로 체크박스로 항목들을 펼쳐줍니다.
        # 항목이 많을 경우를 대비해 스크롤 가능한 영역에 배치
        with st.container(height=250):
            for label in candidates.keys():
                # 이미 바구니에 있는 항목은 기본 선택 상태로 표시
                is_already_in = label in st.session_state["selected_basket"]
                if st.checkbox(
                    label,
                    value=is_already_in,
                    key=f"chk_{candidates[label]['code']}",
                ):
                    selected_labels.append(label)

        col_add, _ = st.columns([2, 5])
        with col_add:
            if st.button("선택한 의약품을 바구니에 담기", type="secondary"):
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
