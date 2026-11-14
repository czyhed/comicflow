"""Plan project character bindings without writes or model calls."""

from copy import deepcopy
from hashlib import sha256

from comicflow.domain.errors import DomainError
from comicflow.domain.models import JsonObject, ProjectRecord


def bind_script_characters(
    record: ProjectRecord, script: JsonObject, characters: list[JsonObject]
) -> tuple[JsonObject, list[JsonObject]]:
    project_id = record.project["id"]
    by_id = {card["id"]: card for card in characters}
    by_name = {card["name"]: card for card in characters if card.get("projectId") == project_id}
    result = deepcopy(script)
    pending: list[JsonObject] = []
    for shot in result.get("shots", []):
        ids = list(shot.get("characterIds", []))
        names = shot.get("characters", [])
        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
            raise DomainError("SCRIPT_INVALID")
        for name in dict.fromkeys(name.strip() for name in names if name.strip()):
            card = by_name.get(name)
            if card is None:
                # Stable in read-only previews, project-scoped, and independent of shot order.
                card_id = "chr_" + sha256(f"{project_id}\0{name}".encode()).hexdigest()[:24]
                card = {
                    "id": card_id,
                    "name": name,
                    "projectId": project_id,
                    "source": "temporary",
                    "ownerType": "guest",
                    "ownerId": record.guest_session["id"],
                    "appearance": "",
                    "clothing": "",
                    "personality": "",
                    "voice": {"language": "zh-CN"},
                }
                by_name[name] = card
                by_id[card_id] = card
                pending.append(card)
            if card["id"] not in ids:
                ids.append(card["id"])
        for card_id in ids:
            card = by_id.get(card_id)
            if card is None:
                raise DomainError("CHARACTER_NOT_FOUND")
            if card.get("source") != "system" and card.get("projectId") != project_id:
                if not (
                    record.project.get("ownerUserId")
                    and card.get("ownerType") == "user"
                    and card.get("ownerId") == record.project["ownerUserId"]
                ):
                    raise DomainError("CHARACTER_ACCESS_DENIED")
        shot["characterIds"] = list(dict.fromkeys(ids))
    return result, pending
