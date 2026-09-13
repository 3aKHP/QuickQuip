"""Compile record query identity candidates once per request."""
from quickquip.common.record_content import decode, legacy, references, render


class RecordQuery:
    def __init__(self, query, snapshot):
        self.query = query or ""
        self.needle = self.query.casefold()
        self.snapshot = snapshot
        self.member_ids = snapshot.candidates(self.query) | references(legacy(self.query)) if self.query else set()

    def matches(self, row, include_owner=False):
        if not self.query or self.needle in str(row["content"]).casefold():
            return True
        if include_owner and str(row.get("user_id") or "") in self.member_ids:
            return True
        body = row.get("content_parts") or decode(row["content"], row.get("content_parts_json"))
        return bool(self.member_ids & references(body)) or self.needle in render(body, self.snapshot).casefold()


def matches(row, query, snapshot, include_owner=False):
    """Compatibility entry for individual comparisons; loops should reuse RecordQuery."""
    return RecordQuery(query, snapshot).matches(row, include_owner)
