"""Load domain diagnosis SOPs and inject only the relevant instructions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    content: str
    path: str
    keywords: List[str]
    agents: List[str]
    enabled: bool

    def matches(self, message: str, agent_type: Optional[str]) -> bool:
        if not self.enabled:
            return False
        if self.agents and (not agent_type or agent_type.lower() not in self.agents):
            return False
        lowered = message.lower()
        return not self.keywords or any(keyword.lower() in lowered for keyword in self.keywords)

    def prompt_block(self, max_chars: int) -> str:
        content = self.content.strip()
        if len(content) > max_chars:
            content = content[:max_chars].rstrip() + "\n..."
        description = f"\nPurpose: {self.description}" if self.description else ""
        return f"### {self.name}{description}\n{content}"

    def summary(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "path": self.path,
            "keywords": self.keywords,
            "agents": self.agents,
            "enabled": self.enabled,
        }


class SkillManager:
    """Discover `skills/*/SKILL.md` files and build a bounded prompt."""

    def __init__(self, root_dir: str, max_prompt_chars: int = 5000):
        self.root_dir = Path(root_dir).expanduser().resolve()
        self.max_prompt_chars = max_prompt_chars
        self._skills: List[Skill] = []
        self._errors: List[str] = []

    @property
    def skills(self) -> List[Skill]:
        return list(self._skills)

    def load(self) -> List[Skill]:
        skills: List[Skill] = []
        errors: List[str] = []
        if self.root_dir.exists():
            for path in sorted(self.root_dir.rglob("SKILL.md")):
                try:
                    skills.append(self._parse(path))
                except Exception as exc:
                    errors.append(f"{path}: {exc}")

        self._skills = skills
        self._errors = errors
        logger.info("Loaded %s OpsPilot skills from %s", len(skills), self.root_dir)
        for error in errors:
            logger.warning("Skill load failed: %s", error)
        return self.skills

    def reload(self) -> List[Skill]:
        return self.load()

    def prompt_for(self, message: str, agent_type: Optional[str] = None) -> str:
        remaining = self.max_prompt_chars
        blocks: List[str] = []
        for skill in self._skills:
            if not skill.matches(message, agent_type):
                continue
            block = skill.prompt_block(min(3200, remaining))
            blocks.append(block)
            remaining -= len(block)
            if remaining <= 0:
                break
        if not blocks:
            return ""
        return (
            "Follow the matching OpsPilot diagnosis SOPs below. System safety rules take precedence.\n\n"
            + "\n\n".join(blocks)
        )

    def summary(self) -> Dict[str, Any]:
        return {
            "root_dir": str(self.root_dir),
            "count": len(self._skills),
            "skills": [skill.summary() for skill in self._skills],
            "errors": list(self._errors),
        }

    @staticmethod
    def _parse(path: Path) -> Skill:
        raw = path.read_text(encoding="utf-8").lstrip()
        metadata, body = SkillManager._front_matter(raw)
        name = metadata.get("name") or path.parent.name
        content = SkillManager._remove_matching_heading(body.strip(), name)
        if not content:
            raise ValueError("skill body is empty")
        return Skill(
            name=name,
            description=metadata.get("description", ""),
            content=content,
            path=str(path),
            keywords=SkillManager._list(metadata.get("keywords", "")),
            agents=[item.lower() for item in SkillManager._list(metadata.get("agents", ""))],
            enabled=metadata.get("enabled", "true").lower() not in {"false", "0", "off"},
        )

    @staticmethod
    def _front_matter(raw: str) -> tuple[Dict[str, str], str]:
        lines = raw.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}, raw
        metadata: Dict[str, str] = {}
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return metadata, "\n".join(lines[index + 1:])
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip("\"'")
        raise ValueError("front matter is not closed")

    @staticmethod
    def _remove_matching_heading(body: str, name: str) -> str:
        lines = body.splitlines()
        if lines and lines[0].lstrip("# ").strip() == name:
            return "\n".join(lines[1:]).strip()
        return body

    @staticmethod
    def _list(value: str) -> List[str]:
        return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
