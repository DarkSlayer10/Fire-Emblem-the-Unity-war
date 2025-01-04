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
import app.engine.combat.playback as pb

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

class EndstepEvent(SkillComponent):
    nid = 'endstep_event'
    desc = "Triggers the designated event at endstep"
    tag = SkillTags.TIME

    expose = ComponentType.Event
    value = ''

    def on_endstep(self, actions, playback, unit):
        game.events.trigger_specific_event(self.value, unit, None, unit.position, local_args={})

class DynamicResistMultiplier(SkillComponent):
    nid = 'dynamic_resist_multiplier'
    desc = "Multiplies damage taken by a fraction"
    tag = SkillTags.COMBAT

    expose = ComponentType.String

    def resist_multiplier(self, unit, item, target, item2, mode, attack_info, base_value):
        from app.engine import evaluate
        try:
            local_args = {'item': item, 'item2': item2, 'mode': mode, 'skill': self.skill, 'attack_info': attack_info, 'base_value': base_value}
            return float(evaluate.evaluate(self.value, unit, target, unit.position, local_args))
        except Exception:
            print("Couldn't evaluate %s conditional" % self.value)
            return 1
            
class DefenseProcWhenHit(SkillComponent):
    nid = 'defense_proc_when_hit'
    desc = "Allows skill to proc when defending a single strike, only consumes charges when hit"
    tag = SkillTags.ADVANCED

    expose = ComponentType.Skill
    _did_action = False
    _got_hit = False

    def start_sub_combat(self, actions, playback, unit, item, target, item2, mode, attack_info):
        if mode == 'defense' and target and skill_system.check_enemy(unit, target):
            if not get_weapon_filter(self.skill, unit, item):
                return
            proc_rate = get_proc_rate(unit, self.skill)
            if static_random.get_combat() < proc_rate:
                act = action.AddSkill(unit, self.value)
                action.do(act)
                if act.skill_obj:
                    playback.append(pb.DefenseProc(unit, act.skill_obj))
                self._did_action = True
                
    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        if strike != Strike.MISS:
            self._got_hit = True

    def end_sub_combat(self, actions, playback, unit, item, target, item2, mode, attack_info):
        if self._did_action:
            if self._got_hit:
                action.do(action.TriggerCharge(unit, self.skill))
            action.do(action.RemoveSkill(unit, self.value))
        self._got_hit = False
        self._did_action = False
        
def get_proc_rate(unit, skill) -> int:
    for component in skill.components:
        if component.defines('proc_rate'):
            return component.proc_rate(unit)
    return 100  # 100 is default


def get_weapon_filter(skill, unit, item) -> bool:
    for component in skill.components:
        if component.defines('weapon_filter'):
            return component.weapon_filter(unit, item)
    return True