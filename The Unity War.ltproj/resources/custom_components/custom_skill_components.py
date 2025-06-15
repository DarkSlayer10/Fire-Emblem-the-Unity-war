from __future__ import annotations

from app.data.database.components import ComponentType
from app.data.database.database import DB
from app.data.database.skill_components import SkillComponent, SkillTags
from app.engine import (action, banner, combat_calcs, engine, equations,
                        image_mods, item_funcs, item_system, skill_system,
                        target_system)
from app.engine.game_state import game
from app.engine.objects.unit import UnitObject

from app.utilities import utils, static_random
from app.engine.combat import playback as pb
from app.utilities.enums import Strike

from app.data.database.item_components import ItemComponent, ItemTags

from app.engine.skill_components import advanced_components

from app.data.resources.resources import RESOURCES
from app.engine import config as cf

import random, logging



class DoNothing(SkillComponent):
    nid = 'do_nothing'
    desc = 'does nothing'
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 1

class SavageBlowFates(SkillComponent):
    nid = 'savage_blow_fates'
    desc = 'Deals 20% Current HP damage to enemies within the given number of spaces from target.'
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 0
    author = 'Lord_Tweed'

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target):
            r = set(range(self.value+1))
            locations = game.target_system.get_shell({target.position}, r, game.board.bounds)
            for loc in locations:
                target2 = game.board.get_unit(loc)
                if target2 and target2 is not target and skill_system.check_enemy(unit, target2):
                    end_health = target2.get_hp() - (int(target2.get_hp() * .2))
                    action.do(action.SetHP(target2, max(1, end_health)))

class LostOnTakeHit(SkillComponent):
    nid = 'lost_on_take_hit'
    desc = "This skill is lost when receiving an attack (it must hit)"
    tag = SkillTags.CUSTOM

    author = 'Lord_Tweed'

    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        if target and skill_system.check_enemy(unit, target) and strike == Strike.HIT:
            action.do(action.RemoveSkill(unit, self.skill))

class EventOnTakeHit(SkillComponent):
    nid = 'event_stack_on_take_hit'
    desc = "An event procs when receiving an attack (it must hit)"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Event
    value = ''

    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        if target and skill_system.check_enemy(unit, target) and strike == Strike.HIT:
            game.events.trigger_specific_event(self.value, unit, unit, unit.position, {'item': None, 'mode': None})
        
class LostOnStrike(SkillComponent):
    nid = 'lost_on_strike'
    desc = "This skill is after performing a strike (hit or miss)"
    tag = SkillTags.CUSTOM

    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        action.do(action.RemoveSkill(unit, self.skill))
        
class GainSkillOnStrike(SkillComponent):
    nid = 'gain_on_strike'
    desc = "Gain skill after performing a strike (hit or miss)"
    tag = SkillTags.CUSTOM
    
    expose = ComponentType.Skill

    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        action.do(action.AddSkill(unit, self.value))

class SelfNihil(SkillComponent):
    nid = 'self_nihil'
    desc = "Skill does not work if the unit has this other skill"
    tag = SkillTags.CUSTOM

    expose = (ComponentType.List, ComponentType.Skill)
    value = []

    ignore_conditional = True

    def condition(self, unit, item):
        all_target_nihils = set(self.value)
        for skill in unit.skills:
          if skill.nid in all_target_nihils:
            return False
        return True

class SelfRecoil(SkillComponent):
    nid = 'self_recoil'
    desc = "Unit takes non-lethal damage after any combat"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 0
    author = 'Lord_Tweed'

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target:
            end_health = unit.get_hp() - self.value
            action.do(action.SetHP(unit, max(1, end_health)))
            action.do(action.TriggerCharge(unit, self.skill))

class EvalGaleforce(SkillComponent):
    nid = 'eval_galeforce'
    desc = "Unit can move again if conditions are met. Value must resolve to a Boolean."
    tag = SkillTags.CUSTOM

    expose = ComponentType.String
    value = ''
    author = 'Lord_Tweed'

    def end_combat(self, playback, unit, item, target, item2, mode):
        from app.engine import evaluate
        try:
            x = bool(evaluate.evaluate(self.value, unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode}))
            if x:
                action.do(action.Reset(unit))
                action.do(action.TriggerCharge(unit, self.skill))
        except Exception as e:
            print("%s: Could not evaluate EvalGaleforce condition %s" % (e, self.value))

class UpkeepEvent(SkillComponent):
    nid = 'upkeep_event'
    desc = "Triggers the designated event at upkeep"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Event
    value = ''

    def on_upkeep(self, actions, playback, unit):
        game.events.trigger_specific_event(self.value, unit, unit, unit.position, {'item': None, 'mode': None})

class CritEvent(SkillComponent):
    nid = 'crit_event'
    desc = "Triggers the designated event on crit"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Event
    value = ''

    def end_combat(self, playback, unit, item, target, item2, mode):
        mark_playbacks = [p for p in playback if p.nid in ('mark_crit')]
        if target and any(p.attacker is unit for p in mark_playbacks):
            game.events.trigger_specific_event(self.value, unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode})

class UpkeepSkillGain(SkillComponent):
    nid = 'upkeep_skill_gain'
    desc = "Grants the designated skill at upkeep"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Skill

    def on_upkeep(self, actions, playback, unit):
        action.do(action.AddSkill(unit, self.value))

class EndstepSkillGain(SkillComponent):
    nid = 'endstep_skill_gain'
    desc = "Grants the designated skill at endstep"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Skill

    def on_endstep(self, actions, playback, unit):
        action.do(action.AddSkill(unit, self.value))

class LostOnEndNextCombat(SkillComponent):
    nid = 'lost_on_end_next_combat'
    desc = "Remove after subsequent combat"
    tag = SkillTags.CUSTOM

    author = "Xilirite"
    expose = (ComponentType.MultipleOptions)

    value = [["NumberOfCombats (X)", "2", 'Number of combats before expiration'],["LostOnSelf (T/F)", "T", 'Lost after self combat (e.g. vulnerary)'],["LostOnAlly (T/F)", "T", 'Lost after combat with an ally'],["LostOnEnemy (T/F)", "T", 'Lost after combat with an enemy'],["LostOnSplash (T/F)", "T", 'Lost after combat if using an AOE item']]

    def init(self, skill):
        self.skill.data['combats'] = self.values.get('NumberOfCombats (X)', '2')

    @property
    def values(self) -> Dict[str, str]:
        return {value[0]: value[1] for value in self.value}

    def post_combat(self, playback, unit, item, target, item2, mode):
        from app.engine import skill_system
        remove_skill = False
        if self.values.get('LostOnSelf (T/F)', 'T') == 'T':
            if unit == target:
                val = int(self.skill.data['combats']) - 1
                action.do(action.SetObjData(self.skill, 'combats', val))
                if int(self.skill.data['combats']) <= 0:
                    remove_skill = True

        if self.values.get('LostOnAlly (T/F)', 'T') == 'T':
            if target:
                if skill_system.check_ally(unit, target):
                    val = int(self.skill.data['combats']) - 1
                    action.do(action.SetObjData(self.skill, 'combats', val))
                    if int(self.skill.data['combats']) <= 0:
                        remove_skill = True
        if self.values.get('LostOnEnemy (T/F)', 'T') == 'T':
            if target:
                if skill_system.check_enemy(unit, target):
                    val = int(self.skill.data['combats']) - 1
                    action.do(action.SetObjData(self.skill, 'combats', val))
                    if int(self.skill.data['combats']) <= 0:
                        remove_skill = True
        if self.values.get('LostOnSplash (T/F)', 'T') == 'T':
            if not target:
                val = int(self.skill.data['combats']) - 1
                action.do(action.SetObjData(self.skill, 'combats', val))
                if int(self.skill.data['combats']) <= 0:
                    remove_skill = True

        if remove_skill:
            action.do(action.RemoveSkill(unit, self.skill))

    def on_end_chapter(self, unit, skill):
        action.do(action.RemoveSkill(unit, self.skill))

class FullMiracle(SkillComponent):
    nid = 'full_miracle'
    desc = "Unit will not die after combat, but will instead be resurrected with full hp"
    tag = SkillTags.CUSTOM

    def cleanup_combat(self, playback, unit, item, target, item2, mode):
        if unit.get_hp() <= 0:
            action.do(action.SetHP(unit, unit.get_max_hp()))
            game.death.miracle(unit)
            action.do(action.TriggerCharge(unit, self.skill))

class UndamagedCondition(SkillComponent):
    nid = 'undamaged_condition'
    desc = "Skill is active while unit has not taken damage this chapter"
    tag = SkillTags.CUSTOM
    author = 'rainlash'

    ignore_conditional = True

    _took_damage_this_combat = False

    def init(self, skill):
        self.skill.data['_has_taken_damage'] = False

    def condition(self, unit):
        return not self.skill.data['_has_taken_damage']

    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        for act in reversed(actions):
            if isinstance(act, action.ChangeHP) and act.num < 0 and act.unit == unit:
                self._took_damage_this_combat = True
                break

    def end_combat(self, playback, unit, item, target, item2, mode):
        if self._took_damage_this_combat:
            action.do(action.SetObjData(self.skill, '_has_taken_damage', True))
        self._took_damage_this_combat = False

    def on_end_chapter(self, unit, skill):
        self.skill.data['_has_taken_damage'] = False
        self._took_damage_this_combat = False

class CombatTriggerCharge(SkillComponent):
    nid = 'combat_trigger_charge'
    desc = "This skill will triger a charge usage as long as combat was with an enemy. A hit must have been landed."
    tag = SkillTags.CUSTOM
    author = 'Lord_Tweed'

    def end_combat(self, playback, unit, item, target, item2, mode):
        mark_playbacks = [p for p in playback if p.nid in ('mark_hit', 'mark_crit')]
        if target and skill_system.check_enemy(unit, target) and any(p.attacker == unit for p in mark_playbacks):
            action.do(action.TriggerCharge(unit, self.skill))

class HealOnKill(SkillComponent):
    nid = 'heal_on_kill'
    desc = 'Gives +X health on kill'
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int

    value = 0

    def end_combat(self, playback, unit, item, target, item2, mode):
        mark_playbacks = [p for p in playback if p.nid in ('mark_miss', 'mark_hit', 'mark_crit')]
        if target and target.get_hp() <= 0:
            heal = self.value
            action.do(action.ChangeHP(unit, heal))

class EvalRegeneration(SkillComponent):
    nid = 'eval_regeneration'
    desc = "Unit restores HP at beginning of turn, based on the given evaluation"
    tag = SkillTags.CUSTOM

    expose = ComponentType.String

    def on_upkeep(self, actions, playback, unit):
        max_hp = equations.parser.hitpoints(unit)
        if unit.get_hp() < max_hp:
            from app.engine import evaluate
            try:
                hp_change = int(evaluate.evaluate(self.value, unit))
            except:
                logging.error("Couldn't evaluate %s conditional" % self.value)
                hp_change = 0
            actions.append(action.ChangeHP(unit, hp_change))
            if hp_change > 0:
                # Playback
                playback.append(pb.HitSound('MapHeal'))
                playback.append(pb.DamageNumbers(unit, -hp_change))
                if hp_change >= 30:
                    name = 'MapBigHealTrans'
                elif hp_change >= 15:
                    name = 'MapMediumHealTrans'
                else:
                    name = 'MapSmallHealTrans'
                playback.append(pb.CastAnim(name))

class CannotUseItemsOnEnemy(SkillComponent):
    nid = 'cannot_use_items_enemy'
    desc = "Unit cannot use or equip any items that target specifically enemies"
    tag = SkillTags.CUSTOM

    def available(self, unit, item) -> bool:
        return not item.target_enemy
        
class EventAfterKill(SkillComponent):
    nid = 'event_after_kill'
    desc = "Triggers event after a kill"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Event

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and target.get_hp() <= 0:
            game.events.trigger_specific_event(self.value, unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode})
            action.do(action.TriggerCharge(unit, self.skill))

