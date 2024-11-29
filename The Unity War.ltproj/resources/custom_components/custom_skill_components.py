from __future__ import annotations

from app.data.database.components import ComponentType
from app.data.database.database import DB
from app.data.database.skill_components import SkillComponent, SkillTags
from app.engine import (action, banner, combat_calcs, engine, equations,
                        image_mods, item_funcs, item_system, skill_system)
from app.engine.game_state import game
from app.engine.objects.unit import UnitObject
from app.utilities import utils, static_random


class DoNothing(SkillComponent):
    nid = 'do_nothing'
    desc = 'does nothing'
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 1

class PersonalSkill(SkillComponent):
    nid = 'personal_skill'
    desc = "A filler for future organizational purposes."
    tag = SkillTags.ATTRIBUTE
    
class CostUses(SkillComponent):
    nid = 'cost_uses'
    desc = "Skill costs alternate number of weapon uses. Unit must have at least that many uses."
    tag = SkillTags.CHARGE

    expose = ComponentType.Int
    value = 2

    ignore_conditional = True

    def condition(self, unit, item):
        return item.data.get('uses', 999) > self.value
            
    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        actions.append(action.SetObjData(item, 'uses', item.data['uses'] - self.value + 1))

    def on_miss(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        if item.uses_options.lose_uses_on_miss():
            actions.append(action.SetObjData(item, 'uses', item.data['uses'] - self.value + 1))
        else:
            actions.append(action.SetObjData(item, 'uses', item.data['uses'] - self.value))