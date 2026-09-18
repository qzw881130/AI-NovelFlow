"""Book-scoped retrieval and deterministic identity rules; no prompt text."""
from copy import deepcopy
from difflib import SequenceMatcher
import json
from pathlib import Path

from app.models.novel import Character, Scene, Prop
from app.models.asset_resolution import CharacterIdentity, CharacterAlias, ChapterCharacterBinding, ChapterSceneBinding, ChapterPropBinding
from app.services.chapter_asset_parse_service import digest

MODELS = {"characters": Character, "scenes": Scene, "props": Prop}
BINDINGS = {"characters": (ChapterCharacterBinding, "character_id"),
            "scenes": (ChapterSceneBinding, "scene_id"), "props": (ChapterPropBinding, "prop_id")}
ROOT = Path(__file__).resolve().parents[2] / "prompt_templates"


def load_policy():
    rules_raw = (ROOT / "asset_identity_rules.json").read_text(encoding="utf-8")
    prompts_raw = (ROOT / "existing_asset_resolver.json").read_text(encoding="utf-8")
    rules, prompts = json.loads(rules_raw), json.loads(prompts_raw)
    if type(rules.get("top_k")) is not int or not 1 <= rules["top_k"] <= 20:
        raise ValueError("invalid resolver top_k")
    for key in ("stable_groups", "generic_groups"):
        if not isinstance(rules.get(key), list) or any(not isinstance(item, str) for item in rules[key]):
            raise ValueError(f"invalid resolver rules: {key}")
    for key in ("strong_aliases", "contextual_aliases"):
        if not isinstance(rules.get(key), dict) or any(not isinstance(v, list) or any(not isinstance(x, str) for x in v) for v in rules[key].values()):
            raise ValueError(f"invalid resolver rules: {key}")
    if any(not isinstance(prompts.get(key), str) or not prompts[key].strip() for key in ("version", "character_prompt", "asset_prompt", "user_template")):
        raise ValueError("invalid resolver prompt file")
    return {"rules": rules, "prompts": prompts, "rules_hash": digest(rules_raw), "prompt_hash": digest(prompts_raw),
            "hash": digest([rules_raw, prompts_raw])}


def row_snapshot(row):
    result = {}
    for column in row.__table__.columns:
        value = getattr(row, column.key)
        result[column.key] = value.isoformat() if hasattr(value, "isoformat") else value
    return result


def catalog(db, novel_id):
    identities = {row.character_id: row for row in db.query(CharacterIdentity).filter_by(novel_id=novel_id)}
    aliases = list(db.query(CharacterAlias).filter_by(novel_id=novel_id).order_by(CharacterAlias.id))
    fingerprint = {"identities": [row_snapshot(row) for row in sorted(identities.values(), key=lambda row: row.character_id)],
                   "aliases": [row_snapshot(row) for row in aliases]}
    result = {}
    for kind, model in MODELS.items():
        rows = db.query(model).filter(model.novel_id == novel_id).order_by(model.id).all()
        fingerprint[kind] = [row_snapshot(row) for row in rows]
        result[kind] = []
        for row in rows:
            identity = identities.get(row.id) if kind == "characters" else None
            result[kind].append({"asset_id": row.id, "character_id": row.id if kind == "characters" else None,
                "canonical_name": row.name, "entity_type": identity.entity_type if identity else None,
                "group_size_hint": identity.group_size_hint if identity else None,
                "description": row.description or "", "context": identity.context if identity else {},
                "strong_aliases": [a.alias for a in aliases if a.character_id == row.id and a.alias_type == "STRONG" and not a.scope],
                "contextual_aliases": [a.alias for a in aliases if a.character_id == row.id and a.alias_type == "CONTEXTUAL"],
                "alias_scopes": [{"alias": a.alias, "alias_type": a.alias_type, "scope": a.scope}
                                 for a in aliases if a.character_id == row.id],
                "is_narrator": bool(getattr(row, "is_narrator", False))})
    return result, digest(fingerprint)