class PermanentDamage(SkillComponent):
    nid = 'permanent_damage'
    desc = 'All damage taken is dealt to max HP'
    tag = SkillTags.CUSTOM
    
    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        stat_changes = {}
        if unit.get_max_hp() > int(unit._fields['Undeath_Current_HP']):
            for i in range(unit.get_max_hp() - int(unit._fields['Undeath_Current_HP'])):
                action.do(action.AddSkill(unit, 'Undying_Will'))
            stat_changes['HP'] = int(unit._fields['Undeath_Current_HP']) - unit.get_max_hp()
            action.do(action.ApplyStatChanges(unit, stat_changes, False))
        elif unit.get_max_hp() < int(unit._fields['Undeath_Current_HP']):
            action.do(action.RemoveSkill(unit, 'Undying_Will', count=(int(unit._fields['Undeath_Current_HP']) - unit.get_max_hp())))
            stat_changes['HP'] = min(int(unit._fields['Undeath_Current_HP']) - unit.get_max_hp(), len([skill.nid for skill in unit.skills if skill.nid == 'Undying_Will']) - unit.get_max_hp())
            action.do(action.ApplyStatChanges(unit, stat_changes, False))
        stat_changes['HP'] = max(unit.get_hp() - unit.get_max_hp(), 1 - unit.get_max_hp())
        action.do(action.ApplyStatChanges(unit, stat_changes, False))
        action.do(action.ChangeField(unit, key='Undeath_Current_HP', value=unit.get_max_hp()))

    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        stat_changes = {}
        if unit.get_max_hp() > int(unit._fields['Undeath_Current_HP']):
            for i in range(unit.get_max_hp() - int(unit._fields['Undeath_Current_HP'])):
                action.do(action.AddSkill(unit, 'Undying_Will'))
            stat_changes['HP'] = int(unit._fields['Undeath_Current_HP']) - unit.get_max_hp()
            action.do(action.ApplyStatChanges(unit, stat_changes, False))
        elif unit.get_max_hp() < int(unit._fields['Undeath_Current_HP']):
            action.do(action.RemoveSkill(unit, 'Undying_Will', count=(int(unit._fields['Undeath_Current_HP']) - unit.get_max_hp())))
            stat_changes['HP'] = min(int(unit._fields['Undeath_Current_HP']) - unit.get_max_hp(), len([skill.nid for skill in unit.skills if skill.nid == 'Undying_Will']) - unit.get_max_hp())
            action.do(action.ApplyStatChanges(unit, stat_changes, False))
        stat_changes['HP'] = max(unit.get_hp() - unit.get_max_hp(), 1 - unit.get_max_hp())
        action.do(action.ApplyStatChanges(unit, stat_changes, False))
        action.do(action.ChangeField(unit, key='Undeath_Current_HP', value=unit.get_max_hp()))
        
    def cleanup_combat(self, playback, unit, item, target, item2, mode):
        stat_changes = {}
        if unit.get_max_hp() > int(unit._fields['Undeath_Current_HP']):
            for i in range(unit.get_max_hp() - int(unit._fields['Undeath_Current_HP'])):
                action.do(action.AddSkill(unit, 'Undying_Will'))
            stat_changes['HP'] = int(unit._fields['Undeath_Current_HP']) - unit.get_max_hp()
            action.do(action.ApplyStatChanges(unit, stat_changes, False))
        elif unit.get_max_hp() < int(unit._fields['Undeath_Current_HP']):
            action.do(action.RemoveSkill(unit, 'Undying_Will', count=(int(unit._fields['Undeath_Current_HP']) - unit.get_max_hp())))
            stat_changes['HP'] = min(int(unit._fields['Undeath_Current_HP']) - unit.get_max_hp(), len([skill.nid for skill in unit.skills if skill.nid == 'Undying_Will']) - unit.get_max_hp())
            action.do(action.ApplyStatChanges(unit, stat_changes, False))
        stat_changes['HP'] = max(unit.get_hp() - unit.get_max_hp(), 1 - unit.get_max_hp())
        action.do(action.ApplyStatChanges(unit, stat_changes, False))
        action.do(action.ChangeField(unit, key='Undeath_Current_HP', value=unit.get_max_hp()))
        
    def end_combat(self, playback, unit, item, target, item2, mode):
        print(unit.get_max_hp())
        print(int(unit._fields['Undeath_Current_HP']))
        stat_changes = {}
        if unit.get_max_hp() > int(unit._fields['Undeath_Current_HP']):
            for i in range(unit.get_max_hp() - int(unit._fields['Undeath_Current_HP'])):
                action.do(action.AddSkill(unit, 'Undying_Will'))
            stat_changes['HP'] = int(unit._fields['Undeath_Current_HP']) - unit.get_max_hp()
            action.do(action.ApplyStatChanges(unit, stat_changes, False))
        elif unit.get_max_hp() < int(unit._fields['Undeath_Current_HP']):
            action.do(action.RemoveSkill(unit, 'Undying_Will', count=(int(unit._fields['Undeath_Current_HP']) - unit.get_max_hp())))
            stat_changes['HP'] = min(int(unit._fields['Undeath_Current_HP']) - unit.get_max_hp(), len([skill.nid for skill in unit.skills if skill.nid == 'Undying_Will']) - unit.get_max_hp())
            action.do(action.ApplyStatChanges(unit, stat_changes, False))
        stat_changes['HP'] = max(unit.get_hp() - unit.get_max_hp(), 1 - unit.get_max_hp())
        action.do(action.ApplyStatChanges(unit, stat_changes, False))
        action.do(action.ChangeField(unit, key='Undeath_Current_HP', value=unit.get_max_hp()))

class EvalUpkeepDamage(SkillComponent):
    nid = 'eval_upkeep_damage'
    desc = "Unit takes damage at upkeep based on eval"
    tag = SkillTags.CUSTOM

    expose = ComponentType.String

    def _playback_processing(self, playback, unit, hp_change):
        # Playback
        if hp_change < 0:
            playback.append(pb.HitSound('Attack Hit ' + str(static_random.get_randint(1, 5))))
            playback.append(pb.UnitTintAdd(unit, (255, 255, 255)))
            playback.append(pb.DamageNumbers(unit, abs(hp_change)))
        elif hp_change > 0:
            playback.append(pb.HitSound('MapHeal'))
            if hp_change >= 30:
                name = 'MapBigHealTrans'
            elif hp_change >= 15:
                name = 'MapMediumHealTrans'
            else:
                name = 'MapSmallHealTrans'
            playback.append(pb.CastAnim(name))
            playback.append(pb.DamageNumbers(unit, abs(hp_change)))

    def on_upkeep(self, actions, playback, unit):
        from app.engine import evaluate
        try:
            hp_change = -int(evaluate.evaluate(self.value, unit))
        except:
            logging.error("Couldn't evaluate %s conditional" % self.value)
            hp_change = 0
        actions.append(action.ChangeHP(unit, hp_change))
        actions.append(action.TriggerCharge(unit, self.skill))
        self._playback_processing(playback, unit, hp_change)
        skill_system.after_take_strike(actions, playback, unit, None, None, None, 'defense', (0, 0), Strike.HIT)

class CopySafe(SkillComponent):
    nid = 'copysafe'
    desc = "Skill is safe to copy to other units. If there are dependant skills, include them as the values."
    tag = SkillTags.CUSTOM
    
    expose = (ComponentType.List, ComponentType.Skill)

class AbilityAttackCharge(SkillComponent):
    nid = 'ability_attack_charge'
    desc = "Give unit an item as an extra ability, only costs charges when attacking"
    tag = SkillTags.ADVANCED

    expose = ComponentType.Item

    def extra_ability(self, unit):
        item_uid = self.skill.data.get('ability_item_uid', None)
        if item_uid and game.item_registry.get(item_uid, None):
            return game.item_registry[item_uid]
        else:
            new_item = item_funcs.create_item(unit, self.value)
            self.skill.data['ability_item_uid'] = new_item.uid
            game.register_item(new_item)
            return new_item

    def end_combat_unconditional(self, playback, unit, item, target, item2, mode):
        if item and item.nid == self.value and mode == 'attack':
            action.do(action.TriggerCharge(unit, self.skill))

class Inherited(SkillComponent):
    nid = 'inherited'
    desc = "Don't actually put this on skills, please and thank you."
    tag = SkillTags.CUSTOM

class GainSkillAfterCrit(SkillComponent):
    nid = 'gain_skill_after_crit'
    desc = "Gives a skill to user after a crit"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Skill

    def end_combat(self, playback, unit, item, target, item2, mode):
        mark_playbacks = [p for p in playback if p.nid in (
            'mark_crit')]
        if target and any(p.attacker is unit and (p.main_attacker is unit or p.attacker is p.main_attacker.strike_partner)
                          for p in mark_playbacks):  # Unit is overall attacker
            action.do(action.AddSkill(unit, self.value, target))
            action.do(action.TriggerCharge(unit, self.skill))

class ActiveCombatChargeIncrease(SkillComponent):
    nid = 'active_combat_charge_increase'
    desc = "Increases charge of skill each combat, if unit initiated"
    tag = SkillTags.CHARGE

    expose = ComponentType.Int
    value = 1

    ignore_conditional = True

    def end_combat(self, playback, unit, item, target, item2, mode):
        mark_playbacks = [p for p in playback if p.nid in (
            'mark_miss', 'mark_hit', 'mark_crit')]
        if not self.skill.data.get('active') and target and any(p.attacker is unit and (p.main_attacker is unit or p.attacker is p.main_attacker.strike_partner) for p in mark_playbacks):
            new_value = self.skill.data['charge'] + self.value
            new_value = min(new_value, self.skill.data['total_charge'])
            action.do(action.SetObjData(self.skill, 'charge', new_value))
            
class AdditionalInventory(SkillComponent):
    nid = 'additional_inventory'
    desc = "Unit can hold additional regular items rather than accessories"
    tag = SkillTags.BASE

    expose = ComponentType.Int
    value = 2

    def num_items_offset(self, unit) -> int:
        return self.value

    def num_accessories_offset(self, unit) -> int:
        return -1 * self.value

class GiveStatusOnTakeHit(SkillComponent):
    nid = 'give_status_on_take_hit'
    desc = "When receiving an attack, give a status to the attacker"
    tag = SkillTags.CUSTOM
    author = 'Lord_Tweed'
    
    expose = ComponentType.Skill

    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        if target:
            actions.append(action.AddSkill(target, self.value, unit))
            actions.append(action.TriggerCharge(unit, self.skill))

class Dazzled(SkillComponent):
    nid = 'dazzled'
    desc = "Skill is treated as Dazzled. Allows us to have multiple different skills that are treated the same way."
    tag = SkillTags.CUSTOM

class Blinded(SkillComponent):
    nid = 'blinded'
    desc = "Skill is treated as Blinded. Allows us to have multiple different skills that are treated the same way."
    tag = SkillTags.CUSTOM

class Paragon(SkillComponent):
    nid = 'paragon'
    desc = "Skill is treated as Paragon. Allows us to have multiple different skills that are treated the same way."
    tag = SkillTags.CUSTOM

class TetherParameters(SkillComponent):
    nid = 'tether_parameters'
    desc = "Skill can be purchased in the Skill Shop. The cost should not exceed 50."
    tag = SkillTags.CUSTOM

    expose = (ComponentType.NewMultipleOptions)
    options = {
        "cost": ComponentType.Int,
        "level": ComponentType.Int,
    }
    
    def __init__(self, value=None):
        self.value = {
            "cost": 0,
            "level": 0,
        }
        if value:
            self.value.update(value)

class SavageStatus(SkillComponent):
    nid = 'savage_status'
    desc = 'Inflicts the given status to enemies within the given number of spaces from target.'
    tag = SkillTags.CUSTOM
    author = 'Lord_Tweed'

    expose = (ComponentType.NewMultipleOptions)
    options = {
        "status": ComponentType.Skill,
        "range": ComponentType.Int,
    }
    
    def __init__(self, value=None):
        self.value = {
            "status": 'Canto',
            "range": 1,
        }
        if value:
            self.value.update(value)

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target):
            r = set(range(self.value.get('range') + 1))
            locations = game.target_system.get_shell({target.position}, r, game.board.bounds)
            for loc in locations:
                target2 = game.board.get_unit(loc)
                if target2 and target2 is not target and skill_system.check_enemy(unit, target2):
                    action.do(action.AddSkill(target2, self.value.get('status'), unit))

