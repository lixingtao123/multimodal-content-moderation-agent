"""
Skill Registry v1.0 — 运行时 Skill 知识加载系统

实现三层渐进式加载 (Progressive Disclosure):
  L1 (元数据):  启动时加载全部 name + description + mcp_tools (~100 tokens/skill)
  L2 (完整内容): 首次使用时加载 SKILL.md 全文 (~1000-2000 tokens/skill)
  L3 (支持文件): 按需加载 references/ 和 scripts/ 文件

Skill 目录:
  - /workspace/.claude/skills/  (Claude Code 集成, 优先级高)
  - /workspace/skills/           (原有目录, 向后兼容)

使用方式:
  from agent_moderation.skill_registry import get_skill_registry

  registry = get_skill_registry()

  # Agent 加载 Skill 知识注入 system prompt
  context = registry.get_skill_context("keyword-check")
  if context:
      system_prompt += f"\n\n[SKILL CONTEXT]\n{context}"

  # 查找某个 MCP 工具关联的 Skill
  skills = registry.find_by_mcp_tool("keyword_check")
"""
import logging
import os
import re
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Skill 搜索路径（优先级从高到低）
SKILL_SEARCH_PATHS = [
    "/workspace/.claude/skills",
    "/workspace/skills",
]

# YAML frontmatter 分隔符
FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)


@dataclass
class SkillMeta:
    """Skill 元数据 (L1 — 启动时加载)"""
    name: str
    description: str
    version: str = "1.0.0"
    invocation_mode: str = "agent-only"  # user-only / agent-only / both
    scope: str = "project"
    mcp_tools: List[str] = field(default_factory=list)
    triggers: List[dict] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    source_path: str = ""  # 来源目录

    @property
    def token_estimate(self) -> int:
        """估算元数据的 token 数（约 4 chars/token）"""
        text = f"{self.name} {self.description} {' '.join(self.tags)} {' '.join(self.mcp_tools)}"
        return len(text) // 4


@dataclass
class Skill:
    """完整 Skill（L1 + L2 + L3）"""
    meta: SkillMeta
    instructions: str = ""         # L2: SKILL.md body
    references: Dict[str, str] = field(default_factory=dict)  # L3: references/ 文件内容
    scripts: Dict[str, str] = field(default_factory=dict)      # L3: scripts/ 文件内容

    @property
    def full_context(self) -> str:
        """获取完整 Skill 上下文（Agent 注入用）"""
        parts = [f"## {self.meta.name}\n{self.instructions}"]
        for ref_name, ref_content in self.references.items():
            parts.append(f"### Reference: {ref_name}\n{ref_content}")
        return "\n\n".join(parts)


