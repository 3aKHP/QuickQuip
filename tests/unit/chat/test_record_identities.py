

from quickquip.common.record_content import legacy
from quickquip.chat.group_quotes import GroupQuoteStore
from quickquip.chat.offline_messages import OfflineMessageStore


from tests.fixtures.record_identities import snapshot as snapshot

def test_quote_pagination_mentions_and_author_separate(tmp_path, snapshot):
    store = GroupQuoteStore(tmp_path / "quotes.db")
    for i in range(7):
        store.add(
            "10001", "23456", "旧作者", str(i), "99999",
            content_parts=legacy(f"[CQ:at,qq=12345,name=旧名] {i}"),
        )
    store.add("10001", "12345", "旧作者", "没有提及", "99999")
    with store._db:
        store._db.execute(
            "UPDATE quotes SET content_parts_json=NULL, "
            "content='[CQ:at,qq=12345,name=旧名] 0' WHERE id=1"
        )
    rows, total = store.search("10001", "标准名", offset=2, limit=2)
    assert total == 7 and [r["id"] for r in rows] == [5, 4]
    assert all("@标准名" in r["content_display"] for r in rows)
    authors, total = store.search_by_sender("10001", user_ids=["12345"])
    assert total == 1 and authors[0]["content"] == "没有提及"
    store.delete(5)
    assert not store._db.execute("SELECT * FROM quotes_member_refs WHERE record_id=5").fetchall()
    store.close()


def test_offline_retains_mentions_and_plain_display(tmp_path, snapshot):
    store = OfflineMessageStore(tmp_path / "offline.db")
    store.add(
        "10001", "12345", "旧发送者", "23456", "",
        content_parts=legacy("[CQ:at,qq=12345] [CQ:at,qq=all] [CQ:record,file=x]"),
    )
    pending = store.list_pending_for("10001", "23456")
    assert "[标准名 " in pending[0].format_display()
    assert "@标准名 @全体成员 [语音]" in pending[0].format_display()
    assert store.pop_pending("10001", "23456")[0].format_display() == pending[0].format_display()
    assert not store._db.execute("SELECT * FROM offline_messages_member_refs").fetchall()
    store.close()