class VisualCharge(SkillComponent):
    nid = 'visual_charge'
    desc = "Skill displays charges, but does not actually use them itself. Unaffected by Trigger Charge."
    tag = SkillTags.CHARGE
    author = 'Lord_Tweed'

    expose = ComponentType.Int
    value = 5

    ignore_conditional = True

    def init(self, skill):
        self.skill.data['charge'] = 0
        self.skill.data['total_charge'] = self.value

    def condition(self, unit, item):
        return True

    def on_end_chapter(self, unit, skill):
        self.skill.data['charge'] = 0

    def text(self) -> str:
        return str(self.skill.data['charge'])

    def cooldown(self):
        return 1

class RemoveStatusAfterCombat(SkillComponent):
    nid = 'remove_status_after_combat'
    desc = "Removes a status from target enemy after combat"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Skill

    def end_combat(self, playback, unit, item, target, item2, mode):
        from app.engine import skill_system
        if target and skill_system.check_enemy(unit, target):
            action.do(action.RemoveSkill(target, self.value))
            action.do(action.TriggerCharge(unit, self.skill))

def get_weapon_filter(skill, unit, item) -> bool:
    for component in skill.components:
        if component.defines('weapon_filter'):
            return component.weapon_filter(unit, item)
    return True

def get_proc_rate_with_target(unit, target, skill) -> int:
    for component in skill.components:
        if component.defines('proc_rate'):
            return component.proc_rate(unit, target)
    return 100  # 100 is default

class EvalProcRate(SkillComponent):
    nid = 'eval_proc_rate'
    desc = "Evaluates the proc rate. Only compatible with custom Proc components."
    tag = SkillTags.CUSTOM

    expose = ComponentType.String

    def proc_rate(self, unit, target):
        from app.engine import evaluate
        try:
            return int(evaluate.evaluate(self.value, unit, target))
        except:
            logging.error("Couldn't evaluate %s conditional" % self.value)
        return 0

class AttackProcWithTarget(SkillComponent):
    nid = 'attack_proc_with_target'
    desc = "Allows skill to proc on a single attacking strike. Target is passed into the Proc Rate method. Only use this with custom Proc Rate components."
    tag = SkillTags.CUSTOM

    expose = ComponentType.Skill
    _did_action = False

    def start_sub_combat(self, actions, playback, unit, item, target, item2, mode, attack_info):
        if mode == 'attack' and target and skill_system.check_enemy(unit, target):
            if not get_weapon_filter(self.skill, unit, item):
                return
            proc_rate = get_proc_rate_with_target(unit, target, self.skill)
            if static_random.get_combat() < proc_rate:
                act = action.AddSkill(unit, self.value)
                action.do(act)
                if act.skill_obj:
                    playback.append(pb.AttackProc(unit, act.skill_obj))
                self._did_action = True

    def end_sub_combat(self, actions, playback, unit, item, target, item2, mode, attack_info):
        if self._did_action:
            action.do(action.TriggerCharge(unit, self.skill))
            action.do(action.RemoveSkill(unit, self.value))
        self._did_action = False

class DefenseProcWithTarget(SkillComponent):
    nid = 'defense_proc_with_target'
    desc = "Allows skill to proc when defending a single strike. Target is passed into the Proc Rate method. Only use this with custom Proc Rate components."
    tag = SkillTags.CUSTOM

    expose = ComponentType.Skill
    _did_action = False

    def start_sub_combat(self, actions, playback, unit, item, target, item2, mode, attack_info):
        if mode == 'defense' and target and skill_system.check_enemy(unit, target):
            if not get_weapon_filter(self.skill, unit, item):
                return
            proc_rate = get_proc_rate_with_target(unit, target, self.skill)
            if static_random.get_combat() < proc_rate:
                act = action.AddSkill(unit, self.value)
                action.do(act)
                if act.skill_obj:
                    playback.append(pb.DefenseProc(unit, act.skill_obj))
                self._did_action = True

    def end_sub_combat(self, actions, playback, unit, item, target, item2, mode, attack_info):
        if self._did_action:
            action.do(action.TriggerCharge(unit, self.skill))
            action.do(action.RemoveSkill(unit, self.value))
        self._did_action = False

class CombatArtProc(SkillComponent):
    nid = 'combat_art_proc'
    desc = "Skill is procced from a Combat Art."
    tag = SkillTags.CUSTOM

class UpkeepAOESkillGain(SkillComponent):
    nid = 'upkeep_aoe_skill_gain'
    desc = "Grants the designated skill at upkeep to units in an AoE around owner. Can optionally affect user as well."
    tag = SkillTags.CUSTOM
    author = 'Lord_Tweed'

    expose = (ComponentType.NewMultipleOptions)
    options = {
        "skill": ComponentType.Skill,
        "range": ComponentType.Int,
        "affect_self": ComponentType.Bool,
        "target": (ComponentType.MultipleChoice, ('ally', 'enemy', 'any')),
    }
    
    def __init__(self, value=None):
        self.value = {
            "skill": 'Canto',
            "range": 1,
            "affect_self": False,
            "target": 'ally',
        }
        if value:
            self.value.update(value)

    def on_upkeep(self, actions, playback, unit):
        r = set(range(self.value.get('range') + 1))
        locations = game.target_system.get_shell({unit.position}, r, game.board.bounds)
        for loc in locations:
            target2 = game.board.get_unit(loc)
            if target2 and target2 is not unit and self.value.get('target') in ['enemy','any'] and skill_system.check_enemy(unit, target2):
                action.do(action.AddSkill(target2, self.value.get('skill'), unit))
            elif target2 and target2 is not unit and self.value.get('target') in ['ally','any'] and skill_system.check_ally(unit, target2):
                action.do(action.AddSkill(target2, self.value.get('skill'), unit))

        if self.value.get('affect_self'):
            action.do(action.AddSkill(unit, self.value.get('skill'), unit))

class EndstepAOESkillGain(SkillComponent):
    nid = 'endstep_aoe_skill_gain'
    desc = "Grants the designated skill at endstep to units in an AoE around owner. Can optionally affect user as well."
    tag = SkillTags.CUSTOM
    author = 'Lord_Tweed'

    expose = (ComponentType.NewMultipleOptions)
    options = {
        "skill": ComponentType.Skill,
        "range": ComponentType.Int,
        "affect_self": ComponentType.Bool,
        "target": (ComponentType.MultipleChoice, ('ally', 'enemy', 'any')),
    }
    
    def __init__(self, value=None):
        self.value = {
            "skill": 'Canto',
            "range": 1,
            "affect_self": False,
            "target": 'ally',
        }
        if value:
            self.value.update(value)

    def on_endstep(self, actions, playback, unit):
        r = set(range(self.value.get('range') + 1))
        locations = game.target_system.get_shell({unit.position}, r, game.board.bounds)
        for loc in locations:
            target2 = game.board.get_unit(loc)
            if target2 and target2 is not unit and self.value.get('target') in ['enemy','any'] and skill_system.check_enemy(unit, target2):
                action.do(action.AddSkill(target2, self.value.get('skill'), unit))
            elif target2 and target2 is not unit and self.value.get('target') in ['ally','any'] and skill_system.check_ally(unit, target2):
                action.do(action.AddSkill(target2, self.value.get('skill'), unit))

        if self.value.get('affect_self'):
            action.do(action.AddSkill(unit, self.value.get('skill'), unit))

class FatalDamage(SkillComponent):
    nid = 'fatal_damage'
    desc = "Skill can deal fatal damage. Use on statuses such as Poison, Bleed, Infection, etc."
    tag = SkillTags.CUSTOM

class FatalBlock(SkillComponent):
    nid = 'fatal_block'
    desc = "This skill should prevent death from fatal damage statuses. Use on statuses such as Legend, Hope for Humanity, etc."
    tag = SkillTags.CUSTOM
    
class TrueMiracleEvent(SkillComponent):
    nid = 'True_Miracle_Event'
    desc = "Unit cannot go beneath 1 HP. An event will occur once this effect triggers."
    tag = SkillTags.COMBAT2
    
    expose = ComponentType.Event
    value = ''

    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        did_something = False
        for act in reversed(actions):
            if isinstance(act, action.ChangeHP) and -act.num >= act.old_hp and act.unit == unit:
                act.num = -act.old_hp + 1
                did_something = True
                playback.append(pb.DefenseHitProc(unit, self.skill))

        if did_something:
            actions.append(action.TriggerCharge(unit, self.skill))
            game.events.trigger_specific_event(self.value, unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode})

class GiveStatusesOnTakeHit(SkillComponent):
    nid = 'give_statuses_on_take_hit'
    desc = "When receiving an attack, give statuses to the attacker"
    tag = SkillTags.CUSTOM
    author = 'Lord_Tweed'
    
    expose = (ComponentType.List, ComponentType.Skill)

    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        if target:
            for skill_nid in self.value:
                actions.append(action.AddSkill(target, skill_nid, unit))
            actions.append(action.TriggerCharge(unit, self.skill))

class GainSkillAfterCombatOnTakeHit(SkillComponent):
    nid = 'gain_skill_after_combat_on_take_hit'
    desc = "Gain a skill after combat if an enemy hits you"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Skill

    def end_combat(self, playback, unit, item, target, item2, mode):
        mark_playbacks = [p for p in playback if p.nid in (
            'mark_hit', 'mark_crit')]
        if target and any(p.defender is unit for p in mark_playbacks):  # Unit is overall defender
            action.do(action.AddSkill(unit, self.value, unit))
            action.do(action.TriggerCharge(unit, self.skill))

class KillChargeIncrease(SkillComponent):
    nid = 'kill_charge_increase'
    desc = "Increases charge of skill when slaying a foe"
    tag = SkillTags.CHARGE

    expose = ComponentType.Int
    value = 1

    ignore_conditional = True

    def end_combat(self, playback, unit, item, target, item2, mode):
        if not self.skill.data.get('active') and target and target.get_hp() <= 0:
            new_value = self.skill.data['charge'] + self.value
            new_value = min(new_value, self.skill.data['total_charge'])
            action.do(action.SetObjData(self.skill, 'charge', new_value))

class NullSweep(SkillComponent):
    nid = 'null_sweep'
    desc = "Checked by evals to determine whether sweeping effects should occur."
    tag = SkillTags.CUSTOM

class CombatArtAll(SkillComponent):
    nid = 'combat_art_all'
    desc = "Combat Art also triggers charge for the designated skill for all allies."
    tag = SkillTags.CUSTOM

    expose = ComponentType.Skill

    def end_combat_unconditional(self, playback, unit, item, target, item2, mode):
        if self.skill.data.get('active'):
            for ally in game.get_all_units_in_party():
                if ally.nid != unit.nid and self.value in [s.nid for s in ally.skills]:
                    action.do(action.TriggerCharge(ally, ally.get_skill(self.value)))

class GrowthChangeExpression(SkillComponent):
    nid = 'growth_change_expression'
    desc = "Gives growth rate % bonuses dynamically"
    tag = SkillTags.COMBAT

    expose = (ComponentType.StringDict, ComponentType.Stat)
    value = []

    def growth_change(self, unit):
        from app.engine import evaluate
        try:
            return {stat[0]: int(evaluate.evaluate(stat[1], unit)) for stat in self.value}
        except Exception as e:
            logging.error("Couldn't evaluate conditional for skill %s: [%s], %s", self.skill.nid, str(self.value), e)
        return {stat[0]: 0 for stat in self.value}
        
class ShittyLifelink(SkillComponent):
    nid = 'shitty_lifelink'
    desc = "Heals user %% of damage dealt ignoring current HP"
    tag = SkillTags.COMBAT2

    expose = ComponentType.Float
    value = 0.5

    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        total_damage_dealt = 0
        playbacks = [p for p in playback if p.nid in (
            'damage_hit', 'damage_crit') and p.attacker == unit]
        for p in playbacks:
            total_damage_dealt += p.damage

        damage = utils.clamp(total_damage_dealt, 0, total_damage_dealt)
        true_damage = int(damage * self.value)
        actions.append(action.ChangeHP(unit, true_damage))

        playback.append(pb.HealHit(unit, item, unit, true_damage, true_damage))

        actions.append(action.TriggerCharge(unit, self.skill))
        