def compatible(kind, candidate, asset):
    return kind != "characters" or (asset.get("entity_type") == candidate["entity_type"] and not asset.get("is_narrator"))


def context_excerpt(content, evidence, limit=3000):
    fragments = []
    for quote in evidence:
        position = content.find(quote["text"])
        if position >= 0:
            fragments.append(content[max(0, position - 180):position + len(quote["text"]) + 180])
    return "\n".join(dict.fromkeys(fragments))[:limit]


def bigrams(value):
    value = "".join(str(value).split()).casefold()
    return {value[i:i+2] for i in range(max(0, len(value) - 1))}


def retrieve(kind, candidate, assets, chapter_context, top_k):
    source = bigrams(candidate["name"] + candidate["description"] + chapter_context)
    ranked = []
    for asset in assets:
        if asset.get("is_narrator"):
            continue
        name = asset["canonical_name"]
        score = 100 if candidate["name"] == name else 20 * SequenceMatcher(None, candidate["name"], name).ratio()
        if candidate["name"] in asset["strong_aliases"]:
            score += 100
        if candidate["name"] in asset["contextual_aliases"]:
            score += 70
        target = bigrams(name + asset["description"] + json.dumps(asset["context"], ensure_ascii=False))
        score += 40 * len(source & target) / max(1, len(target))
        if compatible(kind, candidate, asset):
            score += 5
        projected = deepcopy(asset)
        projected.update(retrieval_score=round(score, 5), short_description=asset["description"][:1500],
                         faction=asset["context"].get("faction"), location=asset["context"].get("location"))
        ranked.append(projected)
    return sorted(ranked, key=lambda item: (-item["retrieval_score"], item["asset_id"]))[:top_k]


def deterministic(kind, candidate, assets, policy, chapter_context, all_characters):
    exact = [item for item in assets if item["canonical_name"] == candidate["name"] and not item.get("is_narrator")]
    if len(exact) == 1 and compatible(kind, candidate, exact[0]):
        if kind != "characters" or candidate["entity_type"] == "INDIVIDUAL":
            return "EXACT_NAME", exact[0]
        if candidate["name"] in policy["rules"]["stable_groups"]:
            old_text = exact[0]["description"] + json.dumps(exact[0]["context"], ensure_ascii=False)
            new_text = candidate["description"] + chapter_context
            for field in ("faction", "location"):
                scope = exact[0]["context"].get(field)
                if isinstance(scope, str) and scope.strip() and scope not in new_text:
                    return None, None
            names = [item["canonical_name"] for item in all_characters if item["entity_type"] == "INDIVIDUAL" and len(item["canonical_name"]) > 1]
            old_people, new_people = {n for n in names if n in old_text}, {n for n in names if n in new_text}
            if not old_people or not new_people or old_people == new_people:
                return "EXACT_NAME", exact[0]
    if kind == "characters" and candidate["entity_type"] == "INDIVIDUAL" and not exact:
        matches = [item for item in assets if candidate["name"] in item["strong_aliases"] and compatible(kind, candidate, item)]
        if len(matches) == 1:
            return "STRONG_ALIAS", matches[0]
    return None, None


def seed_aliases(db, character, policy, provenance):
    db.flush()
    identity = db.get(CharacterIdentity, character.id)
    for key, alias_type in (("strong_aliases", "STRONG"), ("contextual_aliases", "CONTEXTUAL")):
        if alias_type == "STRONG" and identity.entity_type != "INDIVIDUAL":
            continue
        for alias in policy["rules"][key].get(character.name, []):
            existing = db.query(CharacterAlias).filter_by(novel_id=character.novel_id, alias=alias, alias_type=alias_type).all()
            if alias_type == "STRONG" and any(row.character_id != character.id for row in existing):
                raise ValueError("strong alias conflicts with another identity")
            if not any(row.character_id == character.id for row in existing):
                db.add(CharacterAlias(novel_id=character.novel_id, character_id=character.id, alias=alias,
                                     alias_type=alias_type, scope={}, provenance=provenance))
