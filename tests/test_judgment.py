from app.services import judgment as J

NG_OK = {"content": "a", "cause": "b", "risk": "h", "action": "c", "owner": "d", "due": "2026-01-01", "status": "todo"}


def it(result, na="", ng=None, name="항목", iid=1):
    return {"id": iid, "name": name, "result": result, "na_reason": na, "ng": ng or {}}


def test_item_validity():
    assert not J.is_valid(it(None))
    assert J.is_valid(it("ok"))
    assert not J.is_valid(it("na"))
    assert J.is_valid(it("na", na="설비 없음"))
    assert not J.is_valid(it("ng", ng={"content": "x"}))
    assert J.is_valid(it("ng", ng=NG_OK))
    assert J.item_state(it("ng", ng={"content": "x"}))["label"] == "입력 미완료"
    assert J.item_state(it(None))["label"] == "미점검"


def test_counts_rate_excludes_na_and_pending():
    c = J.counts([it("ok"), it("ok"), it("ok"), it("ng", ng=NG_OK), it("na", na="x"), it(None)])
    assert (c["total"], c["ok"], c["ng"], c["na"], c["none"], c["valid"]) == (6, 3, 1, 1, 1, 5)
    assert c["rate"] == 75.0          # 적합 ÷ (적합 + 부적합)
    assert c["progress"] == 83.3      # 입력 완료 ÷ 전체


def test_rate_none_when_no_target():
    assert J.counts([])["rate"] is None
    assert J.counts([it("na", na="x")])["rate"] is None
    assert J.fmt_pct(None) == "산정 대상 없음"


def test_overdue():
    assert J.is_overdue({"due": "2026-01-01", "status": "todo"}, "2026-01-02")
    assert not J.is_overdue({"due": "2026-01-02", "status": "todo"}, "2026-01-02")
    assert not J.is_overdue({"due": "2026-01-01", "status": "done"}, "2026-01-02")
    assert not J.is_overdue({"due": "", "status": "todo"}, "2026-01-02")


def test_opinion_rules():
    info = {"place": "검수고", "insp_type": "일상점검"}
    good = J.generate_opinion(info, [it("ok")] * 20, set(), "2026-01-01")
    assert "양호한 것으로 판단" in good and "적합률은 100%" in good
    mid = J.generate_opinion(info, [it("ok")] * 9 + [it("na", na="x")], set(), "2026-01-01")
    assert "양호한 것으로" in mid
    ng = dict(NG_OK, due="2025-12-01")
    bad = J.generate_opinion(info, [it("ok"), it("ng", ng=ng, name="난간", iid=7)], {7}, "2026-01-01")
    assert "위험도 '상'" in bad and "예정일이 경과한" in bad and "미완료 개선조치 1건" in bad and "반복 지적" in bad
    assert "'양호' 판정을 보류" in bad
    assert "자동 생성한 초안" in bad