class AbilityDrainParentCharge(SkillComponent):
    nid = 'ability_parent'
    desc = "Give unit an item as an extra ability via a drain charge aura"
    tag = SkillTags.ADVANCED

    expose = ComponentType.Item

    def extra_ability(self, unit):
        item_uid = self.skill.data.get('ability_item_uid', None)
        if item_uid and game.item_registry.get(item_uid, None):
            return game.item_registry[item_uid]
        else:
            new_item = item_funcs.create_item(unit, self.value)
            self.skill.data['ability_item_uid'] = new_item.uid
            game.register_item(new_item)
            return new_item

    def end_combat_unconditional(self, playback, unit, item, target, item2, mode):
        if item and item.nid == self.value and self.skill.parent_skill and self.skill.parent_skill.owner_nid:
            action.do(action.TriggerCharge(game.get_unit(self.skill.parent_skill.owner_nid), self.skill.parent_skill))
        
class Shit(SkillComponent):
    nid = 'shit'
    desc = "Shit skill, bruv."
    tag = SkillTags.ATTRIBUTE
    
class BlueMagic(SkillComponent):
    nid = 'blue'
    desc = "Used to track Blue Magic skills"
    tag = SkillTags.ATTRIBUTE

class EvalLifelink(SkillComponent):
    nid = 'eval_lifelink'
    desc = "Heals user on hit based on Eval."
    tag = SkillTags.CUSTOM

    expose = ComponentType.String

    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        total_damage_dealt = 0
        playbacks = [p for p in playback if p.nid in (
            'damage_hit', 'damage_crit') and p.attacker == unit]
        for p in playbacks:
            total_damage_dealt += 1

        from app.engine import evaluate
        try:
            hp_change = int(evaluate.evaluate(self.value, unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode}))
        except:
            logging.error("Couldn't evaluate %s conditional" % self.value)
            hp_change = 0
        damage = hp_change * total_damage_dealt
        actions.append(action.ChangeHP(unit, damage))

        playback.append(pb.HealHit(unit, item, unit, damage, damage))

        actions.append(action.TriggerCharge(unit, self.skill))

class HasAffinities(SkillComponent):
    nid = 'has_affinities'
    desc = 'Skill grants the following affinities to the unit'
    tag = SkillTags.ATTRIBUTE

    expose = (ComponentType.List, ComponentType.Affinity)

class Subskills(SkillComponent):
    nid = 'subskills'
    desc = "This skill is not copy safe, but has underlying associated skills that should be removed with this skill."
    tag = SkillTags.CUSTOM
    
    expose = (ComponentType.List, ComponentType.Skill)
    
class CannotUseMagicItemsEval(SkillComponent):
    nid = 'cannot_use_magic_items_eval'
    desc = "Unit cannot use or equip magic items"
    tag = SkillTags.BASE

    def available(self, unit, item) -> bool:
        return not item_funcs.is_magic(unit, item) and not (item.eval_magic and item.eval_magic.active(unit, item)) and not (item.eval_dragon and item.eval_dragon.active(unit, item)) and not item.eval_dragon_magic
        
class AllyLifelinkTarget(SkillComponent):
    nid = 'ally_lifelink_target'
    desc = "Heals allies adjacent to target %% of damage dealt"
    tag = SkillTags.COMBAT2

    expose = ComponentType.Float
    value = 0.5

    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        total_damage_dealt = 0
        playbacks = [p for p in playback if p.nid in (
            'damage_hit', 'damage_crit') and p.attacker == unit]
        for p in playbacks:
            total_damage_dealt += p.true_damage

        damage = utils.clamp(total_damage_dealt, 0, target.get_hp())
        true_damage = int(damage * self.value)
        if true_damage > 0 and target.position:
            adj_positions = game.target_system.get_adjacent_positions(target.position)
            did_happen = False
            for adj_pos in adj_positions:
                other = game.board.get_unit(adj_pos)
                if other and skill_system.check_ally(other, unit) and unit.nid != other.nid:
                    actions.append(action.ChangeHP(other, true_damage))
                    playback.append(pb.HealHit(
                        unit, item, other, true_damage, true_damage))
                    did_happen = True

            if did_happen:
                actions.append(action.TriggerCharge(unit, self.skill))

class StartAndEndEventInitiate(SkillComponent):
    nid = 'start_and_end_event_initiate'
    desc = 'Calls events before and after combat initated by user'
    tag = SkillTags.ADVANCED

    expose = (ComponentType.NewMultipleOptions)
    options = {
        "start_event": ComponentType.Event,
        "end_event": ComponentType.Event,
    }
    
    def __init__(self, value=None):
        self.value = {
            "start_event": '',
            "end_event": '',
        }
        if value:
            self.value.update(value)

    def start_combat(self, playback, unit, item, target, item2, mode):
        if mode == 'attack':
            game.events.trigger_specific_event(self.value.get('start_event'), unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode})
    
    def end_combat(self, playback, unit: UnitObject, item, target: UnitObject, item2, mode):
        if mode == 'attack':
            game.events.trigger_specific_event(self.value.get('end_event'), unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode})

class BetterPostCombatDamage(SkillComponent):
    nid = 'better_post_combat_damage'
    desc = "Target takes non-lethal flat damage after combat"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 0
    author = 'Lord_Tweed'

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target) and not target.get_hp() <= 0:
            end_health = target.get_hp() - self.value
            action.do(action.SetHP(target, max(1, end_health)))
            action.do(action.TriggerCharge(unit, self.skill))

class EvalPostCombatDamage(SkillComponent):
    nid = 'eval_post_combat_damage'
    desc = "Target takes non-lethal flat damage after combat, based on eval."
    tag = SkillTags.CUSTOM

    expose = ComponentType.String
    author = 'Lord_Tweed'

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target) and not target.get_hp() <= 0:
            from app.engine import evaluate
            try:
                hp_change = int(evaluate.evaluate(self.value, unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode}))
            except:
                logging.error("Couldn't evaluate %s conditional" % self.value)
                hp_change = 0
            end_health = target.get_hp() - hp_change
            action.do(action.SetHP(target, max(1, end_health)))
            action.do(action.TriggerCharge(unit, self.skill))

class CombatChargeIncreaseBetter(SkillComponent):
    nid = 'combat_charge_increase_better'
    desc = "Increases charge of skill each combat, but actually works on miss. Does not work if unit and target are allied."
    tag = SkillTags.CHARGE

    expose = ComponentType.Int
    value = 1

    ignore_conditional = True

    def end_combat(self, playback, unit, item, target, item2, mode):
        if unit and target and not self.skill.data.get('active') and skill_system.check_enemy(unit, target):
            new_value = self.skill.data['charge'] + self.value
            new_value = min(new_value, self.skill.data['total_charge'])
            action.do(action.SetObjData(self.skill, 'charge', new_value))

class GiveStatusesAfterCombat(SkillComponent):
    nid = 'give_statuses_after_combat'
    desc = "Gives multiple statuses to target enemy after combat"
    tag = SkillTags.CUSTOM

    expose = (ComponentType.List, ComponentType.Skill)

    def end_combat(self, playback, unit, item, target, item2, mode):
        from app.engine import skill_system
        if target and skill_system.check_enemy(unit, target):
            for status in self.value:
                action.do(action.AddSkill(target, status, unit))
            action.do(action.TriggerCharge(unit, self.skill))

class DrainChargeAll(SkillComponent):
    nid = 'drain_charge_all'
    desc = "Skill will have a number of charges that are drained by 1 when activated. if other allues have this skill, they will also lose charges."
    tag = SkillTags.CHARGE

    expose = ComponentType.Int
    value = 1

    ignore_conditional = True

    def init(self, skill):
        self.skill.data['charge'] = self.value
        self.skill.data['total_charge'] = self.value

    def condition(self, unit, item):
        return self.skill.data['charge'] > 0

    def on_end_chapter(self, unit, skill):
        self.skill.data['charge'] = self.skill.data['total_charge']

    def trigger_charge(self, unit, skill):
        new_value = self.skill.data['charge'] - 1
        action.do(action.SetObjData(self.skill, 'charge', new_value))
        combined_parties = game.get_all_units_in_party() + game.get_all_units_in_party('Flex')
        for ally in combined_parties:
            if ally.nid != unit.nid and self.skill.nid in [s.nid for s in ally.skills]:
                action.do(action.SetObjData(ally.get_skill(self.skill.nid), 'charge', new_value))

    def text(self) -> str:
        return str(self.skill.data['charge'])

    def cooldown(self):
        return self.skill.data['charge'] / self.skill.data['total_charge']

class ArmsthriftAlways(SkillComponent):
    nid = 'armsthrift_always'
    desc = 'Restores a use regardless of circumstance'
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 1

    def _post_combat(self, unit, item):
        if item_system.unrepairable(unit, item):
            return  # Don't restore for unrepairable items
        # Handles Uses
        if item.uses:
            curr_uses = item.data.get('uses')
            max_uses = item.data.get('starting_uses')
            action.do(action.SetObjData(item, 'uses', min(curr_uses + self.value, max_uses)))
        # Handles Chapter Uses
        #if item.data.get('c_uses', None) and item.data.get('starting_c_uses', None):
        if item.c_uses:
            curr_uses = item.data.get('c_uses')
            max_uses = item.data.get('starting_c_uses')
            action.do(action.SetObjData(item, 'c_uses', min(curr_uses + self.value, max_uses)))

    def post_combat(self, playback, unit, item, target, item2, mode):
        # handles one loss per combat + armsthift interaction
        if not item:
            return
        if item.parent_item:
            self.post_combat(
                playback, unit, item.parent_item, target, item2, mode)
        if item.uses_options:
            self._post_combat(unit, item)

class SavageStatuses(SkillComponent):
    nid = 'savage_statuses'
    desc = 'Inflicts the given statuses to enemies within the given number of spaces from target.'
    tag = SkillTags.CUSTOM
    author = 'Lord_Tweed'

    expose = (ComponentType.NewMultipleOptions)
    options = {
        "statuses": (ComponentType.List, ComponentType.Skill),
        "range": ComponentType.Int,
    }
    
    def __init__(self, value=None):
        self.value = {
            "statuses": [],
            "range": 1,
        }
        if value:
            self.value.update(value)

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target):
            r = set(range(self.value.get('range') + 1))
            locations = game.target_system.get_shell({target.position}, r, game.board.bounds)
            for loc in locations:
                target2 = game.board.get_unit(loc)
                if target2 and target2 is not target and skill_system.check_enemy(unit, target2):
                    for status in self.value.get('statuses'):
                        action.do(action.AddSkill(target2, status, unit))

class GainTerrain(SkillComponent):
    nid = 'gain_terrain'
    desc = "Unit will be affected by terrain"
    tag = SkillTags.MOVEMENT

    def ignore_terrain(self, unit):
        return False

    def ignore_region_status(self, unit):
        return False

class HealAfterFollowUp(SkillComponent):
    nid = 'heal_after_follow_up'
    desc = "Heal HP immediately after an enemy damages you, only if attack was a follow-up"
    tag = SkillTags.COMBAT

    expose = ComponentType.Int
    value = 5

    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        for act in actions:
            if isinstance(act, action.ChangeHP) and act.num < 0 and act.unit == unit and attack_info[0] > 0 and unit.get_hp() > (-1 * act.num):
                playbacks = [p for p in playback if p.nid in ('damage_hit', 'damage_crit') and p.attacker == target]
                actions.append(action.ChangeHP(unit, self.value))
                playback.append(pb.HealHit(target, item2, unit, self.value, self.value))
                actions.append(action.TriggerCharge(unit, self.skill))
                return

class AlternateMagicDamageFormula(SkillComponent):
    nid = 'alternate_magic_damage_formula'
    desc = 'Unit uses a different magic_damage formula'
    tag = SkillTags.FORMULA

    expose = ComponentType.Equation
    value = 'MAGIC_DAMAGE'

    def damage_formula(self, unit):
        return self.value

