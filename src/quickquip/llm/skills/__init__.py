"""QuickQuip Skill 系统（``llm/skills/`` 域包）。

Skill 目录（默认项目根 ``skills/``）是受信任的部署资产：每个子目录一个
Skill（``SKILL.md`` + 可选 ``references/`` + 可选 ``scripts/``），目录名即
name。catalog（全部已安装 Skill 的 name+description）常驻系统提示静态段
末尾，模型经 ``activate_skill`` 激活后正文才以带标记工具结果注入会话
历史尾部；``read_skill_resource`` / ``search_skill_resources`` /
``run_skill_script`` 只对已激活 Skill 开放。

本 ``__init__`` 只 re-export 真实公共契约（tests/unit/llm 的 re-export
契约测试守护）；工具名常量定义在各工具模块，``service_parts/constants.py``
统一 re-export 给默认名单使用。
"""

from quickquip.llm.skills.catalog import (
    MAX_RESOURCES_PER_SKILL,
    SKILL_FILE_NAME,
    LoadedSkill,
    SkillCatalog,
    SkillCatalogEntry,
    SkillResource,
    assert_safe_relative_path,
    build_catalog,
    classify_resource,
    derive_catalog_budget_bytes,
    resolve_catalog_dir,
    resolve_skill_file,
    scan_skills,
    utf8_safe_boundary,
)
from quickquip.llm.skills.context import (
    ACTIVATION_STATUS_ACTIVATED,
    ACTIVATION_STATUS_ALREADY_ACTIVE,
    format_activation_block,
    render_catalog_block,
    render_skill_list,
)
from quickquip.llm.skills.parser import (
    MAX_DESCRIPTION_CHARS,
    MAX_NAME_LENGTH,
    MAX_SKILL_FILE_BYTES,
    SKILL_NAME_PATTERN,
    ParseSkillResult,
    SkillDiagnostic,
    SkillMetadata,
    parse_skill_markdown,
)
from quickquip.llm.skills.state import SkillActivationState
from quickquip.llm.skills.tools.activate import (
    ACTIVATE_SKILL_TOOL_NAME,
    activate_skill,
    build_activate_skill_spec,
    require_active_skill,
)
from quickquip.llm.skills.tools.activate import (
    TOOL_KEYWORDS as ACTIVATE_SKILL_TOOL_KEYWORDS,
)
from quickquip.llm.skills.tools.read_resource import (
    READ_SKILL_RESOURCE_SPEC,
    READ_SKILL_RESOURCE_TOOL_NAME,
    read_skill_resource,
)
from quickquip.llm.skills.tools.read_resource import (
    TOOL_KEYWORDS as READ_SKILL_RESOURCE_TOOL_KEYWORDS,
)
from quickquip.llm.skills.tools.run_script import (
    MAX_SCRIPT_TIMEOUT_MS,
    RUN_SKILL_SCRIPT_SPEC,
    RUN_SKILL_SCRIPT_TOOL_NAME,
    run_skill_script,
)
from quickquip.llm.skills.tools.run_script import (
    TOOL_KEYWORDS as RUN_SKILL_SCRIPT_TOOL_KEYWORDS,
)
from quickquip.llm.skills.tools.search_resource import (
    SEARCH_SKILL_RESOURCES_SPEC,
    SEARCH_SKILL_RESOURCES_TOOL_NAME,
    search_skill_resources,
)
from quickquip.llm.skills.tools.search_resource import (
    TOOL_KEYWORDS as SEARCH_SKILL_RESOURCES_TOOL_KEYWORDS,
)

__all__ = [
    "ACTIVATE_SKILL_TOOL_KEYWORDS",
    "ACTIVATE_SKILL_TOOL_NAME",
    "ACTIVATION_STATUS_ACTIVATED",
    "ACTIVATION_STATUS_ALREADY_ACTIVE",
    "MAX_DESCRIPTION_CHARS",
    "MAX_NAME_LENGTH",
    "MAX_RESOURCES_PER_SKILL",
    "MAX_SCRIPT_TIMEOUT_MS",
    "MAX_SKILL_FILE_BYTES",
    "ParseSkillResult",
    "READ_SKILL_RESOURCE_SPEC",
    "READ_SKILL_RESOURCE_TOOL_KEYWORDS",
    "READ_SKILL_RESOURCE_TOOL_NAME",
    "RUN_SKILL_SCRIPT_SPEC",
    "RUN_SKILL_SCRIPT_TOOL_KEYWORDS",
    "RUN_SKILL_SCRIPT_TOOL_NAME",
    "SEARCH_SKILL_RESOURCES_SPEC",
    "SEARCH_SKILL_RESOURCES_TOOL_KEYWORDS",
    "SEARCH_SKILL_RESOURCES_TOOL_NAME",
    "SKILL_FILE_NAME",
    "SKILL_NAME_PATTERN",
    "SkillActivationState",
    "SkillCatalog",
    "SkillCatalogEntry",
    "SkillDiagnostic",
    "SkillMetadata",
    "SkillResource",
    "LoadedSkill",
    "activate_skill",
    "assert_safe_relative_path",
    "build_activate_skill_spec",
    "build_catalog",
    "classify_resource",
    "derive_catalog_budget_bytes",
    "format_activation_block",
    "parse_skill_markdown",
    "read_skill_resource",
    "render_catalog_block",
    "render_skill_list",
    "require_active_skill",
    "resolve_catalog_dir",
    "resolve_skill_file",
    "run_skill_script",
    "scan_skills",
    "search_skill_resources",
    "utf8_safe_boundary",
]
