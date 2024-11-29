from __future__ import annotations

from app.data.database.components import ComponentType
from app.data.database.database import DB
from app.data.database.item_components import ItemComponent, ItemTags
from app.engine import (action, banner, combat_calcs, engine, equations,
                        image_mods, item_funcs, item_system, skill_system)
from app.engine.game_state import game
from app.engine.objects.unit import UnitObject
from app.utilities import utils, static_random


class DoNothing(ItemComponent):
    nid = 'do_nothing'
    desc = 'does nothing'
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 1

class StatusAfterCombat(ItemComponent):
    nid = 'status_after_combat'
    desc = "Target will gain the specified status at the end of combat. Prevents changes being applied mid-combat."
    tag = ItemTags.SPECIAL

    expose = ComponentType.Skill  # Nid

    def end_combat(self, playback, unit, item, target, item2, mode):
        act = action.AddSkill(target, self.value, unit)
        action.do(act)

    def ai_priority(self, unit, item, target, move):
        # Do I add a new status to the target
        return ai_status_priority(unit, target, item, move, self.value)