class EvalCritDamage(SkillComponent):
    nid = 'eval_crit_additional'
    desc = "Gives +X additional damage on crit solved using evaluate"
    tag = SkillTags.COMBAT

    expose = ComponentType.String

    def modify_crit_addition(self, unit, item):
        from app.engine import evaluate
        try:
            return int(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except Exception as e:
            logging.error("Couldn't evaluate %s conditional (%s)", self.value, e)
        return 0

class GainSkillAfterActiveNotKill(SkillComponent):
    nid = 'gain_skill_after_active_not_kill'
    desc = "Gives a skill after failing to kill on personal phase"
    tag = SkillTags.COMBAT2

    expose = ComponentType.Skill

    def end_combat(self, playback, unit, item, target, item2, mode):
        mark_playbacks = [p for p in playback if p.nid in (
            'mark_miss', 'mark_hit', 'mark_crit')]
        if target and target.get_hp() > 0 and any(p.main_attacker is unit for p in mark_playbacks):  # Unit is overall attacker
            action.do(action.AddSkill(unit, self.value))
            action.do(action.TriggerCharge(unit, self.skill))

class PostCombatHealing(SkillComponent):
    nid = 'post_combat_healing'
    desc = "Unit heals a flat amount of HP after battle with an enemy"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 1
    author = 'Lord_Tweed'

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target) and unit.get_hp() > 0:
            end_health = unit.get_hp() + self.value
            action.do(action.SetHP(unit, end_health))
            action.do(action.TriggerCharge(unit, self.skill))

class HitDamageMultiplier(SkillComponent):
    nid = 'true_damage_multiplier'
    desc = "Multiplies bonus damage modifier given by a fraction"
    tag = SkillTags.COMBAT

    expose = ComponentType.Float
    value = 0.5

    def hit_damage_multiplier(self, unit, item, target, item2, mode, attack_info, base_value):
        return self.value

class EvalHealOnKill(SkillComponent):
    nid = 'eval_heal_on_kill'
    desc = 'Gives +X health on kill, based on eval'
    tag = SkillTags.CUSTOM

    expose = ComponentType.String

    def end_combat(self, playback, unit, item, target, item2, mode):
        from app.engine import evaluate
        try:
            hp_change = int(evaluate.evaluate(self.value, unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode}))
        except:
            logging.error("Couldn't evaluate %s conditional" % self.value)
            hp_change = 0
        mark_playbacks = [p for p in playback if p.nid in ('mark_miss', 'mark_hit', 'mark_crit')]
        if target and target.get_hp() <= 0:
            heal = max(0, hp_change)
            action.do(action.ChangeHP(unit, heal))

class CannotUseWeapons(SkillComponent):
    nid = 'cannot_use_weapons'
    desc = "Unit cannot use weapons"
    tag = SkillTags.CUSTOM

    def available(self, unit, item) -> bool:
        return not item.weapon

class EvalPreCombatDamage(SkillComponent):
    nid = 'eval_pre_combat_damage'
    desc = "Target takes non-lethal flat damage at start of combat, based on eval."
    tag = SkillTags.CUSTOM

    expose = ComponentType.String
    author = 'Lord_Tweed'

    def start_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target) and not target.get_hp() <= 0:
            from app.engine import evaluate
            try:
                hp_change = int(evaluate.evaluate(self.value, unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode}))
            except:
                logging.error("Couldn't evaluate %s conditional" % self.value)
                hp_change = 0
            end_health = target.get_hp() - hp_change
            action.do(action.SetHP(target, max(1, end_health)))
            action.do(action.TriggerCharge(unit, self.skill))

class EvalPostCombatHealing(SkillComponent):
    nid = 'eval_post_combat_healing'
    desc = "Unit heals a flat amount of HP after any battle, based on eval"
    tag = SkillTags.CUSTOM

    expose = ComponentType.String
    author = 'Lord_Tweed'

    def end_combat(self, playback, unit, item, target, item2, mode):
        from app.engine import evaluate
        if target and unit.get_hp() > 0:
            try:
                hp_change = int(evaluate.evaluate(self.value, unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode}))
            except:
                logging.error("Couldn't evaluate %s conditional" % self.value)
                hp_change = 0
            end_health = unit.get_hp() + hp_change
            action.do(action.SetHP(unit, end_health))
            action.do(action.TriggerCharge(unit, self.skill))

class GainSkillOnHit(SkillComponent):
    nid = 'gain_on_hit'
    desc = "Gain skill after performing a strike (it must hit)"
    tag = SkillTags.COMBAT2
    
    expose = ComponentType.Skill

    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        if strike == Strike.HIT or strike == Strike.CRIT:
            actions.append(action.AddSkill(unit, self.value, unit))
            actions.append(action.TriggerCharge(unit, self.skill))

class GainSkillOnMiss(SkillComponent):
    nid = 'gain_on_miss'
    desc = "Gain skill after performing a strike (it must miss)"
    tag = SkillTags.COMBAT2
    
    expose = ComponentType.Skill

    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        if strike == Strike.MISS:
            actions.append(action.AddSkill(unit, self.value, unit))
            actions.append(action.TriggerCharge(unit, self.skill))

class NoStackz(SkillComponent):
    nid = 'no_stackz'
    desc = "Not a target of infinite stacking."
    tag = SkillTags.CUSTOM

class EvalPostCombatDamageAll(SkillComponent):
    nid = 'eval_post_combat_damage_all'
    desc = "All targets take non-lethal flat damage after combat, based on eval. Only activates if unit strikes."
    tag = SkillTags.CUSTOM

    expose = ComponentType.String
    author = 'Lord_Tweed'
    
    _did_hit = set()
    
    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        self._did_hit.add(target)

    def end_combat(self, playback, unit, item, target, item2, mode):
        from app.engine import evaluate
        try:
            hp_change = int(evaluate.evaluate(self.value, unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode}))
        except:
            logging.error("Couldn't evaluate %s conditional" % self.value)
            hp_change = 0
        hit_targets = 0
        for targets in self._did_hit:
            if skill_system.check_enemy(unit, targets) and not targets.get_hp() <= 0:
                end_health = targets.get_hp() - hp_change
                action.do(action.SetHP(targets, max(1, end_health)))
                hit_targets += 1
        if hit_targets > 0:
            action.do(action.TriggerCharge(unit, self.skill))
        self._did_hit.clear()

class BetterRecoil(SkillComponent):
    nid = 'better_recoil'
    desc = "Unit takes non-lethal damage after combat with an enemy, OR after initiated splash involving an enemy"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 0
    author = 'Lord_Tweed'

    _did_hit = set()
    
    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        self._did_hit.add(target)
    
    def end_combat(self, playback, unit, item, target, item2, mode):
        if ((target and skill_system.check_enemy(unit, target)) or any([skill_system.check_enemy(unit, y) for y in self._did_hit])) and not unit.get_hp() <= 0:
            end_health = unit.get_hp() - self.value
            action.do(action.SetHP(unit, max(1, end_health)))
            action.do(action.TriggerCharge(unit, self.skill))

class RescueBonus(SkillComponent):
    nid = 'rescue_bonus'
    desc = "Traveler grants a child skill to lead unit while being rescued."
    tag = SkillTags.STATUS

    expose = ComponentType.Skill

    def on_rescue(self, unit, leader):
        action.do(action.AddSkill(leader, self.value))

    def on_drop(self, unit, leader):
        if self.value in [skill.nid for skill in leader.skills]:
            action.do(action.RemoveSkill(leader, self.value))

class RescueBonuses(SkillComponent):
    nid = 'rescue_bonuses'
    desc = "Traveler grants child skills to lead unit while being rescued."
    tag = SkillTags.STATUS

    expose = (ComponentType.List, ComponentType.Skill)

    def on_rescue(self, unit, leader):
        for status in self.value:
            action.do(action.AddSkill(leader, status))

    def on_drop(self, unit, leader):
        for status in self.value:
            if status in [skill.nid for skill in leader.skills]:
                action.do(action.RemoveSkill(leader, status))

class AoeGainSkillAfterCombat(SkillComponent):
    nid = 'aoe_gain_skill_after_combat'
    desc = "Gives a skill to user (optionally) and units within X spaces of user after any combat"
    tag = SkillTags.COMBAT2
    author = 'Lord_Tweed'

    expose = (ComponentType.NewMultipleOptions)
    options = {
        "skill": ComponentType.Skill,
        "range": ComponentType.Int,
        "affect_self": ComponentType.Bool,
        "target": (ComponentType.MultipleChoice, ('ally', 'enemy', 'any')),
    }
    
    def __init__(self, value=None):
        self.value = {
            "skill": 'Canto',
            "range": 1,
            "affect_self": False,
            "target": 'ally',
        }
        if value:
            self.value.update(value)

    def end_combat(self, playback, unit, item, target, item2, mode):
        r = set(range(self.value.get('range') + 1))
        skill_used = 0
        locations = game.target_system.get_shell({unit.position}, r, game.board.bounds)
        for loc in locations:
            target2 = game.board.get_unit(loc)
            if target2 and target2 is not unit and self.value.get('target') in ['enemy','any'] and skill_system.check_enemy(unit, target2):
                action.do(action.AddSkill(target2, self.value.get('skill'), unit))
                skill_used += 1
            elif target2 and target2 is not unit and self.value.get('target') in ['ally','any'] and skill_system.check_ally(unit, target2):
                action.do(action.AddSkill(target2, self.value.get('skill'), unit))
                skill_used += 1

        if self.value.get('affect_self'):
            action.do(action.AddSkill(unit, self.value.get('skill'), unit))
            skill_used += 1
        if skill_used > 0:
            action.do(action.TriggerCharge(unit, self.skill))

class EventAfterCombatIfTakeDamage(SkillComponent):
    nid = 'event_after_combat_if_take_damage'
    desc = "Run an event after combat if unit took damage from combat"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Event
    got_hit = False

    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        for act in actions:
            if isinstance(act, action.ChangeHP) and act.num < 0 and act.unit == unit:
                self.got_hit = True
                return

    def end_combat(self, playback, unit, item, target, item2, mode):
        if self.got_hit:
            game.events.trigger_specific_event(self.value, unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode})
        self.got_hit = False

class StatChangeAtApplyExpression(SkillComponent):
    nid = 'stat_change_at_apply_expression'
    desc = "Gives stat bonuses based on expression. Stat change will not update after application, regardless of eval."
    tag = SkillTags.COMBAT

    expose = (ComponentType.StringDict, ComponentType.Stat)
    value = []
    
    def init(self, skill):
        from app.engine import evaluate
        try:
            self.new_value = {stat[0]: int(evaluate.evaluate(stat[1], local_args={'skill': skill})) for stat in self.value}
            print(self.new_value)
        except Exception as e:
            logging.error("Couldn't evaluate conditional for skill %s: [%s], %s", self.skill.nid, str(self.value), e)
            self.new_value = {stat[0]: 0 for stat in self.value}

    def stat_change(self, unit=None):
        return self.new_value

class ChangeItemSlots(SkillComponent):
    nid = 'change_item_slots'
    desc = "Alters the amount of normal items unit can carry."
    tag = SkillTags.BASE

    expose = ComponentType.Int
    value = 0

    def num_items_offset(self, unit) -> int:
        return self.value

class EvalCanter(SkillComponent):
    nid = 'eval_canter'
    desc = "Evaluates the canter spaces."
    tag = SkillTags.CUSTOM

    expose = ComponentType.String

    def canto_movement(self, unit, unit2) -> int:
        from app.engine import evaluate
        try:
            if 'NullCanto' in unit.tags:
                return min(1, int(evaluate.evaluate(self.value, unit, unit2)))
            else:
                return int(evaluate.evaluate(self.value, unit, unit2))
        except:
            logging.error("Couldn't evaluate %s conditional" % self.value)
        return 0

    def has_canto(self, unit, unit2) -> bool:
        """
        Can move again after any action, has exactly the number of movement that was determined in the component
        """
        return True

