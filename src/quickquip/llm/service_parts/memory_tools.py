"""主模型的会话记忆工具；事实来源只能引用当前上下文中的消息。"""

from __future__ import annotations

import json
from collections.abc import Callable

from quickquip.llm.tools import LLMToolSpec, ToolExecutionContext
from quickquip.common.record_content import references

MEMORY_TOOL_NAMES = frozenset({"list_memories", "read_memory", "write_memory", "delete_memory"})
_RULES = (
    "自主维护当前会话记忆，修改前读取条目和来源。管理约定冲突时依次优先考虑"
    "全局管理员、群主、群管理员、普通成员；个人事实按可靠来源和明确更正判断。"
    "用 source_message_id 指明依据的消息 ID，角色由程序核实；未提供时来源未知。"
)


def entry_payload(item: dict, *, full: bool = True) -> dict:
    keys = [
        "id",
        "title",
        "description",
        "version",
        "source",
        "writer",
        "source_role",
        "source_user_id",
        "source_message_id",
        "updated_at",
    ]
    if full:
        keys += ["content", "content_display", "content_parts"]
    return {**{key: item.get(key) for key in keys},
            "subject_user_id": item.get("user_id")}


class MemoryTools:
    def __init__(self, store, settings: Callable, capacity: Callable[[], int]):
        self._store = store
        self.settings = settings
        self.capacity = capacity

    @property
    def store(self):
        store = self._store() if callable(self._store) else self._store
        if store is None:
            raise ValueError("记忆存储不可用")
        return store

    def scope(self, context: ToolExecutionContext) -> str:
        if not self.settings(context.group_id, context.chat_type).memory_enabled:
            raise ValueError("当前会话记忆已关闭")
        return context.chat_scope or (
            f"private:{context.group_id}"
            if context.chat_type == "private"
            else str(context.group_id)
        )

    async def list_entries(self, args, context):
        scope = self.scope(context)
        offset = max(0, int(args.get("offset", 0)))
        items = self.store.list_memories(
            scope, keyword=args.get("keyword") or None, limit=21, offset=offset
        )
        return json.dumps(
            {
                "total": self.store.count_memories(scope),
                "next_offset": offset + 20 if len(items) > 20 else None,
                "items": [entry_payload(item, full=False) for item in items[:20]],
            },
            ensure_ascii=False,
        )

    async def read(self, args, context):
        return json.dumps(
            entry_payload(self.store.read_memory(self.scope(context), args["id"])),
            ensure_ascii=False,
        )

    async def write(self, args, context):
        scope = self.scope(context)
        source_id = args.get("source_message_id")
        if source_id is not None and source_id not in context.memory_sources:
            raise ValueError("来源消息不在当前上下文中，请使用已提供的消息 ID")
        provenance = dict(context.memory_sources.get(source_id, {}), writer="model")
        values = {
            key: args[key]
            for key in ("content", "title", "description", "content_parts")
            if key in args
        }
        if "id" not in args:
            memory_id = self.store.add_memory(
                scope, **values, **provenance, source="model", max_items=self.capacity()
            )
            item = self.store.read_memory(scope, memory_id)
        else:
            if "version" not in args:
                raise ValueError("覆写前请读取条目并提供 version")
            current = self.store.read_memory(scope, args["id"])
            if references(current["content_parts"]) and "content_parts" not in values:
                raise ValueError(
                    "原条目包含明确艾特，请基于 read_memory 返回的 content_parts 编辑；"
                    "需要移除引用时，将对应片段明确改为 text"
                )
            item = self.store.update_memory(
                scope, args["id"], version=args["version"], provenance=provenance, **values
            )
        return json.dumps(entry_payload(item), ensure_ascii=False)

    async def delete(self, args, context):
        count = self.store.delete_memory(self.scope(context), args["id"], version=args["version"])
        return json.dumps({"deleted": count})


def register_memory_tools(registry, store, settings, capacity) -> None:
    handlers = MemoryTools(store, settings, capacity)
    integer = {"type": "integer", "minimum": 1}
    definitions = [
        (
            "list_memories",
            handlers.list_entries,
            "搜索或分页浏览当前会话的记忆目录。",
            {
                "keyword": {"type": "string", "maxLength": 256},
                "offset": {"type": "integer", "minimum": 0},
            },
            [],
        ),
        ("read_memory", handlers.read, "按 ID 读取完整记忆、版本和来源。", {"id": integer}, ["id"]),
        (
            "write_memory",
            handlers.write,
            "新增记忆；提供 id 和 version 时覆写已有条目。" + _RULES,
            {
                "id": integer,
                "version": integer,
                "content": {"type": "string", "minLength": 1, "maxLength": 4096},
                "title": {"type": "string", "minLength": 1, "maxLength": 64},
                "description": {"type": "string", "maxLength": 160},
                "source_message_id": {"type": "string"},
                "content_parts": {
                    "type": "object",
                    "description": ("含明确艾特的条目使用读取返回的结构，"
                                    "编辑 text 正文并保留 member 引用"),
                    "properties": {
                        "version": {"type": "integer", "enum": [1]},
                        "parts": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["version", "parts"],
                },
            },
            ["content"],
        ),
        (
            "delete_memory",
            handlers.delete,
            "删除指定版本的记忆。" + _RULES,
            {"id": integer, "version": integer},
            ["id", "version"],
        ),
    ]
    for name, handler, description, properties, required in definitions:
        registry.register(
            LLMToolSpec(
                name=name,
                description=description,
                input_schema={
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            ),
            handler,
            category="memory",
            keywords=["记忆", "memory"],
            always_loaded=True,
        )
