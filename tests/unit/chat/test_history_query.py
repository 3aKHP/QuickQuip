"""HistoryQueryService：同群隔离、有界扫描、keyset 分页、引用与游标
（#72 实施计划 §5/§11 的 A 线场景）。"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


from quickquip.chat.archive import ChatArchive
from quickquip.chat.history_query import (
    HistoryQueryService,
    HistorySession,
    QueryStatus,
)

G1 = "1000000000"
G2 = "1000000001"
BASE = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc).timestamp()


def _ts(minutes: float) -> float:
    return BASE + minutes * 60


def _make_service(tmp_path: Path, **kwargs) -> tuple[HistoryQueryService, ChatArchive]:
    archive = ChatArchive(tmp_path / "archive.db")
    return HistoryQueryService(archive, **kwargs), archive


def test_search_scoped_to_group_and_ref_round_trip(tmp_path: Path):
    service, archive = _make_service(tmp_path)
    archive.record(G1, "张三", "SQLite 锁的讨论", ts=_ts(0), user_id="1", message_id="m1")
    archive.record(G2, "李四", "SQLite 锁的讨论", ts=_ts(1), user_id="2", message_id="m1")
    session = HistorySession()

    out_g1 = service.search(G1, session, terms=["SQLite"], start_ts=_ts(-10), end_ts=_ts(10))
    out_g2 = service.search(G2, session, terms=["SQLite"], start_ts=_ts(-10), end_ts=_ts(10))
    assert out_g1.status is QueryStatus.OK and len(out_g1.hits) == 1
    assert out_g2.status is QueryStatus.OK and len(out_g2.hits) == 1
    assert out_g1.hits[0].sender_name == "张三"
    assert out_g2.hits[0].sender_name == "李四"

    ref_g2 = service.encode_ref(out_g2.hits[0].row_id)
    assert service.decode_ref(ref_g2) == out_g2.hits[0].row_id
    # 用 G2 的引用在 G1 上下文展开：统一拒绝，不区分"不存在/跨群/已撤回"
    anchor_out = service.read_anchor(G1, session, ref=ref_g2)
    assert anchor_out.status is QueryStatus.INVALID_REQUEST
    assert anchor_out.detail == "anchor_unavailable"


def test_search_empty_and_unavailable_distinguished(tmp_path: Path):
    service, archive = _make_service(tmp_path)
    session = HistorySession()

    empty = service.search(G1, session, terms=["任意"], start_ts=_ts(-10), end_ts=_ts(10))
    assert empty.status is QueryStatus.EMPTY
    assert empty.coverage is not None and empty.coverage.total_messages == 0

    archive.record(G1, "张三", "不匹配内容", ts=_ts(0), user_id="1", message_id="m1")
    no_hit = service.search(G1, session, terms=["不存在词"], start_ts=_ts(-10), end_ts=_ts(10))
    # LIKE 预筛是精确超集：窗口扫完且无候选 → EMPTY 具备全窗口语义
    assert no_hit.status is QueryStatus.EMPTY
    assert no_hit.scanned_rows == 0  # 非匹配行根本不会成为候选

    # 数据库不可用：与"无结果"显式区分
    def _broken():
        return None

    original = archive.query_connection
    archive.query_connection = _broken  # type: ignore[method-assign]
    try:
        unavailable = service.search(
            G1, session, terms=["任意"], start_ts=_ts(-10), end_ts=_ts(10)
        )
    finally:
        archive.query_connection = original  # type: ignore[method-assign]
    assert unavailable.status is QueryStatus.UNAVAILABLE


def test_page_cap_paging_and_forced_scan_cap(tmp_path: Path):
    """LIKE 预筛精确时扫描帽极少自然触发；用小批次强制走多批路径，
    验证 keyset 续页不重不漏、触帽返回可续 partial/OK、最终候选耗尽。"""
    service, archive = _make_service(tmp_path, batch_rows=1, scan_row_cap=2)
    for i in range(5):
        archive.record(G1, "张三", f"刷屏{i}", ts=_ts(i), user_id="1", message_id=f"p{i}")
    session = HistorySession()

    # 扫描帽 2 + 批 1：每调用最多交付 2 条命中
    first = service.search(
        G1, session, terms=["刷屏"], start_ts=_ts(-5), end_ts=_ts(10), max_hits=5
    )
    assert first.status is QueryStatus.OK
    assert first.scanned_rows == 2
    assert first.stop_reason == "scan_cap"
    assert first.has_more and first.cursor_token
    assert [h.text for h in first.hits] == ["刷屏4", "刷屏3"]

    seen = [h.text for h in first.hits]
    outcome = first
    while outcome.cursor_token:
        outcome = service.search_continue(G1, session, cursor_token=outcome.cursor_token)
        seen.extend(h.text for h in outcome.hits)
    # 新→旧全量交付，无重复、无遗漏；最后一轮候选耗尽
    assert seen == ["刷屏4", "刷屏3", "刷屏2", "刷屏1", "刷屏0"]
    assert not outcome.has_more and outcome.cursor_token is None

    # 无命中 + 扫描帽触顶（预筛后仍有候选）→ partial，不得谎称全库无结果
    partial_service, partial_archive = _make_service(tmp_path / "sub", batch_rows=1, scan_row_cap=1)
    for i in range(3):
        partial_archive.record(G1, "李四", f"别的{i}", ts=_ts(i), user_id="2", message_id=f"q{i}")
    partial_out = partial_service.search(
        G1, HistorySession(), terms=["别的", "不存在"], start_ts=_ts(-5), end_ts=_ts(10), max_hits=5
    )
    assert partial_out.status is QueryStatus.OK  # "别的"命中即交付
    assert partial_out.has_more  # 帽内未扫尽 → 可续


def test_page_cap_and_keyset_no_dup_no_miss(tmp_path: Path):
    service, archive = _make_service(tmp_path, batch_rows=3)
    # 同一秒多条 + 跨秒多条，检验 (ts,id) keyset 稳定性
    for i in range(9):
        archive.record(G1, "张三", f"刷屏消息{i}", ts=_ts(i // 3), user_id="1", message_id=f"d{i}")
    session = HistorySession()

    seen: list[int] = []
    outcome = service.search(
        G1, session, terms=["刷屏"], start_ts=_ts(-5), end_ts=_ts(10), max_hits=4
    )
    assert outcome.status is QueryStatus.OK and outcome.stop_reason == "page_cap"
    seen.extend(h.row_id for h in outcome.hits)
    while outcome.cursor_token:
        outcome = service.search_continue(G1, session, cursor_token=outcome.cursor_token)
        seen.extend(h.row_id for h in outcome.hits)
    assert len(seen) == 9 and len(set(seen)) == 9  # 无重复、无遗漏


def test_snapshot_freezes_new_messages_mid_search(tmp_path: Path):
    service, archive = _make_service(tmp_path, batch_rows=1, scan_row_cap=1)
    archive.record(G1, "张三", "早期内容", ts=_ts(0), user_id="1", message_id="a1")
    session = HistorySession()

    first = service.search(G1, session, terms=["内容"], start_ts=_ts(-5), end_ts=_ts(10))
    assert first.status is QueryStatus.OK and first.stop_reason == "scan_cap"
    assert [h.text for h in first.hits] == ["早期内容"]
    # 翻页间隙新增消息：续页受首查快照约束，不可见
    archive.record(G1, "李四", "晚到内容", ts=_ts(99), user_id="2", message_id="a2")
    second = service.search_continue(G1, session, cursor_token=first.cursor_token)
    assert second.status is QueryStatus.EMPTY  # 快照内候选已扫尽
    assert second.hits == []
    # 全新搜索建立新快照，可见新消息（仍受扫描帽约束，跟游标读完）
    fresh = service.search(G1, session, terms=["内容"], start_ts=_ts(-5), end_ts=_ts(100))
    fresh_hits = [h.text for h in fresh.hits]
    while fresh.cursor_token:
        fresh = service.search_continue(G1, session, cursor_token=fresh.cursor_token)
        fresh_hits.extend(h.text for h in fresh.hits)
    assert fresh_hits == ["晚到内容", "早期内容"]


def test_term_matching_variants_and_like_wildcard_escape(tmp_path: Path):
    service, archive = _make_service(tmp_path)
    archive.record(G1, "A", "STRASSE 啤酒", ts=_ts(0), user_id="1", message_id="w1")
    archive.record(G1, "B", "Straße 面包", ts=_ts(1), user_id="2", message_id="w2")
    archive.record(G1, "C", "进度 100% 完成", ts=_ts(2), user_id="3", message_id="w3")
    archive.record(G1, "D", "没有百分号", ts=_ts(3), user_id="4", message_id="w4")
    session = HistorySession()

    def _texts(term: str) -> list[str]:
        out = service.search(G1, session, terms=[term], start_ts=_ts(-5), end_ts=_ts(10))
        return [h.text for h in out.hits]

    # ASCII 大小写：LIKE 与 Python 判定同口径（strasse 命中 STRASSE）
    assert _texts("STRASSE") == ["STRASSE 啤酒"]
    # 变体含 casefold 形态：ß→ss 展开后可命中 ASCII 目标（两套判定一致）
    assert _texts("straße") == ["Straße 面包", "STRASSE 啤酒"]
    # LIKE 通配符按字面匹配： "%" 只命中含百分号的行
    assert _texts("%") == ["进度 100% 完成"]
    # 中文词项精确子串
    assert _texts("啤酒") == ["STRASSE 啤酒"]
    # 多词项任一命中
    assert _texts("面包") == ["Straße 面包"]


def test_search_validates_request(tmp_path: Path):
    service, _ = _make_service(tmp_path)
    session = HistorySession()
    assert service.search(
        G1, session, terms=[], start_ts=_ts(0), end_ts=_ts(10)
    ).detail == "empty_terms"
    assert service.search(
        G1, session, terms=["a", "b", "c", "d", "e", "f"], start_ts=_ts(0), end_ts=_ts(10)
    ).detail == "too_many_terms"
    assert service.search(
        G1, session, terms=["a"], start_ts=_ts(10), end_ts=_ts(0)
    ).detail == "bad_window"
    assert service.search(
        "not-a-number", session, terms=["a"], start_ts=_ts(0), end_ts=_ts(10)
    ).detail == "bad_group"
    assert service.search_continue(G1, session, cursor_token="nope").detail == "bad_cursor"


def test_cursor_rejected_across_groups_and_sessions(tmp_path: Path):
    service, archive = _make_service(tmp_path)
    archive.record(G1, "张三", "群里内容", ts=_ts(0), user_id="1", message_id="m1")
    archive.record(G1, "张三", "群里内容2", ts=_ts(1), user_id="1", message_id="m2")
    archive.record(G1, "张三", "群里内容3", ts=_ts(2), user_id="1", message_id="m3")
    archive.record(G1, "张三", "群里内容4", ts=_ts(3), user_id="1", message_id="m4")
    archive.record(G1, "张三", "群里内容5", ts=_ts(4), user_id="1", message_id="m5")
    session = HistorySession()
    first = service.search(
        G1, session, terms=["内容"], start_ts=_ts(-5), end_ts=_ts(10), max_hits=2
    )
    assert first.cursor_token

    # 复制到他群：拒绝（不区分"不存在/跨群"）
    stolen = service.search_continue(G2, session, cursor_token=first.cursor_token)
    assert stolen.status is QueryStatus.INVALID_REQUEST

    # 换一个会话：句柄不可解析
    other_session = HistorySession()
    stranger = service.search_continue(G1, other_session, cursor_token=first.cursor_token)
    assert stranger.status is QueryStatus.INVALID_REQUEST


def test_read_continue_rejects_malformed_cursor_state(tmp_path: Path):
    """损坏/异 kind 游标状态统一 bad_cursor，不变成未处理异常（KHPilot）。"""
    service, archive = _make_service(tmp_path)
    archive.record(G1, "张三", "内容", ts=_ts(0), user_id="1", message_id="m1")
    session = HistorySession()

    # search 游标用于 read_continue：kind 不符 → bad_cursor
    search_out = service.search(G1, session, terms=["内容"], start_ts=_ts(-5), end_ts=_ts(10))
    assert service.read_continue(
        G1, session, cursor_token=search_out.cursor_token or "none"
    ).detail == "bad_cursor"

    # 缺 direction/last_key 的 read 状态 → bad_cursor 而非 KeyError
    broken = session.issue({"kind": "read", "group_id": G1})
    assert service.read_continue(G1, session, cursor_token=broken).detail == "bad_cursor"
    keyless = session.issue({"kind": "read", "group_id": G1, "direction": "older"})
    assert service.read_continue(G1, session, cursor_token=keyless).detail == "bad_cursor"


def test_read_anchor_directions_and_radius(tmp_path: Path):
    service, archive = _make_service(tmp_path)
    for i in range(10):
        archive.record(
            G1, f"成员{i % 3}", f"消息{i}",
            ts=_ts(i), user_id=str(i % 3), message_id=f"r{i}",
        )
    archive.record(G2, "他群", "消息5", ts=_ts(5), user_id="9", message_id="x5")
    session = HistorySession()
    target = service.search(G1, session, terms=["消息5"], start_ts=_ts(-5), end_ts=_ts(60))
    ref = service.encode_ref(target.hits[0].row_id)

    around = service.read_anchor(G1, session, ref=ref, radius=2, max_messages=10, max_chars=10_000)
    assert [m.text for m in around.messages] == ["消息3", "消息4", "消息5", "消息6", "消息7"]
    assert around.stop_reason == "window_end" or around.older_cursor  # 更早侧未穷尽

    before = service.read_anchor(
        G1, session, ref=ref, direction="before", radius=2,
        max_messages=10, max_chars=10_000,
    )
    assert [m.text for m in before.messages] == ["消息3", "消息4", "消息5"]

    after = service.read_anchor(
        G1, session, ref=ref, direction="after", radius=2,
        max_messages=10, max_chars=10_000,
    )
    assert [m.text for m in after.messages] == ["消息5", "消息6", "消息7"]

    bad = service.read_anchor(G1, session, ref="hr1.deadbeef.999999")
    assert bad.status is QueryStatus.INVALID_REQUEST
    assert bad.detail == "bad_ref"


def test_read_range_and_message_cap_continuation(tmp_path: Path):
    service, archive = _make_service(tmp_path)
    for i in range(6):
        archive.record(G1, "张三", f"内容{i}", ts=_ts(i), user_id="1", message_id=f"c{i}")
    session = HistorySession()

    out = service.read_range(
        G1, session, start_ts=_ts(0), end_ts=_ts(10),
        max_messages=4, max_chars=10_000,
    )
    assert [m.text for m in out.messages] == ["内容0", "内容1", "内容2", "内容3"]
    assert out.stop_reason == "message_cap"
    assert out.newer_cursor and out.older_cursor is None

    rest = service.read_continue(G1, session, cursor_token=out.newer_cursor)
    assert [m.text for m in rest.messages] == ["内容4", "内容5"]
    assert rest.stop_reason == "window_end"
    assert rest.newer_cursor is None


def test_long_message_fragment_continuation(tmp_path: Path):
    service, archive = _make_service(tmp_path)
    long_text = "长" * 500
    archive.record(G1, "张三", long_text, ts=_ts(0), user_id="1", message_id="L1")
    archive.record(G1, "李四", "尾部短消息", ts=_ts(1), user_id="2", message_id="L2")
    session = HistorySession()

    out = service.read_range(
        G1, session, start_ts=_ts(0), end_ts=_ts(10),
        max_messages=5, max_chars=120,
    )
    # 首条保底推进：切片而非整条顺延/静默截断
    assert len(out.messages) == 1
    assert out.fragment is not None
    row_id, offset, total = out.fragment
    assert (row_id, offset, total) == (out.messages[0].row_id, 0, 500)
    assert out.stop_reason == "char_cap"
    assert len(out.messages[0].text) == 120

    # 片段续读：从剩余部分继续，不重复已交付内容（剩余仍超帽 → 再切一片）
    rest = service.read_continue(G1, session, cursor_token=out.newer_cursor)
    assert rest.messages[0].row_id == row_id
    assert rest.messages[0].text == long_text[120:240]
    assert rest.stop_reason == "char_cap"

    # 逐段读完整个长消息后能到达后续短消息
    final = rest
    guard = 0
    while final.newer_cursor and guard < 10:
        final = service.read_continue(G1, session, cursor_token=final.newer_cursor)
        guard += 1
    texts = [m.text for m in final.messages]
    assert "尾部短消息" in texts


def test_recall_sidecar_excludes_from_all_paths(tmp_path: Path):
    service, archive = _make_service(tmp_path)
    archive.record(G1, "张三", "撤回我", ts=_ts(0), user_id="1", message_id="rec1")
    archive.record(G1, "李四", "保留我", ts=_ts(1), user_id="2", message_id="keep1")
    # 同 message_id 在他群：G2 的不应受 G1 撤回影响
    archive.record(G2, "王五", "撤回我", ts=_ts(2), user_id="3", message_id="rec1")
    session = HistorySession()

    # 撤回先于任何查询：屏蔽
    assert archive.record_recall(G1, "rec1") is True
    assert archive.record_recall(G1, "rec1") is False  # 幂等
    search_out = service.search(G1, session, terms=["撤回"], start_ts=_ts(-5), end_ts=_ts(10))
    assert [h.text for h in search_out.hits] == []
    search_keep = service.search(G1, session, terms=["保留"], start_ts=_ts(-5), end_ts=_ts(10))
    assert [h.text for h in search_keep.hits] == ["保留我"]
    other_group = service.search(G2, session, terms=["撤回"], start_ts=_ts(-5), end_ts=_ts(10))
    assert [h.text for h in other_group.hits] == ["撤回我"]

    # 撤回先于消息入库：后到的消息同样被屏蔽
    archive.record_recall(G1, "late1")
    archive.record(G1, "赵六", "迟到但已撤回", ts=_ts(5), user_id="6", message_id="late1")
    late = service.search(G1, session, terms=["迟到"], start_ts=_ts(-5), end_ts=_ts(10))
    assert late.hits == []

    # 锚点/区间/交付前重查同样生效
    keep_ref_row = search_keep.hits[0].row_id
    # 既有消费者（read_window）不受旁表影响：归档本体保全量
    legacy_window = archive.read_window(G1, _ts(-5), _ts(10))
    assert "撤回我" in [m["text"] for m in legacy_window]
    anchor = service.read_anchor(
        G1, session, ref=service.encode_ref(keep_ref_row), radius=5, max_chars=10_000
    )
    assert "撤回我" not in [m.text for m in anchor.messages]
    # recalled_row_ids：按行 ID 复查（报告交付前用）
    rows_by_mid = {
        r["message_id"]: int(r["id"])
        for r in _raw_rows(archive, G1)
        if r["message_id"]
    }
    all_ids = list(rows_by_mid.values())
    assert service.recalled_row_ids(G1, all_ids) == {
        rows_by_mid["rec1"], rows_by_mid["late1"]
    }


def _raw_rows(archive: ChatArchive, group_id: str) -> list[sqlite3.Row]:
    conn = archive.query_connection()
    assert conn is not None
    try:
        return conn.execute(
            "SELECT id, message_id FROM archive_messages WHERE group_id = ? ORDER BY id",
            (group_id,),
        ).fetchall()
    finally:
        conn.close()


def test_legacy_rows_without_user_id_still_readable(tmp_path: Path):
    service, archive = _make_service(tmp_path)
    archive.record(G1, "旧显示名", "回灌消息", ts=_ts(0))  # 无 user_id/message_id
    session = HistorySession()
    out = service.search(G1, session, terms=["回灌"], start_ts=_ts(-5), end_ts=_ts(10))
    assert out.hits[0].user_id is None
    assert out.hits[0].sender_name == "旧显示名"
    assert out.hits[0].message_id is None


def test_speaker_filter_in_sql(tmp_path: Path):
    service, archive = _make_service(tmp_path)
    for i in range(4):
        archive.record(G1, f"人{i}", "同一句话", ts=_ts(i), user_id=str(i), message_id=f"s{i}")
    session = HistorySession()
    out = service.search(
        G1, session, terms=["同一句话"], start_ts=_ts(-5), end_ts=_ts(10),
        speaker_user_ids=["2"],
    )
    assert [h.user_id for h in out.hits] == ["2"]


def test_ref_invalid_on_archive_replacement(tmp_path: Path):
    service, archive = _make_service(tmp_path)
    archive.record(G1, "张三", "内容", ts=_ts(0), user_id="1", message_id="m1")
    session = HistorySession()
    hit = service.search(G1, session, terms=["内容"], start_ts=_ts(-5), end_ts=_ts(10))
    ref = service.encode_ref(hit.hits[0].row_id)
    assert service.decode_ref(ref) == hit.hits[0].row_id

    # 库替换：全新归档库 UUID 不同 → 旧引用明确失效（不是静默错读他行）
    replacement_archive = ChatArchive(tmp_path / "replacement.db")
    replacement_archive.record(G1, "李四", "别的库", ts=_ts(0), user_id="2", message_id="k1")
    assert replacement_archive.archive_uuid != archive.archive_uuid
    replacement_service = HistoryQueryService(replacement_archive)
    assert replacement_service.decode_ref(ref) is None


def test_additive_migration_on_existing_database(tmp_path: Path):
    # 模拟旧版代码创建的库：只有 archive_messages（无 meta/撤回表）
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archive_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT NOT NULL, ts REAL NOT NULL, user_id TEXT,
            sender_name TEXT NOT NULL, message_id TEXT, text TEXT NOT NULL,
            image_count INTEGER NOT NULL DEFAULT 0, image_urls TEXT,
            dedupe_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO archive_messages (group_id, ts, sender_name, text, dedupe_key, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (G1, BASE, "旧数据", "旧内容", "k1", "2026-08-01"),
    )
    conn.commit()
    conn.close()

    archive = ChatArchive(db_path)  # 附加式迁移
    assert archive.archive_uuid
    service = HistoryQueryService(archive)
    session = HistorySession()
    out = service.search(G1, session, terms=["旧内容"], start_ts=BASE - 1, end_ts=BASE + 1)
    assert out.status is QueryStatus.OK  # 旧数据可查
    assert archive.record_recall(G1, "anything") is True  # 旁表可用


def test_second_instance_shares_stamped_uuid(tmp_path: Path):
    """Bot 先启动、Web Admin 后启动（现实序列）：第二实例读到同一 UUID。
    并发首启动的 WAL PRAGMA 竞态是归档既有行为（失败实例按冷却自愈），
    附加式迁移不引入新的迁移竞态。"""
    db_path = tmp_path / "archive.db"
    first = ChatArchive(db_path)
    second = ChatArchive(db_path)
    assert first.archive_uuid and first.archive_uuid == second.archive_uuid


def test_range_continuation_respects_window_end(tmp_path):
    """R10：区间阅读续页不越出原窗口 end（排除行不进入次屏）。"""
    service, archive = _make_service(tmp_path)
    for i in range(6):
        archive.record(G1, "张三", f"行{i}", ts=_ts(i), user_id="1", message_id=f"w{i}")
    session = HistorySession()
    out = service.read_range(G1, session, start_ts=_ts(0), end_ts=_ts(4), max_messages=2, max_chars=10_000)
    assert [m.text for m in out.messages] == ["行0", "行1"]
    assert out.newer_cursor
    second = service.read_continue(G1, session, cursor_token=out.newer_cursor)
    # 次屏只含窗口内的 行2/行3；行4（end=4 排除）与之后的行都不出现
    assert [m.text for m in second.messages] == ["行2", "行3"]
    assert second.stop_reason == "window_end" or second.newer_cursor is None


def test_read_db_error_is_unavailable_not_empty(tmp_path, monkeypatch):
    """R13：读取路径数据库故障返回 UNAVAILABLE，不冒充空记录。"""
    import sqlite3 as _sqlite3
    service, archive = _make_service(tmp_path)
    archive.record(G1, "张三", "内容", ts=_ts(0), user_id="1", message_id="m1")

    from quickquip.chat.history_query import _QueryUnavailable

    def _broken(*a, **k):
        raise _QueryUnavailable("database is locked")

    monkeypatch.setattr(service, "_fetch_range", _broken)
    out = service.read_range(G1, HistorySession(), start_ts=_ts(-5), end_ts=_ts(10))
    assert out.status is QueryStatus.UNAVAILABLE
    assert out.detail == "database_error"
