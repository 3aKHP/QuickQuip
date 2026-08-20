#!/usr/bin/env bash
# Deterministic, read-only gate for Tier 2 deep review.
#
# Prints one JSON object and never changes repository state. Keep the domain
# mapping aligned with docs/dev/branching.md "Two-tier code review".
set -u

base="${1:-dev}"
merge_base=""
if merge_base=$(git merge-base HEAD "$base" 2>/dev/null); then
  base_resolved=1
else
  base_resolved=0
fi

changed_files=""
if [ "$base_resolved" -eq 1 ]; then
  changed_files=$(git diff --name-only "$merge_base" HEAD 2>/dev/null | sort -u)
fi

classify() {
  case "$1" in
    src/quickquip/llm/provider/*|src/quickquip/llm/mcp/*) echo provider-mcp ;;
    src/quickquip/llm/service.py|src/quickquip/llm/service_parts/*|src/quickquip/llm/tool_*.py) echo llm-tools ;;
    src/quickquip/llm/*store*|src/quickquip/common/persistence.py|src/quickquip/app/web/actions.py) echo persistence ;;
    src/quickquip/chat/awakening.py|src/quickquip/adapters/nonebot/group_messages.py|src/quickquip/app/message_pipeline.py) echo message-policy ;;
    src/quickquip/app/web/*|frontend/src/*) echo web-admin ;;
    Dockerfile|docker-compose*.yml|prod.example/*|.github/workflows/release.yml) echo release-deployment ;;
    *) echo "" ;;
  esac
}

categories=""
if [ -n "$changed_files" ]; then
  categories=$(printf '%s\n' "$changed_files" | while IFS= read -r file; do classify "$file"; done | grep . | sort -u)
fi

file_count=0
category_count=0
if [ -n "$changed_files" ]; then file_count=$(printf '%s\n' "$changed_files" | grep -c .); fi
if [ -n "$categories" ]; then category_count=$(printf '%s\n' "$categories" | grep -c .); fi

changed_lines=0
if [ "$base_resolved" -eq 1 ]; then
  changed_lines=$(git diff --numstat "$merge_base" HEAD 2>/dev/null | awk '{ a=($1=="-"?0:$1)+0; d=($2=="-"?0:$2)+0; sum+=a+d } END { print sum+0 }')
fi

category_match=0
cross_boundary=0
size_floor=0
release_branch=0
[ "$category_count" -gt 0 ] && category_match=1
[ "$category_count" -ge 2 ] && cross_boundary=1
if [ "$file_count" -ge 8 ] || [ "$changed_lines" -ge 300 ]; then size_floor=1; fi

branch=$(git branch --show-current 2>/dev/null || true)
case "$branch:$base" in
  release/*:*|main:*|*:main|*:v*) release_branch=1 ;;
esac

reasons=()
if [ "$category_match" -eq 1 ]; then
  reasons+=("category_match: touches $(printf '%s' "$categories" | paste -sd, - | sed 's/,/, /g')")
else
  reasons+=("no_category_match: no high-risk domain file changed")
fi
[ "$cross_boundary" -eq 1 ] && reasons+=("cross_boundary: ${category_count} distinct domains")
[ "$size_floor" -eq 1 ] && reasons+=("size_floor: ${file_count} files, ${changed_lines} changed lines")
[ "$release_branch" -eq 1 ] && reasons+=("release_branch: branch=${branch} base=${base}")
[ "$base_resolved" -eq 0 ] && reasons+=("base '${base}' not resolvable locally")

trigger=0
if [ "$category_match" -eq 1 ] && { [ "$cross_boundary" -eq 1 ] || [ "$size_floor" -eq 1 ] || [ "$release_branch" -eq 1 ]; }; then trigger=1; fi

joined=""
for reason in "${reasons[@]}"; do
  escaped=${reason//\\/\\\\}
  escaped=${escaped//\"/\\\"}
  if [ -z "$joined" ]; then joined="\"${escaped}\""; else joined="${joined}, \"${escaped}\""; fi
done

base_escaped=${base//\\/\\\\}
base_escaped=${base_escaped//\"/\\\"}
printf '{"trigger":%s,"base":"%s","reasons":[%s]}\n' \
  "$([ "$trigger" -eq 1 ] && echo true || echo false)" "$base_escaped" "$joined"