class NullRefresh(SkillComponent):
    nid = 'null_refresh'
    desc = "This unit cannot be refreshed."
    tag = SkillTags.CUSTOM

    def on_refresh(self, unit):
        if not 'AlwaysRefresh' in unit.tags:
            action.do(action.Wait(unit))

class BlockStatus(SkillComponent):
    nid = 'block_status'
    desc = "Unit does not receive negative statuses. Can trigger charges, allowing effects such as: Nullify first debuff received."
    tag = SkillTags.STATUS

    def after_gain_skill(self, unit, other_skill):
        if other_skill.negative and skill_system.condition(self.skill, unit):
            action.do(action.RemoveSkill(unit, other_skill))
            action.do(action.TriggerCharge(unit, self.skill))

class AoeGainSkillAfterKill(SkillComponent):
    nid = 'aoe_gain_skill_after_kill'
    desc = "Gives a skill to user (optionally) and units within X spaces of user after a kill"
    tag = SkillTags.COMBAT2
    author = 'Lord_Tweed'

    expose = (ComponentType.NewMultipleOptions)
    options = {
        "skill": ComponentType.Skill,
        "range": ComponentType.Int,
        "affect_self": ComponentType.Bool,
        "target": (ComponentType.MultipleChoice, ('ally', 'enemy', 'any')),
    }
    
    def __init__(self, value=None):
        self.value = {
            "skill": 'Canto',
            "range": 1,
            "affect_self": False,
            "target": 'enemy',
        }
        if value:
            self.value.update(value)

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and target.get_hp() <= 0:
            r = set(range(self.value.get('range') + 1))
            skill_used = 0
            locations = game.target_system.get_shell({unit.position}, r, game.board.bounds)
            for loc in locations:
                target2 = game.board.get_unit(loc)
                if target2 and target2 is not unit and self.value.get('target') in ['enemy','any'] and skill_system.check_enemy(unit, target2):
                    action.do(action.AddSkill(target2, self.value.get('skill'), unit))
                    skill_used += 1
                elif target2 and target2 is not unit and self.value.get('target') in ['ally','any'] and skill_system.check_ally(unit, target2):
                    action.do(action.AddSkill(target2, self.value.get('skill'), unit))
                    skill_used += 1

            if self.value.get('affect_self'):
                action.do(action.AddSkill(unit, self.value.get('skill'), unit))
                skill_used += 1
            if skill_used > 0:
                action.do(action.TriggerCharge(unit, self.skill))

class AllyLifelinkRanged(SkillComponent):
    nid = 'ally_lifelink_ranged'
    desc = "Heals allies in X range for a %% of damage dealt"
    tag = SkillTags.COMBAT2
    
    expose = (ComponentType.NewMultipleOptions)
    options = {
        "percentage": ComponentType.Float,
        "range": ComponentType.Int,
        "include self?": ComponentType.Bool
    }
    
    def __init__(self, value=None):
        self.value = {
            "percentage": 0.5,
            "range": 1,
            "include self?": False
        }
        if value:
            self.value.update(value)

    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        total_damage_dealt = 0
        playbacks = [p for p in playback if p.nid in (
            'damage_hit', 'damage_crit') and p.attacker == unit]
        for p in playbacks:
            total_damage_dealt += p.true_damage

        damage = utils.clamp(total_damage_dealt, 0, target.get_hp())
        true_damage = int(damage * self.value.get('percentage'))
        if true_damage > 0 and unit.position:
            r = set(range(self.value.get('range') + 1))
            ally_positions = game.target_system.get_shell({unit.position}, r, game.board.bounds)
            did_happen = False
            for ally_pos in ally_positions:
                other = game.board.get_unit(ally_pos)
                if other and ((skill_system.check_ally(other, unit) and other.nid != unit.nid) or (self.value.get('include self?', False) and other.nid == unit.nid)):
                    actions.append(action.ChangeHP(other, true_damage))
                    playback.append(pb.HealHit(
                        unit, item, other, true_damage, true_damage))
                    did_happen = True

            if did_happen:
                actions.append(action.TriggerCharge(unit, self.skill))
                
class AllyStrikehealRanged(SkillComponent):
    nid = 'ally_strikeheal_ranged'
    desc = "After combat, heals allies in X range for a set amount or %% of their max HP. Unit must have struck in combat."
    tag = SkillTags.CUSTOM
    
    expose = (ComponentType.NewMultipleOptions)
    options = {
        "Amount/Percentage": ComponentType.Int,
        "range": ComponentType.Int,
        "is percent?": ComponentType.Bool
    }
    
    def __init__(self, value=None):
        self.value = {
            "Amount/Percentage": 5,
            "range": 1,
            "is percent?": False
        }
        if value:
            self.value.update(value)

    def end_combat(self, playback, unit, item, target, item2, mode):
        mark_playbacks = [p for p in playback if p.nid in ('mark_hit', 'mark_crit', 'mark_miss') and p.attacker == unit]
        if mark_playbacks:
            did_happen = False
            r = set(range(self.value.get('range') + 1))
            ally_positions = game.target_system.get_shell({unit.position}, r, game.board.bounds)
            for ally_pos in ally_positions:
                other = game.board.get_unit(ally_pos)
                if other and skill_system.check_ally(other, unit):
                    if self.value.get('is percent?', False):
                        heal_amount = int(other.get_max_hp() * (self.value.get('Amount/Percentage') / 100))
                    else:
                        heal_amount = self.value.get('Amount/Percentage')
                    action.do(action.ChangeHP(other, heal_amount))
                    did_happen = True

            if did_happen:
                action.do(action.TriggerCharge(unit, self.skill))

class BetterPostCombatSplash(SkillComponent):
    nid = 'better_post_combat_splash'
    desc = "After combat, damages foes in X range of target for a set amount or %% of their max HP. Unit must have struck in combat."
    tag = SkillTags.CUSTOM
    
    expose = (ComponentType.NewMultipleOptions)
    options = {
        "Amount/Percentage": ComponentType.Int,
        "range": ComponentType.Int,
        "is percent?": ComponentType.Bool
    }
    
    def __init__(self, value=None):
        self.value = {
            "Amount/Percentage": 5,
            "range": 1,
            "is percent?": False
        }
        if value:
            self.value.update(value)

    def end_combat(self, playback, unit, item, target, item2, mode):
        mark_playbacks = [p for p in playback if p.nid in ('mark_hit', 'mark_crit', 'mark_miss') and p.attacker == unit]
        if mark_playbacks and target:
            did_happen = False
            r = set(range(self.value.get('range') + 1))
            foe_positions = game.target_system.get_shell({target.position}, r, game.board.bounds)
            for foe_pos in foe_positions:
                other = game.board.get_unit(foe_pos)
                if other and not skill_system.check_ally(other, unit):
                    if self.value.get('is percent?', False):
                        damage_amount = int(other.get_max_hp() * (self.value.get('Amount/Percentage') / 100))
                    else:
                        damage_amount = self.value.get('Amount/Percentage')
                    end_health = other.get_hp() - damage_amount
                    if other.get_hp() > 0:
                        action.do(action.SetHP(other, max(1, end_health)))
                        did_happen = True

            if did_happen:
                action.do(action.TriggerCharge(unit, self.skill))

class EmpowerHealReceivedMultiplier(SkillComponent):
    nid = 'empower_heal_received_multiplier'
    desc = "Multiply healing received by X%%"
    tag = SkillTags.ADVANCED

    expose = ComponentType.Float
    value = 1.0

    def empower_heal_received_multiplier(self, target, unit):
        return self.value
    
class EmpowerHealMultiplier(SkillComponent):
    nid = 'empower_heal_multiplier'
    desc = "Multiply healing given by X%%"
    tag = SkillTags.ADVANCED

    expose = ComponentType.Float
    value = 1.0

    def empower_heal_multiplier(self, target, unit):
        return self.value

class PurgeAilments(SkillComponent):
    nid = 'purge_ailments'
    desc = "Ailments are purged during upkeep."
    tag = SkillTags.STATUS

    def on_upkeep(self, actions, playback, unit):
        for s in unit.skills:
            if s.negative:
                action.do(action.RemoveSkill(unit, s))

class BetterGiveStatusAfterCombatOnHit(SkillComponent):
    nid = 'better_give_status_after_combat_on_hit'
    desc = "Gives a status to target after combat assuming you hit the target. Works in AoE. Only affects enemies."
    tag = SkillTags.COMBAT2

    expose = ComponentType.Skill

    def end_combat(self, playback, unit, item, target, item2, mode):
        mark_playbacks = [p for p in playback if p.nid in ('mark_hit', 'mark_crit') and p.attacker == unit]
        targets = set([u.defender for u in mark_playbacks if skill_system.check_enemy(u.attacker, u.defender)])
        for target in targets:
            action.do(action.AddSkill(target, self.value, unit))
        if targets:
            action.do(action.TriggerCharge(unit, self.skill))

class GainSkillsAfterCombat(SkillComponent):
    nid = 'gain_skills_after_combat'
    desc = "Gives multiple skills to user after any combat"
    tag = SkillTags.COMBAT2

    expose = (ComponentType.List, ComponentType.Skill)

    def end_combat(self, playback, unit, item, target, item2, mode):
        for status in self.value:
            action.do(action.AddSkill(unit, status))
        action.do(action.TriggerCharge(unit, self.skill))

class LifelinkOnCrit(SkillComponent):
    nid = 'lifelink_on_crit'
    desc = "Heals user %% of damage dealt when dealing a critical hit"
    tag = SkillTags.COMBAT2

    expose = ComponentType.Float
    value = 0.5

    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        total_damage_dealt = 0
        playbacks = [p for p in playback if p.nid in ('damage_crit') and p.attacker == unit]
        for p in playbacks:
            total_damage_dealt += p.true_damage

        damage = utils.clamp(total_damage_dealt, 0, target.get_hp())
        true_damage = int(damage * self.value)
        actions.append(action.ChangeHP(unit, true_damage))

        playback.append(pb.HealHit(unit, item, unit, true_damage, true_damage))

        actions.append(action.TriggerCharge(unit, self.skill))

class TriggerCharge(SkillComponent):
    nid = 'trigger_charge'
    desc = "Forcibly triggers charge at the end of combat."
    tag = SkillTags.CUSTOM

    def end_combat(self, playback, unit, item, target, item2, mode):
        action.do(action.TriggerCharge(unit, self.skill))

class EventOnGainSkill(SkillComponent):
    nid = 'event_on_gain_skill'
    desc = "An event procs when skill is added to a unit"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Event
    value = ''

    def after_add(self, unit, skill):
        game.events.trigger_specific_event(self.value, unit, unit, unit.position, {'skill': skill})

class ExtraTriangleAdvantage(SkillComponent):
    nid = 'extra_triangle_advantage'
    desc = 'Unit has triangle advantage against this weapon type'
    tag = SkillTags.BASE

    author = 'Beccarte'
    expose = (ComponentType.List,ComponentType.WeaponType)

    def advantage_wtypes(self, unit, skill):
        return self.value

class ReplacesSkills(SkillComponent):
    nid = 'replaces_skills'
    desc = "Skill replaces another skill upon being learned. That skill is removed."
    tag = SkillTags.CUSTOM

    author = 'Beccarte'
    expose = ComponentType.Skill
    value = []

    ignore_conditional = True
    _condition = True

    def skill_learn_replace(self, unit):
        return self.value.nid

class NoWeaponRankBonus(SkillComponent):
    nid = 'no_weapon_rank_bonus'
    desc = "Unit does not benefit from weapon rank bonuses."
    tag = SkillTags.CUSTOM

    author = 'Beccarte'

    def no_rank_bonus(self, unit):
        return True

class CombatSwap(SkillComponent):
    nid = 'combat_swap'
    desc = "Defending allies within the given number of spaces will have this unit substitute for them in combat."
    tag = SkillTags.COMBAT

    author = 'Beccarte'
    expose = ComponentType.Int

    def combat_swap(self, unit):
        return self.value

