from __future__ import annotations

from app.data.database.components import ComponentType
from app.data.database.database import DB
from app.data.database.skill_components import SkillComponent, SkillTags
from app.engine import (action, banner, combat_calcs, engine, equations,
                        image_mods, item_funcs, item_system, skill_system)
from app.engine.game_state import game
from app.engine.objects.unit import UnitObject
from app.utilities import utils, static_random
from app.utilities.enums import Strike

class PersonalSkill(SkillComponent):
    nid = 'personal_skill'
    desc = "A filler for future organizational purposes."
    tag = SkillTags.ATTRIBUTE
    
class ReactiveArt(SkillComponent):
    nid = 'reactive_art'
    desc = "Used to denote skills that primarily trigger when defending."
    tag = SkillTags.ATTRIBUTE
    
class CostUses(SkillComponent):
    nid = 'cost_uses'
    desc = "Skill costs alternate number of weapon uses. Unit must have at least that many uses."
    tag = SkillTags.CHARGE

    expose = ComponentType.Int
    value = 2
    
    ignore_conditional = True

    def condition(self, unit, item):
        return item and item.data.get('uses', 999) >= self.value
            
    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        if self.skill.data.get('active'):
            actions.append(action.SetObjData(item, 'uses', item.data['uses'] - self.value))
            
class CostUsesAlwaysOn(SkillComponent):
    nid = 'cost_uses_always_on'
    desc = "Skill costs alternate number of weapon uses. Unit must have at least that many uses. For non-combat art skills."
    tag = SkillTags.CHARGE

    expose = ComponentType.Int
    value = 2
    
    def condition(self, unit, item):
        return item.data.get('uses', 999) >= self.value
            
    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        actions.append(action.SetObjData(item, 'uses', item.data['uses'] - self.value))
                

class StrikeTrigger(SkillComponent):
    nid = 'strike_trigger'
    desc = "Skill counts as using a charge after a strike."
    tag = SkillTags.ADVANCED

    _did_something = False

    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        self._did_something = True

    def end_combat_unconditional(self, playback, unit, item, target, item2, mode):
        if self._did_something:
            action.do(action.TriggerCharge(unit, self.skill))
        self._did_something = False
        
class EventBeforeCombat(SkillComponent):
    nid = 'event_before_combat'
    desc = 'Calls event before any combat'
    tag = SkillTags.ADVANCED

    expose = ComponentType.Event
    value = ''

    def start_combat(self, playback, unit: UnitObject, item, target: UnitObject, item2, mode):
        game.events.trigger_specific_event(self.value, unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode})
        
class EventAfterCombat(SkillComponent):
    nid = 'event_after_combat'
    desc = 'calls event after combat'
    tag = SkillTags.ADVANCED

    expose = ComponentType.Event
    value = ''

    def end_combat(self, playback, unit: UnitObject, item, target: UnitObject, item2, mode):
        game.events.trigger_specific_event(self.value, unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode})
