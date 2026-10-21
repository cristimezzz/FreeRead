"""图谱的固定 schema（architecture §5.7A）。"""

from enum import StrEnum


class EntityType(StrEnum):
    TASK = "Task"
    METHOD = "Method"
    DATASET = "Dataset"
    METRIC = "Metric"
    MODEL = "Model"
    CONCEPT = "Concept"


class RelationType(StrEnum):
    PROPOSES = "proposes"
    USES = "uses"
    IMPROVES_ON = "improves_on"
    EVALUATED_ON = "evaluated_on"
    ACHIEVES = "achieves"
    COMPARES_WITH = "compares_with"
    PART_OF = "part_of"


_ENTITY_BY_LOWER = {t.value.lower(): t for t in EntityType}
_RELATION_BY_LOWER = {t.value: t for t in RelationType}


def entity_type(raw: object) -> EntityType | None:
    return _ENTITY_BY_LOWER.get(str(raw or "").strip().lower())


def relation_type(raw: object) -> RelationType | None:
    key = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    return _RELATION_BY_LOWER.get(key)