class AttackProcEnemy(SkillComponent):
    nid = 'attack_proc_enemy'
    desc = "Allows skill to proc on a single attacking strike. Gives the status to the foe."
    tag = SkillTags.ADVANCED

    expose = ComponentType.Skill
    _did_action = False

    def start_sub_combat(self, actions, playback, unit, item, target, item2, mode, attack_info):
        if mode == 'attack' and target and skill_system.check_enemy(unit, target):
            if not advanced_components.get_weapon_filter(self.skill, unit, item):
                return
            proc_rate = advanced_components.get_proc_rate(unit, self.skill)
            if static_random.get_combat() < proc_rate:
                act = action.AddSkill(target, self.value)
                action.do(act)
                if act.skill_obj:
                    playback.append(pb.AttackProc(unit, act.skill_obj))
                self._did_action = True

    def end_sub_combat_unconditional(self, actions, playback, unit, item, target, item2, mode, attack_info):
        if self._did_action:
            action.do(action.TriggerCharge(unit, self.skill))
            action.do(action.RemoveSkill(target, self.value))
        self._did_action = False

class HardyBearing(SkillComponent):
    nid = 'hardy_bearing'
    desc = "Unit ignores all vantage and disvantage attack order changes."
    tag = SkillTags.COMBAT2

    author = 'Beccarte'

    def hardy_bearing(self, unit):
        return True

class DisplaySkillIconOnCondition(SkillComponent):
    nid = 'display_skill_icon_on_condition'
    desc = "Displays the skill's icon in combat if a specified condition is met"
    tag = SkillTags.AESTHETIC

    author = 'Beccarte'
    
    expose = ComponentType.String
    value = 'False'
    _condition = False
    
    def pre_combat(self, playback, unit, item, target, item2, mode):
        from app.engine import evaluate
        try:
            x = bool(evaluate.evaluate(self.value, unit, target,
                                       unit.position, {'item': item, 'item2': item2, 'mode': mode}))
            self._condition = x
            return x
        except Exception as e:
            print("%s: Could not evaluate display icon condition %s" %
                  (e, self.value))
    
    def show_skill_icon(self, unit) -> bool:
        return self._condition

class BlockDamage(SkillComponent):
    nid = 'block_damage'
    desc = "As ignore damage but will cosmetically appear as if no damage was inflicted"
    tag = SkillTags.COMBAT2

    author = 'Beccarte'

    def block_damage(self, unit):
        return True

class ExpendChargeAfterCombat(SkillComponent):
    nid = 'expend_charge_after_combat'
    desc = "If at full charge, skill will trigger a charge after combat"
    tag = SkillTags.CHARGE

    author = 'Beccarte'
    
    _remove = False
    
    def start_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target) and self.skill.data['charge'] >= self.skill.data['total_charge']:
            self._remove = True

    def end_combat(self, playback, unit, item, target, item2, mode):
        if self._remove:
            skill_system.trigger_charge(unit, self.skill)
            self._remove = False

class MaximumAccuracy(SkillComponent):
    nid = 'maximum_accuracy'
    desc = "Sets a cap on unit's hit rate."
    tag = SkillTags.COMBAT

    author = 'Beccarte'

    expose = ComponentType.Int
    value = 100

    def maximum_accuracy(self, unit):
        return self.value

class FoeMaximumAccuracy(SkillComponent):
    nid = 'foe_maximum_accuracy'
    desc = "Sets a cap on enemy hit rates against this unit."
    tag = SkillTags.COMBAT

    author = 'Beccarte'

    expose = ComponentType.Int
    value = 100

    def foe_maximum_accuracy(self, unit):
        return self.value

class MaximumDamage(SkillComponent):
    nid = 'maximum_damage'
    desc = "Sets a cap on unit's damage dealt."
    tag = SkillTags.COMBAT

    author = 'Beccarte'

    expose = ComponentType.Int
    value = 999

    def maximum_damage(self, unit):
        return self.value

class FoeMaximumDamage(SkillComponent):
    nid = 'foe_maximum_damage'
    desc = "Sets a cap on enemy damage against this unit."
    tag = SkillTags.COMBAT

    author = 'Beccarte'

    expose = ComponentType.Int
    value = 999

    def foe_maximum_damage(self, unit):
        return self.value

class EnemyPass(SkillComponent):
    nid = 'enemy_pass'
    desc = "Enemies can move through this unit"
    tag = SkillTags.MOVEMENT

    def enemy_pass_through(self, unit):
        return True

class RagingStorm(SkillComponent):
    nid = 'raging_storm'
    desc = "After combat, unit can move and act again. This is unrestricted without other conditions."
    tag = SkillTags.MOVEMENT

    author = 'Beccarte'

    def end_combat(self, playback, unit, item, target, item2, mode):
        mark_playbacks = [p for p in playback if p.nid in ('mark_miss', 'mark_hit', 'mark_crit')]
        if target and any(p.main_attacker is unit for p in mark_playbacks):  # Unit is overall attacker
            action.do(action.Reset(unit))

class NoStatDebuffs(SkillComponent):
    nid = 'no_stat_debuffs'
    desc = "Unit's stats cannot be lowered by skills."
    tag = SkillTags.COMBAT2

    author = 'Beccarte'

    def no_stat_debuffs(self, unit):
        return True

class ItemRefresh(SkillComponent):
    nid = 'item_refresh'
    desc = "After using a non-weapon item, unit can move again. Can activate once per turn."
    tag = SkillTags.MOVEMENT

    author = 'Beccarte'
    
    def end_combat(self, playback, unit, item, target, item2, mode):
        if item and not item_system.is_weapon(unit, item) and (not target or target == unit):
            action.do(action.Reset(unit))
            action.do(action.TriggerCharge(unit, self.skill))

class EventOnUpkeep(SkillComponent):
    nid = 'event_on_upkeep'
    desc = "Triggers an event at upkeep."
    tag = SkillTags.BASE

    author = 'Beccarte'
    
    expose = ComponentType.Event

    def on_upkeep(self, actions, playback, unit):
        event_prefab = DB.events.get_from_nid(self.value)
        if event_prefab:
            game.events.trigger_specific_event(event_prefab.nid, unit, unit.position)

class CritProc(SkillComponent):
    nid = 'crit_proc'
    desc = "When the unit crits, it will play the combat effect animation named 'Crit_' + unit.nid"
    tag = SkillTags.ADVANCED

    author = 'Beccarte'
    
    _did_action = False

    def before_crit(self, actions, playback, attacker, item, defender, item2, mode, attack_info):
        if defender and skill_system.check_enemy(attacker, defender):
            playback.append(pb.CritProc(attacker))

class GainSkillOnEndstep(SkillComponent):
    nid = 'gain_skill_on_endstep'
    desc = "Gain a skill on endstep."
    tag = SkillTags.TIME

    author = 'Beccarte'

    expose = ComponentType.Skill

    def on_endstep_unconditional(self, actions, playback, unit):
        actions.append(action.AddSkill(unit, self.value))

class DualGuardBonus(SkillComponent):
    nid = 'dual_guard_bonus'
    desc = "Bonus chance to guard ally when supporting in combat"
    tag = SkillTags.BASE

    author = 'Beccarte'
    
    expose = ComponentType.Int
    value = 10

    def modify_dual_guard_chance(self, unit):
        return self.value

class DualStrikeBonus(SkillComponent):
    nid = 'dual_strike_bonus'
    desc = "Bonus chance to strike enemy when supporting in combat"
    tag = SkillTags.BASE

    author = 'Beccarte'
    
    expose = ComponentType.Int
    value = 10

    def modify_dual_strike_chance(self, unit):
        return self.value

class NegatedBySkills(SkillComponent):
    nid = 'negated_by_skills'
    desc = "Skill does not work against a holder of other skill(s)"
    tag = SkillTags.CUSTOM

    expose = (ComponentType.List, ComponentType.Skill)
    value = []

    ignore_conditional = True
    _condition = True

    def pre_combat(self, playback, unit, item, target, item2, mode):
        all_negates = set(self.value)
        if target:
            for skill in target.skills:
                if skill.nid in all_negates:
                    self._condition = False
                    return
        self._condition = True

    def post_combat(self, playback, unit, item, target, item2, mode):
        self._condition = True

    def condition(self, unit, item):
        return self._condition

    def test_on(self, playback, unit, item, target, item2, mode):
        self.pre_combat(playback, unit, item, target, item2, mode)

    def test_off(self, playback, unit, item, target, item2, mode):
        self._condition = True

class UnitFlickeringTintIntense(SkillComponent):
    nid = 'unit_flickering_tint_intense'
    desc = "Displays a rapid flickering tint on the unit"
    tag = SkillTags.AESTHETIC

    author = 'Beccarte'

    expose = ComponentType.Color3

    def unit_sprite_flicker_tint(self, unit, skill) -> tuple:
        return (self.value, 400, 300)

class UnitFlickeringTintSlow(SkillComponent):
    nid = 'unit_flickering_tint_slow'
    desc = "Displays a slow flickering tint on the unit"
    tag = SkillTags.AESTHETIC

    author = 'Beccarte'

    expose = ComponentType.Color3

    def unit_sprite_flicker_tint(self, unit, skill) -> tuple:
        return (self.value, 1300, 300)

class ModifySpecMaximumRange(SkillComponent):
    nid = 'modify__spec_maximum_range'
    desc = "modifies unit's maximum allowed range with specific weapon types"
    tag = SkillTags.COMBAT2

    expose = (ComponentType.Dict, ComponentType.WeaponType)
    value = []
    author = 'h0lyMushrooms'

    def modify_maximum_range(self, unit, item):
        for increase in self.value:
            if item.weapon_type:
                if item.weapon_type.value == increase[0]:
                    return increase[1]
        return 0

class Provoke(SkillComponent):
    nid = 'provoke'
    desc = "AI will attack this unit even if it can't hit or will do zero damage"
    tag = SkillTags.COMBAT2

    author = 'Beccarte'

    def provoke(self, unit):
        return True

class Disvantage(SkillComponent):
    nid = 'disvantage'
    desc = "Unit will attack last even while attacking"
    tag = SkillTags.COMBAT2

    author = 'Beccarte'

    def disvantage(self, unit):
        return True

class PostCombatDamageSelf(SkillComponent):
    nid = 'post_combat_damage_self'
    desc = "Unit takes non-lethal flat damage after combat with an enemy"
    tag = SkillTags.COMBAT2

    expose = ComponentType.Int
    value = 0
    author = 'Beccarte'

    def end_combat(self, playback, unit, item, target, item2, mode):
        end_health = unit.get_hp() - self.value
        if unit and target and skill_system.check_enemy(unit, target):
            action.do(action.SetHP(unit, max(1, end_health)))
            action.do(action.TriggerCharge(unit, self.skill))

class DynamicUpkeepDamage(SkillComponent):
    nid = 'dynamic_upkeep_damage'
    desc = "Unit takes damage at upkeep specified by a forumla"
    tag = SkillTags.STATUS

    expose = ComponentType.String
    value = '5'
    author = 'Beccarte'

    def _playback_processing(self, playback, unit, hp_change):
        from app.engine import evaluate
        try:
            damage_amount = int(evaluate.evaluate(self.value, unit))
        except Exception:
            print("Couldn't evaluate %s conditional" % self.value)
            damage_amount = 1
        # Playback
        if hp_change < 0:
            playback.append(pb.HitSound('Attack Hit ' + str(random.randint(1, 5))))
            playback.append(pb.UnitTintAdd(unit, (255, 255, 255)))
            playback.append(pb.DamageNumbers(unit, damage_amount))
        elif hp_change > 0 and unit.get_hp() < unit.get_max_hp():
            playback.append(pb.HitSound('MapHeal'))
            if hp_change >= 30:
                name = 'MapBigHealTrans'
            elif hp_change >= 15:
                name = 'MapMediumHealTrans'
            else:
                name = 'MapSmallHealTrans'
            playback.append(pb.CastAnim(name))
            playback.append(pb.DamageNumbers(unit, damage_amount))

    def on_upkeep(self, actions, playback, unit):
        from app.engine import evaluate
        try:
            damage_amount = int(evaluate.evaluate(self.value, unit))
        except Exception:
            print("Couldn't evaluate %s conditional" % self.value)
            damage_amount = 1            
        hp_change = -damage_amount
        actions.append(action.ChangeHP(unit, hp_change))
        actions.append(action.TriggerCharge(unit, self.skill))
        self._playback_processing(playback, unit, hp_change)
        #skill_system.after_take_strike(actions, playback, unit, None, None, 'defense', (0, 0), Strike.HIT)