class SkillRegistry:
    """Skill 注册中心 — 运行时加载和管理所有 Skills"""

    def __init__(self, search_paths: List[str] = None):
        self._search_paths = search_paths or SKILL_SEARCH_PATHS
        self._skills: Dict[str, Skill] = {}       # 完整加载的 Skills
        self._meta_cache: Dict[str, SkillMeta] = {}  # L1 元数据缓存
        self._activation_count: Dict[str, int] = {}  # Skill 激活次数统计
        self._loaded = False
        self._load_all_metadata()

    def _load_all_metadata(self):
        """L1 加载：扫描所有 Skill 目录，解析 SKILL.md 元数据"""
        for search_path in self._search_paths:
            if not os.path.isdir(search_path):
                continue

            for entry in os.listdir(search_path):
                skill_dir = os.path.join(search_path, entry)
                if not os.path.isdir(skill_dir):
                    continue

                skill_md = os.path.join(skill_dir, "SKILL.md")
                if not os.path.exists(skill_md):
                    continue

                try:
                    meta = self._parse_frontmatter(skill_md, search_path)
                    if meta:
                        # 去重：已存在的 Skill 不覆盖（第一个搜索路径优先级最高）
                        if meta.name not in self._meta_cache:
                            self._meta_cache[meta.name] = meta
                            self._activation_count[meta.name] = 0
                            logger.debug(f"Skill discovered: {meta.name} ({skill_dir})")
                except Exception as e:
                    logger.warning(f"Failed to parse {skill_md}: {e}")

        self._loaded = True
        logger.info(
            f"SkillRegistry: loaded {len(self._meta_cache)} skill metadata "
            f"(~{sum(m.token_estimate for m in self._meta_cache.values())} tokens L1)"
        )

    def _parse_frontmatter(self, filepath: str, source_path: str) -> Optional[SkillMeta]:
        """解析 SKILL.md 的 YAML frontmatter"""
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        match = FRONTMATTER_RE.match(content)
        if not match:
            logger.warning(f"No frontmatter found in {filepath}")
            return None

        frontmatter_text = match.group(1)
        body = content[match.end():]

        # 简易 YAML 解析（仅支持顶层 key: value 和 list）
        meta_dict = self._parse_simple_yaml(frontmatter_text)

        return SkillMeta(
            name=meta_dict.get("name", os.path.basename(os.path.dirname(filepath))),
            description=meta_dict.get("description", ""),
            version=meta_dict.get("version", "1.0.0"),
            invocation_mode=meta_dict.get("invocation_mode", "agent-only"),
            scope=meta_dict.get("scope", "project"),
            mcp_tools=meta_dict.get("mcp_tools", []),
            triggers=meta_dict.get("triggers", []),
            tags=meta_dict.get("tags", []),
            source_path=source_path,
        )

    def _parse_simple_yaml(self, text: str) -> dict:
        """简易 YAML 解析器（支持顶层 key: value、[-] 列表、内联列表 [a,b,c]）"""
        import re as _re
        result = {}
        current_key = None
        current_list = []

        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # 列表项
            if stripped.startswith("- "):
                value = stripped[2:].strip().strip('"').strip("'")
                if current_key:
                    # 尝试解析嵌套的 key: value
                    if ":" in value:
                        nk, _, nv = value.partition(":")
                        current_list.append({nk.strip(): nv.strip().strip('"').strip("'")})
                    else:
                        current_list.append(value)
                continue

            # 保存之前的列表
            if current_key and current_list:
                result[current_key] = current_list
                current_list = []

            # key: value
            if ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip().strip('"').strip("'")

                if value == "":
                    # 可能是嵌套对象的开始
                    current_key = key
                    current_list = []
                elif value == "[]":
                    result[key] = []
                    current_key = None
                elif value.startswith("[") and value.endswith("]"):
                    # 内联列表: [a, b, c]
                    inner = value[1:-1]
                    items = [v.strip().strip('"').strip("'") for v in inner.split(",") if v.strip()]
                    result[key] = items
                    current_key = None
                else:
                    result[key] = value
                    current_key = None

        # 保存最后的列表
        if current_key and current_list:
            result[current_key] = current_list

        return result

    def _load_full_skill(self, name: str) -> Optional[Skill]:
        """L2 + L3 加载：读取完整 SKILL.md 和 references/"""
        meta = self._meta_cache.get(name)
        if not meta:
            return None

        # 查找 SKILL.md 文件
        skill_md_path = None
        skill_dir = None
        for search_path in self._search_paths:
            for entry in os.listdir(search_path):
                if entry == name or entry == name.replace("-", "_"):
                    candidate = os.path.join(search_path, entry, "SKILL.md")
                    if os.path.exists(candidate):
                        skill_md_path = candidate
                        skill_dir = os.path.join(search_path, entry)
                        break
            if skill_md_path:
                break

        if not skill_md_path:
            return None

        with open(skill_md_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 提取 body（去除 frontmatter）
        match = FRONTMATTER_RE.match(content)
        instructions = content[match.end():].strip() if match else content

        # L3: 加载 references/
        references = {}
        refs_dir = os.path.join(skill_dir, "references") if skill_dir else None
        if refs_dir and os.path.isdir(refs_dir):
            for ref_file in os.listdir(refs_dir):
                ref_path = os.path.join(refs_dir, ref_file)
                if os.path.isfile(ref_path):
                    try:
                        with open(ref_path, "r", encoding="utf-8") as f:
                            references[ref_file] = f.read()
                    except Exception:
                        pass

        # L3: 加载 scripts/（仅元数据，不加载完整内容）
        scripts = {}
        scripts_dir = os.path.join(skill_dir, "scripts") if skill_dir else None
        if scripts_dir and os.path.isdir(scripts_dir):
            for script_file in os.listdir(scripts_dir):
                scripts[script_file] = f"<script:{script_file}>"

        skill = Skill(meta=meta, instructions=instructions, references=references, scripts=scripts)
        self._skills[name] = skill
        return skill

    # ===== 公共 API =====

    def list_skills(self) -> List[SkillMeta]:
        """列出所有 Skill 元数据（L1）"""
        return list(self._meta_cache.values())

    def get_skill(self, name: str) -> Optional[Skill]:
        """获取完整 Skill（L1 + L2 + L3），首次调用触发 L2 加载"""
        if name in self._skills:
            skill = self._skills[name]
        else:
            skill = self._load_full_skill(name)
            if skill:
                self._skills[name] = skill

        if skill:
            self._activation_count[name] = self._activation_count.get(name, 0) + 1
        return skill

    def get_skill_context(self, name: str) -> Optional[str]:
        """
        获取 Skill 的 Agent 上下文注入文本。

        Agent 将此文本拼接到 system prompt 中，
        格式: [SKILL CONTEXT: <name>]\n<instructions>\n[/SKILL CONTEXT]
        """
        skill = self.get_skill(name)
        if not skill:
            return None

        parts = [f"[SKILL CONTEXT: {skill.meta.name} v{skill.meta.version}]"]
        parts.append(skill.instructions)

        # 附加关键 reference
        for ref_name, ref_content in skill.references.items():
            if len(ref_content) < 5000:  # 只注入小型 reference
                parts.append(f"--- Reference: {ref_name} ---\n{ref_content}")

        parts.append(f"[/SKILL CONTEXT: {skill.meta.name}]")
        return "\n\n".join(parts)

    def get_skill_instructions_only(self, name: str) -> Optional[str]:
        """获取 Skill 的纯指令文本（不含 reference）"""
        skill = self.get_skill(name)
        return skill.instructions if skill else None

    def find_by_mcp_tool(self, tool_name: str) -> List[SkillMeta]:
        """查找依赖指定 MCP 工具的所有 Skills"""
        results = []
        for meta in self._meta_cache.values():
            if tool_name in meta.mcp_tools:
                results.append(meta)
        return results

    def find_by_tag(self, tag: str) -> List[SkillMeta]:
        """按标签查找 Skills"""
        return [m for m in self._meta_cache.values() if tag in m.tags]

    def find_by_content_type(self, content_type: str) -> List[SkillMeta]:
        """按内容类型查找 Skills"""
        results = []
        for meta in self._meta_cache.values():
            for trigger in meta.triggers:
                if trigger.get("content_type") == content_type:
                    results.append(meta)
        return results

    def get_mcp_tool_skills_map(self) -> Dict[str, List[str]]:
        """获取 MCP 工具 → Skill 映射表"""
        mapping: Dict[str, List[str]] = {}
        for meta in self._meta_cache.values():
            for tool in meta.mcp_tools:
                if tool not in mapping:
                    mapping[tool] = []
                mapping[tool].append(meta.name)
        return mapping

    def get_metrics(self) -> dict:
        """获取 Skill 激活统计"""
        return {
            name: {
                "activations": count,
                "version": self._meta_cache[name].version if name in self._meta_cache else "?",
                "mcp_tools": self._meta_cache[name].mcp_tools if name in self._meta_cache else [],
            }
            for name, count in self._activation_count.items()
        }

    @property
    def l1_token_cost(self) -> int:
        """L1 元数据的总 token 开销"""
        return sum(m.token_estimate for m in self._meta_cache.values())

    @property
    def skill_count(self) -> int:
        return len(self._meta_cache)


# 全局单例
_skill_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    global _skill_registry
    if _skill_registry is None:
        _skill_registry = SkillRegistry()
    return _skill_registry
