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
    cached["보관방법"] = clean_whitespace(item.get("STORAGE_METHOD", ""))

    for key, field in EXTRA_DIRECT_FIELDS.items():
        cached["_raw_" + key] = clean_whitespace(item.get(field, ""))

    # 안전하게 키워드 존재 여부 확인 후 파싱
    for key in wanted_extras:
        if key in EXTRA_DIRECT_FIELDS:
            cached[key] = cached.get("_raw_" + key, "")
        elif key in EXTRA_FIELD_KEYWORDS:
            cached[key] = parse_doc_sections(nb_xml, EXTRA_FIELD_KEYWORDS[key])
        else:
            cached[key] = ""

    cache_detail[item_seq] = cached
    return cached