class PostCombatSplashHeal(SkillComponent):
    nid = 'post_combat_splash_heal'
    desc = "Recover HP for allies in a range defined by the PostCombatSplashHealAOE component"
    tag = SkillTags.COMBAT2
    paired_with = ('post_combat_splash_heal_aoe', )

    expose = ComponentType.Int
    value = 0
    author = 'Lord_Tweed, Beccarte'

    def post_combat_damage(self) -> int:
        return self.value

class PostCombatSplashHealAOE(SkillComponent):
    nid = 'post_combat_splash_heal_aoe'
    desc = 'Defines the range for PostCombatSplashHeal healing to hit.'
    tag = SkillTags.COMBAT2
    paired_with = ('post_combat_splash_heal', )

    expose = ComponentType.Int
    value = 0
    author = 'Lord_Tweed, Beccarte'

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target):
            r = set(range(self.value+1))
            locations = game.target_system.get_shell({unit.position}, r, game.board.bounds)
            healing = get_pc_damage(unit, self.skill)
            if healing > 0:
                for loc in locations:
                    target2 = game.board.get_unit(loc)
                    if target2 and target2 is not target and skill_system.check_ally(unit, target2):
                        end_health = target2.get_hp() + healing
                        action.do(action.SetHP(target2, min(target2.get_max_hp(), end_health)))

    def get_pc_damage(unit, skill) -> int:
        for component in skill.components:
            if component.defines('post_combat_damage'):
                return component.post_combat_damage()
        return 0  # 0 is default

class GiveStatusBeforeCombat(SkillComponent):
    nid = 'give_status_before_combat'
    desc = "Gives a status to target enemy before combat"
    tag = SkillTags.COMBAT2

    expose = ComponentType.Skill
    author = 'Beccarte'
    
    def start_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target):
            action.do(action.AddSkill(target, self.value, unit))
            action.do(action.TriggerCharge(unit, self.skill))




class RecoilPercent(SkillComponent):
    nid = 'recoil_percent'
    desc = "Unit takes non-lethal MaxHP percent damage after combat with an enemy"
    tag = SkillTags.COMBAT2

    expose = ComponentType.Float
    value = 0

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target):
            end_health = int(unit.get_hp() -
                             (unit.get_max_hp() * self.value))
            action.do(action.SetHP(unit, max(1, end_health)))
            action.do(action.TriggerCharge(unit, self.skill))

class EvalRecoilPercent(SkillComponent):
    nid = 'eval_recoil_percent'
    desc = "Unit takes non-lethal MaxHP percent damage after combat with an enemy solved using evaluate"
    tag = SkillTags.COMBAT2

    expose = ComponentType.String

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target):
            from app.engine import evaluate
            try:
                end_health = int(unit.get_hp() - (unit.get_max_hp() * evaluate.evaluate(self.value, unit, local_args={'item': item})))
                action.do(action.SetHP(unit, max(1, end_health)))
                action.do(action.TriggerCharge(unit, self.skill))
            except Exception as e:
                logging.error("Couldn't evaluate %s conditional (%s)", self.value, e)
                end_health = int(unit.get_hp())

class SavageBlowFates10P(SkillComponent):
    nid = 'savage_blow_fates_ten_per'
    desc = 'Deals 10% Current HP damage to enemies within the given number of spaces from target.'
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 0
    author = 'Lord_Tweed'

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target):
            r = set(range(self.value + 1))
            locations = game.target_system.get_shell({target.position}, r, game.board.bounds)
            for loc in locations:
                target2 = game.board.get_unit(loc)
                if target2 and target2 is not target and skill_system.check_enemy(unit, target2):
                    original_hp = target2.get_hp()

                    # Calculate 10% damage
                    damage = int(original_hp * 0.1)

                    if unit.team == 'player':
                        damage = max(1, damage)
                        final_hp = max(0, original_hp - damage)
                    else:
                        if original_hp > 1:
                            damage = max(1, min(damage, original_hp - 1))
                            final_hp = original_hp - damage
                        else:
                            damage = 0
                            final_hp = original_hp

                    if damage > 0:
                        action.do(action.SetHP(target2, final_hp))

                        # Lex Talionis-specific death trigger
                        if final_hp == 0:
                            action.do(action.Die(target2))

class SavageBlowFates30P(SkillComponent):
    nid = 'savage_blow_fates_Thirty_Per'
    desc = 'Deals 30% Current HP damage to enemies within the given number of spaces from target.'
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 0
    author = 'Lord_Tweed'

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target):
            r = set(range(self.value + 1))
            locations = game.target_system.get_shell({target.position}, r, game.board.bounds)
            for loc in locations:
                target2 = game.board.get_unit(loc)
                if target2 and target2 is not target and skill_system.check_enemy(unit, target2):
                    original_hp = target2.get_hp()

                    # Calculate 10% damage
                    damage = int(original_hp * 0.3)

                    if unit.team == 'player':
                        damage = max(1, damage)
                        final_hp = max(0, original_hp - damage)
                    else:
                        if original_hp > 1:
                            damage = max(1, min(damage, original_hp - 1))
                            final_hp = original_hp - damage
                        else:
                            damage = 0
                            final_hp = original_hp

                    if damage > 0:
                        action.do(action.SetHP(target2, final_hp))

                        # Lex Talionis-specific death trigger
                        if final_hp == 0:
                            action.do(action.Die(target2))

class SavageBlowFates40P(SkillComponent):
    nid = 'savage_blow_fates_Forty_Per'
    desc = 'Deals 40% Current HP damage to enemies within the given number of spaces from target.'
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 0
    author = 'Lord_Tweed'

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target):
            r = set(range(self.value + 1))
            locations = game.target_system.get_shell({target.position}, r, game.board.bounds)
            for loc in locations:
                target2 = game.board.get_unit(loc)
                if target2 and target2 is not target and skill_system.check_enemy(unit, target2):
                    original_hp = target2.get_hp()

                    # Calculate 10% damage
                    damage = int(original_hp * 0.4)

                    if unit.team == 'player':
                        damage = max(1, damage)
                        final_hp = max(0, original_hp - damage)
                    else:
                        if original_hp > 1:
                            damage = max(1, min(damage, original_hp - 1))
                            final_hp = original_hp - damage
                        else:
                            damage = 0
                            final_hp = original_hp

                    if damage > 0:
                        action.do(action.SetHP(target2, final_hp))

                        # Lex Talionis-specific death trigger
                        if final_hp == 0:
                            action.do(action.Die(target2))

class SavageBlowFates50P(SkillComponent):
    nid = 'savage_blow_fates_Fifty_Per'
    desc = 'Deals 50% Current HP damage to enemies within the given number of spaces from target.'
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 0
    author = 'Lord_Tweed'

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target):
            r = set(range(self.value + 1))
            locations = game.target_system.get_shell({target.position}, r, game.board.bounds)
            for loc in locations:
                target2 = game.board.get_unit(loc)
                if target2 and target2 is not target and skill_system.check_enemy(unit, target2):
                    original_hp = target2.get_hp()

                    # Calculate 10% damage
                    damage = int(original_hp * 0.5)

                    if unit.team == 'player':
                        damage = max(1, damage)
                        final_hp = max(0, original_hp - damage)
                    else:
                        if original_hp > 1:
                            damage = max(1, min(damage, original_hp - 1))
                            final_hp = original_hp - damage
                        else:
                            damage = 0
                            final_hp = original_hp

                    if damage > 0:
                        action.do(action.SetHP(target2, final_hp))

                        # Lex Talionis-specific death trigger
                        if final_hp == 0:
                            action.do(action.Die(target2))

class SavageBlowFates60P(SkillComponent):
    nid = 'savage_blow_fates_Sixty_Per'
    desc = 'Deals 60% Current HP damage to enemies within the given number of spaces from target.'
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 0
    author = 'Lord_Tweed'

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target):
            r = set(range(self.value + 1))
            locations = game.target_system.get_shell({target.position}, r, game.board.bounds)
            for loc in locations:
                target2 = game.board.get_unit(loc)
                if target2 and target2 is not target and skill_system.check_enemy(unit, target2):
                    original_hp = target2.get_hp()

                    # Calculate 10% damage
                    damage = int(original_hp * 0.6)

                    if unit.team == 'player':
                        damage = max(1, damage)
                        final_hp = max(0, original_hp - damage)
                    else:
                        if original_hp > 1:
                            damage = max(1, min(damage, original_hp - 1))
                            final_hp = original_hp - damage
                        else:
                            damage = 0
                            final_hp = original_hp

                    if damage > 0:
                        action.do(action.SetHP(target2, final_hp))

                        # Lex Talionis-specific death trigger
                        if final_hp == 0:
                            action.do(action.Die(target2))

class UpkeepDamageNonFatal(SkillComponent):
    nid = 'upkeep_damage_nonfatal'
    desc = "Unit takes damage at upkeep. Doesn't kill player units or bosses."
    tag = SkillTags.STATUS

    expose = ComponentType.Int
    value = 5

    def _playback_processing(self, playback, unit, hp_change):
        # Playback
        if hp_change < 0:
            playback.append(pb.HitSound('Attack Hit ' + str(random.randint(1, 5))))
            playback.append(pb.UnitTintAdd(unit, (255, 255, 255)))
            playback.append(pb.DamageNumbers(unit, self.value))
        elif hp_change > 0:
            playback.append(pb.HitSound('MapHeal'))
            if hp_change >= 30:
                name = 'MapBigHealTrans'
            elif hp_change >= 15:
                name = 'MapMediumHealTrans'
            else:
                name = 'MapSmallHealTrans'
            playback.append(pb.CastAnim(name))
            playback.append(pb.DamageNumbers(unit, self.value))

    def on_upkeep(self, actions, playback, unit):
        # Determine whether the unit is protected from death
        is_protected = unit.team == 'player' or 'Boss' in unit.tags

        # Default HP change is full damage
        hp_change = -self.value

        # Apply non-lethal logic only to protected units
        if is_protected:
            max_damage = unit.get_hp() - 1
            effective_damage = min(self.value, max_damage)
            if effective_damage <= 0:
                return  # No damage to apply
            hp_change = -effective_damage

        # Other units take full damage — can die from this

        actions.append(action.ChangeHP(unit, hp_change))
        actions.append(action.TriggerCharge(unit, self.skill))
        self._playback_processing(playback, unit, hp_change)
        skill_system.after_take_strike(actions, playback, unit, None, None, None, 'defense', (0, 0), Strike.HIT)

class MultiDescSkill(SkillComponent):
    nid = 'multi_desc_skill'
    desc = "Define a list of Skill NIDs whose info boxes should be attached to this skill's multi desc info box."
    tag = SkillTags.ADVANCED
    author = 'Eretein'
    
    expose = (ComponentType.List, ComponentType.Skill)
    
    def multi_desc(self, unit, skill) ->  tuple[list[str], ComponentType]:
        return self.value, self.expose[1]

class MultiDescItem(SkillComponent):
    nid = 'multi_desc_item'
    desc = "Define a list of Item NIDs whose info boxes should be attached to this skill's multi desc info box."
    tag = SkillTags.ADVANCED
    
    author = "Eretein"
    
    expose = (ComponentType.List, ComponentType.Item)
    
    def multi_desc(self, unit, skill) ->  tuple[list[str], ComponentType]:
        return self.value, self.expose[1]

class EndstepChargeIncrease(SkillComponent):
    nid = 'Endstep_charge_increase'
    desc = "Increases charge of skill by the *value* set here each endstep. Usually used in conjunction with `Build Charge` skill component. Will not go below 0 or above `total_charge`"
    tag = SkillTags.CHARGE

    expose = ComponentType.Int
    value = 5

    ignore_conditional = True

    def on_endstep(self, actions, playback, unit):
        new_value = self.skill.data['charge'] + self.value
        new_value = utils.clamp(new_value, 0, self.skill.data['total_charge'])
        action.do(action.SetObjData(self.skill, 'charge', new_value))
        

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
 
