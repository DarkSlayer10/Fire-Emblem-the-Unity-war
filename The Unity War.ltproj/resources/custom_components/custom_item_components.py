from __future__ import annotations

from app.data.database.components import ComponentType
from app.data.database.database import DB
from app.data.database.item_components import ItemComponent, ItemTags
from app.engine import (action, banner, combat_calcs, engine, equations,
                        image_mods, item_funcs, item_system, skill_system,
                        target_system, evaluate)

from app.engine.game_state import game
from app.engine.objects.unit import UnitObject
from app.utilities import utils, static_random
from app.engine.movement import movement_funcs
import app.engine.combat.playback as pb
import logging
from app.data.database.difficulty_modes import RNGOption
from app.engine.item_components.hit_components import Steal

from app.data.database.skill_components import SkillComponent, SkillTags

from app.engine.skill_components import advanced_components

from app.utilities import utils, static_random
from app.data.resources.resources import RESOURCES
from app.engine import config as cf
from app.engine.combat import playback as pb
import random, logging




class DoNothing(ItemComponent):
    nid = 'do_nothing'
    desc = 'does nothing'
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 1

class StealFullInventoryWIP(ItemComponent):
    nid = 'steal_full_inventory'
    desc = "Steal any unequipped item from target on hit"
    tag = ItemTags.CUSTOM
    author = "TheD4rkblade"

    _did_steal = False

    def init(self, item):
        item.data['target_item'] = None

    def target_restrict(self, unit, item, def_pos, splash) -> bool:
        # Unit has item that can be stolen
        attack = equations.parser.steal_atk(unit)
        defender = game.board.get_unit(def_pos)
        defense = equations.parser.steal_def(defender)
        if attack >= defense:
            for def_item in defender.items:
                if self.item_restrict(unit, item, defender, def_item):
                    return True
        return False

    def valid_targets(self, unit, item):
        positions = set()
        for other in game.units:
            if other.position and skill_system.check_enemy(unit, other):
                for def_item in other.items:
                    if self.item_restrict(unit, item, other, def_item):
                        positions.add(other.position)
                        break
        return positions

    def targets_items(self, unit, item) -> bool:
        return True
 
    def item_restrict(self, unit, item, defender, def_item) -> bool:
        if item_system.unstealable(defender, def_item):
            return False
        if def_item is defender.get_weapon():
            return False
        if item_funcs.inventory_full(unit, def_item):
            return True if unit.team == 'player' else False
        return True

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        target_item = item.data.get('target_item')
        if target_item:
            actions.append(action.RemoveItem(target, target_item))
            actions.append(action.DropItem(unit, target_item))
            if unit.team != 'player':
                actions.append(action.MakeItemDroppable(unit, target_item))
            actions.append(action.UpdateRecords('steal', (unit.nid, target.nid, target_item.nid)))
            self._did_steal = True

    def end_combat(self, playback, unit, item, target, item2, mode):
        if self._did_steal:
            if item_funcs.inventory_full(unit, item):
                game.memory['item_discard_current_unit'] = unit
                game.state.change('item_discard')
            target_item = item.data.get('target_item')
            game.alerts.append(banner.StoleItem(unit, target_item))
            game.state.change('alert')
        item.data['target_item'] = None
        self._did_steal = False

    def ai_priority(self, unit, item, target, move):
        if target:
            steal_term = 0.075
            enemy_positions = utils.average_pos({other.position for other in game.units if other.position and skill_system.check_enemy(unit, other)})
            distance_term = utils.calculate_distance(move, enemy_positions)
            return steal_term + 0.01 * distance_term
        return 0
 
class MagicWeaponRank(ItemComponent):
    nid = 'magic_weapon_rank'
    desc = "Item is a magic weapon, and has a wrank"
    requires = ['weapon_type']
    tag = ItemTags.CUSTOM

    expose = ComponentType.WeaponRank

    def weapon_rank(self, unit, item):
        return self.value

    def available(self, unit, item):
        required_wexp = DB.weapon_ranks.get(self.value).requirement
        weapon_type = item_system.weapon_type(unit, item)
        optional_tag = 'Magician'
        if weapon_type:
            return (unit.wexp.get(weapon_type) >= required_wexp or optional_tag in unit.tags)
        else:  # If no weapon type, then always available
            return True

class StealCon(ItemComponent):
    nid = 'steal_con'
    desc = "Steal any unequipped item from target on hit, only if user's CON exceeds item's weight"
    tag = ItemTags.CUSTOM

    _did_steal = False

    def init(self, item):
        item.data['target_item'] = None

    def target_restrict(self, unit, item, def_pos, splash) -> bool:
        # Unit has item that can be stolen
        attack = equations.parser.steal_atk(unit)
        defender = game.board.get_unit(def_pos)
        defense = equations.parser.steal_def(defender)
        if attack >= defense:
            for def_item in defender.items:
                if self.item_restrict(unit, item, defender, def_item):
                    return True
        return False

    def ai_targets(self, unit, item):
        positions = set()
        for other in game.units:
            if other.position and skill_system.check_enemy(unit, other):
                for def_item in other.items:
                    if self.item_restrict(unit, item, other, def_item):
                        positions.add(other.position)
                        break
        return positions

    def targets_items(self, unit, item) -> bool:
        return True

    def item_restrict(self, unit, item, defender, def_item) -> bool:
        if item_system.unstealable(defender, def_item):
            return False
        if item_funcs.inventory_full(unit, def_item):
            return False
        if def_item is defender.get_weapon():
            return False
        if def_item.components.get('weight') and unit.get_stat('CON') < def_item.components.get('weight').value:
            return False
        return True

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        target_item = item.data.get('target_item')
        if target_item:
            actions.append(action.RemoveItem(target, target_item))
            actions.append(action.DropItem(unit, target_item))
            if unit.team != 'player':
                actions.append(action.MakeItemDroppable(unit, target_item))
            actions.append(action.UpdateRecords('steal', (unit.nid, target.nid, target_item.nid)))
            self._did_steal = True

    def end_combat(self, playback, unit, item, target, item2, mode):
        if self._did_steal:
            target_item = item.data.get('target_item')
            game.alerts.append(banner.StoleItem(unit, target_item))
            game.state.change('alert')
        item.data['target_item'] = None
        self._did_steal = False

    def ai_priority(self, unit, item, target, move):
        if target:
            steal_term = 0.075
            enemy_positions = utils.average_pos({other.position for other in game.units if other.position and skill_system.check_enemy(unit, other)})
            distance_term = utils.calculate_distance(move, enemy_positions)
            return steal_term + 0.01 * distance_term
        return 0

class EvalMaximumRange(ItemComponent):
    nid = 'eval_max_range'
    desc = "Set the maximum_range of the item solved using evaluate"
    tag = ItemTags.CUSTOM

    expose = ComponentType.String
    value = 0

    def maximum_range(self, unit, item) -> int:
        from app.engine import evaluate
        try:
            return int(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except Exception as e:
            logging.error("Couldn't evaluate %s conditional (%s)", self.value, e)
        return 0

class DamageAny(ItemComponent):
    nid = 'damage_any'
    desc = "Item does damage on hit. Can target allies."
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 0

    def damage(self, unit, item):
        return self.value

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        playback_nids = [brush.nid for brush in playback]
        if 'attacker_partner_phase' in playback_nids or 'defender_partner_phase' in playback_nids:
            damage = combat_calcs.compute_assist_damage(unit, target, item, target.get_weapon(), mode, attack_info)
        else:
            damage = combat_calcs.compute_damage(unit, target, item, target.get_weapon(), mode, attack_info)

        # Reduce damage if in Grandmaster Mode
        if game.mode.rng_choice == RNGOption.GRANDMASTER:
            hit = utils.clamp(combat_calcs.compute_hit(unit, target, item, target.get_weapon(), mode, attack_info), 0, 100)
            damage = int(damage * float(hit) / 100)

        true_damage = min(damage, target.get_hp())
        actions.append(action.ChangeHP(target, -damage))

        # For animation
        playback.append(pb.DamageHit(unit, item, target, damage, true_damage))
        if damage == 0:
            playback.append(pb.HitSound('No Damage'))
            playback.append(pb.HitAnim('MapNoDamage', target))

    def on_glancing_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        playback_nids = [brush.nid for brush in playback]
        if 'attacker_partner_phase' in playback_nids or 'defender_partner_phase' in playback_nids:
            damage = combat_calcs.compute_assist_damage(unit, target, item, target.get_weapon(), mode, attack_info)
        else:
            damage = combat_calcs.compute_damage(unit, target, item, target.get_weapon(), mode, attack_info)

        # Reduce damage if in Grandmaster Mode
        if game.mode.rng_choice == RNGOption.GRANDMASTER:
            hit = utils.clamp(combat_calcs.compute_hit(unit, target, item, target.get_weapon(), mode, attack_info), 0, 100)
            damage = int(damage * float(hit) / 100)

        damage //= 2  # Because glancing hit

        true_damage = min(damage, target.get_hp())
        actions.append(action.ChangeHP(target, -damage))

        # For animation
        playback.append(pb.DamageHit(unit, item, target, damage, true_damage))
        if damage == 0:
            playback.append(pb.HitAnim('MapNoDamage', target))
        else:
            playback.append(pb.HitAnim('MapGlancingHit', target))

    def on_crit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        playback_nids = [brush.nid for brush in playback]
        if 'attacker_partner_phase' in playback_nids or 'defender_partner_phase' in playback_nids:
            damage = combat_calcs.compute_assist_damage(unit, target, item, target.get_weapon(), mode, attack_info, crit=True)
        else:
            damage = combat_calcs.compute_damage(unit, target, item, target.get_weapon(), mode, attack_info, crit=True)
 
        # Reduce damage if in Grandmaster Mode (although crit doesn't make much sense with Grandmaster mode)
        if game.mode.rng_choice == RNGOption.GRANDMASTER:
            hit = utils.clamp(combat_calcs.compute_hit(unit, target, item, target.get_weapon(), mode, attack_info), 0, 100)
            damage = int(damage * float(hit) / 100)

        true_damage = min(damage, target.get_hp())
        actions.append(action.ChangeHP(target, -damage))

        playback.append(pb.DamageCrit(unit, item, target, damage, true_damage))
        if damage == 0:
            playback.append(pb.HitSound('No Damage'))
            playback.append(pb.HitAnim('MapNoDamage', target))

class ShoveOnEndCombatInitiate(ItemComponent):
    nid = 'shove_on_end_combat_initiate'
    desc = "Item shoves target at the end of combat, only on initiation"
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 1

    def _check_shove(self, unit_to_move, anchor_pos, magnitude):
        offset_x = utils.clamp(unit_to_move.position[0] - anchor_pos[0], -1, 1)
        offset_y = utils.clamp(unit_to_move.position[1] - anchor_pos[1], -1, 1)
        new_position = (unit_to_move.position[0] + offset_x * magnitude,
                        unit_to_move.position[1] + offset_y * magnitude)

        mcost = movement_funcs.get_mcost(unit_to_move, new_position)
        #If we could pass through it if we had movement, allow the action to occur
        if mcost != 99:
            mcost = 0
        if game.board.check_bounds(new_position) and \
                not game.board.get_unit(new_position) and \
                mcost <= equations.parser.movement(unit_to_move):
            return new_position
        return False
    
    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and not skill_system.ignore_forced_movement(target) and mode and mode == 'attack':
            new_position = self._check_shove(target, unit.position, self.value)
            if new_position:
                action.do(action.ForcedMovement(target, new_position))

class ShoveFlexibleOnEndCombatInitiate(ItemComponent):
    nid = 'shove_flexible_on_end_combat_initiate'
    desc = "Item shoves target at the end of combat, only on initiation. Target will stop if they hit a wall."
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 1

    def _check_shove(self, unit_to_move, anchor_pos, magnitude):
        curr_magnitude = 0
        ret_position = None
        while(abs(curr_magnitude) < abs(magnitude)):
            if magnitude < 0:
                curr_magnitude -= 1
            else:
                curr_magnitude += 1
            offset_x = utils.clamp(unit_to_move.position[0] - anchor_pos[0], -1, 1)
            offset_y = utils.clamp(unit_to_move.position[1] - anchor_pos[1], -1, 1)
            new_position = (unit_to_move.position[0] + offset_x * curr_magnitude,
                            unit_to_move.position[1] + offset_y * curr_magnitude)

            mcost = movement_funcs.get_mcost(unit_to_move, new_position)
            if game.board.check_bounds(new_position) and \
                    not game.board.get_unit(new_position) and \
                    mcost <= equations.parser.movement(unit_to_move):
                ret_position = new_position
            else:
                magnitude = 0
        if not ret_position:
            return False
        return ret_position
    
    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and not skill_system.ignore_forced_movement(target) and mode and mode == 'attack':
            new_position = self._check_shove(target, unit.position, self.value)
            if new_position:
                action.do(action.ForcedMovement(target, new_position))

class EvalHPCost(ItemComponent):
    nid = 'eval_hp_cost'
    desc = "Item subtracts the specified amount of HP upon use. If the subtraction would kill the unit the item becomes unusable."
    tag = ItemTags.CUSTOM

    expose = ComponentType.String
    value = ""

    _did_something = False

    def _check_value(self, unit, item) -> int:
        from app.engine import evaluate
        try:
            return int(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except:
            print("Couldn't evaluate %s conditional" % self.value)
        return 0
    
    def available(self, unit, item) -> bool:
        return unit.get_hp() > self._check_value(unit, item)

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        self._did_something = True

    def on_miss(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        self._did_something = True

    def end_combat(self, playback, unit, item, target, item2, mode):
        value = self._check_value(unit, item)
        if self._did_something:
            action.do(action.ChangeHP(unit, -value))
        self._did_something = False

    def reverse_use(self, unit, item):
        value = self._check_value(unit, item)
        action.do(action.ChangeHP(unit, value))

class ShoveFlexibleStops(ItemComponent):
    nid = 'shove_flex_stops'
    desc = "Item shoves target on hit up to X spaces, can be shortened by obstacles"
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 1

    def _check_shove(self, unit_to_move, anchor_pos, magnitude):
        curr_magnitude = 0
        ret_position = None
        while(abs(curr_magnitude) < abs(magnitude)):
            if magnitude < 0:
                curr_magnitude -= 1
            else:
                curr_magnitude += 1
            offset_x = utils.clamp(unit_to_move.position[0] - anchor_pos[0], -1, 1)
            offset_y = utils.clamp(unit_to_move.position[1] - anchor_pos[1], -1, 1)
            new_position = (unit_to_move.position[0] + offset_x * curr_magnitude,
                            unit_to_move.position[1] + offset_y * curr_magnitude)

            mcost = movement_funcs.get_mcost(unit_to_move, new_position)
            if game.board.check_bounds(new_position) and \
                    not game.board.get_unit(new_position) and \
                    mcost <= equations.parser.movement(unit_to_move):
                ret_position = new_position
            else:
                magnitude = 0
        if not ret_position:
            return False
        return ret_position

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        if target and not skill_system.ignore_forced_movement(target):
            new_position = self._check_shove(target, unit.position, self.value)
            if new_position:
                actions.append(action.ForcedMovement(target, new_position))
                playback.append(pb.ShoveHit(unit, item, target))
                
class PermanentStatChangeEarly(ItemComponent):
    nid = 'permanent_stat_change_early'
    desc = "Using this item permanently changes the stats of the target in the specified ways. The target and user are often the same unit (think of normal FE stat boosters)."
    tag = ItemTags.CUSTOM

    expose = (ComponentType.Dict, ComponentType.Stat)

    def _target_restrict(self, defender):
        klass = DB.classes.get(defender.klass)
        for stat, inc in self.value:
            if inc <= 0 or defender.stats[stat] < klass.max_stats.get(stat, 30):
                return True
        return False

    def target_restrict(self, unit, item, def_pos, splash) -> bool:
        # Ignore's splash
        defender = game.board.get_unit(def_pos)
        if not defender:
            return True
        return self._target_restrict(defender)

    def simple_target_restrict(self, unit, item):
        return self._target_restrict(unit)

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        stat_changes = {k: v for (k, v) in self.value}
        klass = DB.classes.get(target.klass)
        # clamp stat changes
        stat_changes = {k: utils.clamp(v, -target.stats[k], klass.max_stats.get(k, 30) - target.stats[k]) for k, v in stat_changes.items()}
        action.do(action.ApplyStatChanges(target, stat_changes))
        if any(v != 0 for v in stat_changes.values()):
            game.memory['stat_changes'] = stat_changes
            game.exp_instance.append((target, 0, None, 'stat_booster'))
            game.state.change('exp')

class StatusesAfterCombatOnHit(ItemComponent):
    nid = 'statuses_after_combat_on_hit'
    desc = "If the target is hit they gain the specified statuses at the end of combat. Prevents changes being applied mid-combat."
    tag = ItemTags.CUSTOM
    author = 'BigMood, Lord_Tweed'

    expose = (ComponentType.List, ComponentType.Skill)  # Nid

    _did_hit = set()

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        self._did_hit.add(target)

    def end_combat(self, playback, unit, item, target, item2, mode):
        for target in self._did_hit:
            for status_nid in self.value:
                act = action.AddSkill(target, status_nid, unit)
                action.do(act)
        self._did_hit.clear()

    def ai_priority(self, unit, item, target, move):
        # Do I add a new status to the target
        return ai_status_priority(unit, target, item, move, self.value)

class EvalEnemyBlastAOE(ItemComponent):
    nid = 'eval_smartblast_aoe'
    desc = "Grants EVAL Enemy AoE range."
    tag = ItemTags.CUSTOM

    expose = ComponentType.String

    def _get_power(self, unit) -> int:
        from app.engine import evaluate
        try:
            base_power = int(evaluate.evaluate(self.value, unit))
        except Exception as e:
            logging.error("Couldn't evaluate %s conditional (%s)", self.value, e)
            base_power = 0
        empowered_splash = skill_system.empower_splash(unit)
        return base_power + 1 + empowered_splash

    def splash(self, unit, item, position) -> tuple:
        ranges = set(range(self._get_power(unit)))
        splash = game.target_system.find_manhattan_spheres(ranges, position[0], position[1])
        splash = {pos for pos in splash if game.board.check_bounds(pos)}
        from app.engine import item_system, skill_system
        if item_system.is_spell(unit, item):
            # spell blast
            splash = [game.board.get_unit(s) for s in splash]
            splash = [s.position for s in splash if s and skill_system.check_enemy(unit, s)]
            return None, splash
        else:
            # regular blast
            splash = [game.board.get_unit(s) for s in splash if s != position]
            splash = [s.position for s in splash if s and skill_system.check_enemy(unit, s)]
            return position if game.board.get_unit(position) else None, splash

    def splash_positions(self, unit, item, position) -> set:
        from app.engine import skill_system
        ranges = set(range(self._get_power(unit)))
        splash = game.target_system.find_manhattan_spheres(ranges, position[0], position[1])
        splash = {pos for pos in splash if game.tilemap.check_bounds(pos)}
        # Doesn't highlight allies positions
        splash = {pos for pos in splash if not game.board.get_unit(pos) or skill_system.check_enemy(unit, game.board.get_unit(pos))}
        return splash

class SelfUnloadUnit(ItemComponent):
    nid = 'self_unload_unit'
    desc = "Places the unit stored through the store unit component on the specified target (most often a tile). Uses the user's movement to check valid tiles."
    tag = ItemTags.CUSTOM

    def target_restrict(self, unit, item, def_pos, splash) -> bool:
        if def_pos and not game.board.get_unit(def_pos) and movement_funcs.check_weakly_traversable(unit, def_pos):
            return True
        return False

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        if self.item.data.get('stored_unit'):
            rescuee = game.get_unit(self.item.data['stored_unit'])
            self.item.data['stored_unit'] = None
            if rescuee:
                actions.append(action.Warp(rescuee, target_pos))
                # Move camera over position
                game.cursor.set_pos(target_pos)
                
class BlitzStrike(ItemComponent):
    nid = 'galeforce_on_crit'
    desc = "Item causes wielder to move again after crit. Subtracts a charge from Blitz Strike."
    tag = ItemTags.CUSTOM

    def on_crit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        unit._fields['blitz_strike'] = True
        
    def end_combat(self, playback, unit, item, target, item2, mode):
        if 'blitz_strike' in unit._fields and unit._fields['blitz_strike']:
            action.do(action.AddSkill(unit, 'Galeforce_Status'))
            from app.engine import evaluate
            action.do(action.TriggerCharge(unit, evaluate.evaluate("get_skill(unit, 'Blitz_Strike')", unit1=unit)))
            unit._fields['blitz_strike'] = False
                
class RestrictRankMagic(ItemComponent):
    nid = 'restrict_rank_magic'
    desc = "Item cannot be used unless at or below the given rank if magic"
    tag = ItemTags.CUSTOM

    expose = ComponentType.WeaponRank

    def available(self, unit, item):
        return not item_system.weapon_type(unit, item) in ['Anima', 'Dark', 'Staff', 'Light'] or DB.weapon_ranks.get(self.value).requirement >= DB.weapon_ranks.get(item_system.weapon_rank(unit, item)).requirement
        
class WeaponTypeExempt(ItemComponent):
    nid = 'weapon_type_exempt'
    desc = "Categorizes a weapon type but does not require the wielder to be able to use that weapon type"
    tag = ItemTags.CUSTOM

    expose = ComponentType.WeaponType

    def weapon_type(self, unit, item):
        return self.value

    def available(self, unit, item) -> bool:
        return True

class PivotOnEndCombatInitiate(ItemComponent):
    nid = 'pivot_on_end_combat_initiate'
    desc = "Item pivots over target at the end of combat, only on initiation"
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 1

    def _check_pivot(self, unit_to_move, anchor_pos, magnitude):
        offset_x = utils.clamp(unit_to_move.position[0] - anchor_pos[0], -1, 1)
        offset_y = utils.clamp(unit_to_move.position[1] - anchor_pos[1], -1, 1)
        new_position = (anchor_pos[0] + offset_x * -magnitude,
                        anchor_pos[1] + offset_y * -magnitude)

        mcost = movement_funcs.get_mcost(unit_to_move, new_position)
        #If we could pass through it if we had movement, allow the action to occur
        if mcost != 99:
            mcost = 0
        if game.board.check_bounds(new_position) and \
                not game.board.get_unit(new_position) and \
                mcost <= equations.parser.movement(unit_to_move):
            return new_position
        return False
    
    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and not skill_system.ignore_forced_movement(unit) and mode and mode == 'attack':
            new_position = self._check_pivot(unit, target.position, self.value)
            if new_position:
                action.do(action.Teleport(unit, new_position))
                
class Locked2(ItemComponent):
    nid = 'locked_2'
    desc = 'Item cannot be taken or dropped from a units inventory. However, the trade command can be used to rearrange its position, and event commands can remove the item.'
    tag = ItemTags.CUSTOM

    def locked(self, unit, item) -> bool:
        return True

    def unstealable(self, unit, item) -> bool:
        return True

class Backdash(ItemComponent):
    nid = 'backdash'
    desc = 'Unit shoves *itself* backwards from the target point.'
    tag = ItemTags.CUSTOM
    author = 'mag'

    expose = ComponentType.Int
    value = 1

    def _check_dash(self, target, user, magnitude):
        tpos = target.position
        upos = user.position
        offset = utils.tmult(utils.tclamp(utils.tuple_sub(upos, tpos), (-1, -1), (1, 1)), magnitude)
        npos = utils.tuple_add(upos, offset)

        mcost_user = movement_funcs.get_mcost(user, npos)
        if game.board.check_bounds(npos) and not game.board.get_unit(npos) and \
                mcost_user <= equations.parser.movement(user):
            return npos
        return None

    def target_restrict(self, unit, item, def_pos, splash) -> bool:
        target = game.board.get_unit(def_pos)
        if not target:
            return False
        new_position = self._check_dash(target, unit, self.value)
        if new_position:
            return True
        return False

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        if target and not skill_system.ignore_forced_movement(unit):
            new_position = self._check_dash(target, unit, self.value)
            if new_position:
                actions.append(action.ForcedMovement(unit, new_position))
                playback.append(pb.ShoveHit(unit, item, target))

class DrawBackOnEndCombatInitiate(ItemComponent):
    nid = 'draw_back_on_end_combat_initiate'
    desc = "Item moves both user and target back at the end of combat, only on initiation"
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 1

    def _check_draw_back(self, target, user, magnitude):
        offset_x = utils.clamp(target.position[0] - user.position[0], -1, 1)
        offset_y = utils.clamp(target.position[1] - user.position[1], -1, 1)
        new_position_user = (user.position[0] - offset_x * magnitude,
                             user.position[1] - offset_y * magnitude)
        new_position_target = (target.position[0] - offset_x * magnitude,
                               target.position[1] - offset_y * magnitude)

        mcost_user = movement_funcs.get_mcost(user, new_position_user)
        mcost_target = movement_funcs.get_mcost(target, new_position_target)
        #If we could pass through it if we had movement, allow the action to occur
        if mcost_user != 99:
            mcost_user = 0
        if mcost_target != 99:
            mcost_target = 0
        if game.board.check_bounds(new_position_user) and \
                not game.board.get_unit(new_position_user) and \
                mcost_user <= equations.parser.movement(user) and mcost_target <= equations.parser.movement(target):
            return new_position_user, new_position_target
        return None, None
    
    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and not skill_system.ignore_forced_movement(unit) and not skill_system.ignore_forced_movement(target) and mode and mode == 'attack':
            new_position_user, new_position_target = self._check_draw_back(target, unit, self.value)
            if new_position_user:
                action.do(action.Teleport(unit, new_position_user))
            if new_position_target and not game.board.get_unit(new_position_target):
                action.do(action.Teleport(target, new_position_target))

class EvalDamage(ItemComponent):
    nid = 'eval_damage'
    desc = "Item does damage on hit. Damage is evaluated."
    tag = ItemTags.WEAPON

    expose = ComponentType.String
    value = 0

    def damage(self, unit, item):
        from app.engine import evaluate
        try:
            return int(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except Exception as e:
            logging.error("EVAL DAMAGE: Couldn't evaluate %s conditional (%s)", self.value, e)
            return 0

    def target_restrict(self, unit, item, def_pos, splash) -> bool:
        # Restricts target based on whether any unit is an enemy
        defender = game.board.get_unit(def_pos)
        if defender and skill_system.check_enemy(unit, defender):
            return True
        for s_pos in splash:
            s = game.board.get_unit(s_pos)
            if s and skill_system.check_enemy(unit, s):
                return True
        return False

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        playback_nids = [brush.nid for brush in playback]
        if 'attacker_partner_phase' in playback_nids or 'defender_partner_phase' in playback_nids:
            damage = combat_calcs.compute_assist_damage(unit, target, item, target.get_weapon(), mode, attack_info)
        else:
            damage = combat_calcs.compute_damage(unit, target, item, target.get_weapon(), mode, attack_info)

        # Reduce damage if in Grandmaster Mode
        if game.mode.rng_choice == RNGOption.GRANDMASTER:
            hit = utils.clamp(combat_calcs.compute_hit(unit, target, item, target.get_weapon(), mode, attack_info), 0, 100)
            damage = int(damage * float(hit) / 100)

        true_damage = min(damage, target.get_hp())
        actions.append(action.ChangeHP(target, -damage))

        # For animation
        playback.append(pb.DamageHit(unit, item, target, damage, true_damage))
        if damage == 0:
            playback.append(pb.HitSound('No Damage'))
            playback.append(pb.HitAnim('MapNoDamage', target))

    def on_glancing_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        playback_nids = [brush.nid for brush in playback]
        if 'attacker_partner_phase' in playback_nids or 'defender_partner_phase' in playback_nids:
            damage = combat_calcs.compute_assist_damage(unit, target, item, target.get_weapon(), mode, attack_info)
        else:
            damage = combat_calcs.compute_damage(unit, target, item, target.get_weapon(), mode, attack_info)

        # Reduce damage if in Grandmaster Mode
        if game.mode.rng_choice == RNGOption.GRANDMASTER:
            hit = utils.clamp(combat_calcs.compute_hit(unit, target, item, target.get_weapon(), mode, attack_info), 0, 100)
            damage = int(damage * float(hit) / 100)

        damage //= 2  # Because glancing hit

        true_damage = min(damage, target.get_hp())
        actions.append(action.ChangeHP(target, -damage))

        # For animation
        playback.append(pb.DamageHit(unit, item, target, damage, true_damage))
        if damage == 0:
            playback.append(pb.HitAnim('MapNoDamage', target))
        else:
            playback.append(pb.HitAnim('MapGlancingHit', target))

    def on_crit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        playback_nids = [brush.nid for brush in playback]
        if 'attacker_partner_phase' in playback_nids or 'defender_partner_phase' in playback_nids:
            damage = combat_calcs.compute_assist_damage(unit, target, item, target.get_weapon(), mode, attack_info, crit=True)
        else:
            damage = combat_calcs.compute_damage(unit, target, item, target.get_weapon(), mode, attack_info, crit=True)

        # Reduce damage if in Grandmaster Mode (although crit doesn't make much sense with Grandmaster mode)
        if game.mode.rng_choice == RNGOption.GRANDMASTER:
            hit = utils.clamp(combat_calcs.compute_hit(unit, target, item, target.get_weapon(), mode, attack_info), 0, 100)
            damage = int(damage * float(hit) / 100)

        true_damage = min(damage, target.get_hp())
        actions.append(action.ChangeHP(target, -damage))

        playback.append(pb.DamageCrit(unit, item, target, damage, true_damage))
        if damage == 0:
            playback.append(pb.HitSound('No Damage'))
            playback.append(pb.HitAnim('MapNoDamage', target))

    def ai_status_priority_buff(unit, target, item, move, status_nid) -> float:
        if target and status_nid not in [skill.nid for skill in target.skills]:
            accuracy_term = utils.clamp(combat_calcs.compute_hit(unit, target, item, target.get_weapon(), "attack", (0, 0))/100., 0, 1)
            num_attacks = combat_calcs.outspeed(unit, target, item, target.get_weapon(), "attack", (0, 0))
            accuracy_term *= num_attacks
            # Tries to maximize distance from target
            distance_term = 0.01 * utils.calculate_distance(move, target.position)
            if skill_system.check_enemy(unit, target):
                return -0.5 * accuracy_term + distance_term
            else:
                return 0.5 * accuracy_term
        return 0

class BuffAlly(ItemComponent):
    nid = 'buff_ally'
    desc = "Target gains the specified status on hit. Only use this for staves that target allies."
    tag = ItemTags.CUSTOM

    expose = ComponentType.Skill  # Nid

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        act = action.AddSkill(target, self.value, unit)
        actions.append(act)
        playback.append(pb.StatusHit(unit, item, target, self.value))

    def ai_priority(self, unit, item, target, move):
        # Do I add a new status to the target
        return ai_status_priority_buff(unit, target, item, move, self.value)
        
class EventBeforeCombat(ItemComponent):
    nid = 'event_before_combat'
    desc = "The selected event plays at the beginning of combat."
    tag = ItemTags.SPECIAL

    expose = ComponentType.Event

    def start_combat(self, playback, unit, item, target, item2, mode):
        event_prefab = DB.events.get_from_nid(self.value)
        if event_prefab:
            local_args = {'item': item, 'item2': item2, 'mode': mode}
            game.events.trigger_specific_event(event_prefab.nid, unit, target, unit.position, local_args)
            
class EvalMagic(ItemComponent):
    nid = 'eval_magic'
    desc = 'Makes Item use magic damage formula under certain conditions'
    tag = ItemTags.WEAPON
    
    expose = ComponentType.String

    def damage_formula(self, unit, item):
        if self.active(unit, item):
            return 'MAGIC_DAMAGE'
        return 'DAMAGE'

    def resist_formula(self, unit, item):
        if self.active(unit, item):
            return 'MAGIC_DEFENSE'
        return 'DEFENSE'
        
    def active(self, unit, item) -> bool:
        from app.engine import evaluate
        try:
            return bool(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except:
            logging.error("EvalMagic: Couldn't evaluate %s conditional" % self.value)
        return False

class EvalDragon(ItemComponent):
    nid = 'eval_dragon'
    desc = 'Makes Item magical and use target lower defense under certain conditions'
    tag = ItemTags.WEAPON
    
    expose = ComponentType.String
    
    def damage_formula(self, unit, item):
        if self.active(unit, item):
            return 'MAGIC_DAMAGE'
        return 'DAMAGE'

    def resist_formula(self, unit, item):
        if self.active(unit, item):
            return 'WORSE_DEFENSE'
        return 'DEFENSE'
        
    def active(self, unit, item) -> bool:
        from app.engine import evaluate
        try:
            return bool(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except:
            logging.error("EvalMagic: Couldn't evaluate %s conditional" % self.value)
        return False
        
class EvalDragonMagic(ItemComponent):
    nid = 'eval_dragon_magic'
    desc = 'Makes Item magical and use target lower defense under certain conditions, still magical if conditions not met'
    tag = ItemTags.WEAPON
    
    expose = ComponentType.String
    
    def damage_formula(self, unit, item):
        return 'MAGIC_DAMAGE'

    def resist_formula(self, unit, item):
        if self.active(unit, item):
            return 'WORSE_DEFENSE'
        return 'MAGIC_DEFENSE'
        
    def active(self, unit, item) -> bool:
        from app.engine import evaluate
        try:
            return bool(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except:
            logging.error("EvalMagic: Couldn't evaluate %s conditional" % self.value)
        return False

class RemoveOnEndChapter(ItemComponent):
    nid = 'remove_on_end_chapter'
    desc = "This item is lost on chapter end."
    tag = ItemTags.USES
    
    def on_end_chapter(self, unit, item):
        if item:
            if item in game.party.convoy:
                action.do(action.RemoveItemFromConvoy(item))
            elif unit and item in unit.items:
                action.do(action.RemoveItem(unit, item))
            else:
                for other_unit in game.get_units_in_party():
                    if item in other_unit.items:
                        action.do(action.RemoveItem(other_unit, item))

class StartCooldown(ItemComponent):
    nid = 'start_cooldown'
    desc = "Item will be on cooldown at the beginning of the chapter. Place underneath Cooldown component."
    tag = ItemTags.USES


    def init(self, item):
        item.data['cooldown'] = item.data['starting_cooldown']

    def on_end_chapter(self, unit, item):
        item.data['cooldown'] = item.data['starting_cooldown']
    
    def on_upkeep(self, actions, playback, unit, item):
        if game.turncount == 1:
            # Prevents cooldown ticking on turn 1
            action.do(action.SetObjData(item, 'cooldown', item.data['starting_cooldown']))

class PivotAlwaysOnEndCombatInitiate(ItemComponent):
    nid = 'pivot_always_on_end_combat_initiate'
    desc = "Item pivots over target at the end of combat, only on initiation. Will always work unless terrain is completely impassable."
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 1

    def _check_pivot(self, unit_to_move, anchor_pos, magnitude):
        offset_x = utils.clamp(unit_to_move.position[0] - anchor_pos[0], -1, 1)
        offset_y = utils.clamp(unit_to_move.position[1] - anchor_pos[1], -1, 1)
        new_position = (anchor_pos[0] + offset_x * -magnitude,
                        anchor_pos[1] + offset_y * -magnitude)

        mcost = movement_funcs.get_mcost(unit_to_move, new_position)
        #If we could pass through it if we had movement, allow the action to occur
        if mcost != 99:
            mcost = -999
        if game.board.check_bounds(new_position) and \
                not game.board.get_unit(new_position) and \
                mcost <= equations.parser.movement(unit_to_move):
            return new_position
        return False
    
    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and not skill_system.ignore_forced_movement(unit) and mode and mode == 'attack':
            new_position = self._check_pivot(unit, target.position, self.value)
            if new_position:
                action.do(action.Teleport(unit, new_position))

class EvalWeight(ItemComponent):
    nid = 'eval_weight'
    desc = "Lowers attack speed. At first, subtracted from the CONSTITUTION equation. If negative, subtracts from overall attack speed. Value is evaluated."
    tag = ItemTags.WEAPON

    expose = ComponentType.String
    value = 0

    def modify_attack_speed(self, unit, item):
        from app.engine import evaluate
        try:
            new_value = int(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except Exception as e:
            logging.error("EVAL WEIGHT: Couldn't evaluate %s conditional (%s)", self.value, e)
            new_value = 0

        return -1 * max(0, new_value - equations.parser.constitution(unit))

    def modify_defense_speed(self, unit, item):
        from app.engine import evaluate
        try:
            new_value = int(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except Exception as e:
            logging.error("EVAL WEIGHT: Couldn't evaluate %s conditional (%s)", self.value, e)
            new_value = 0

        return -1 * max(0, new_value - equations.parser.constitution(unit))

    def modify_avoid(self, unit, item):
        from app.engine import evaluate
        try:
            new_value = int(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except Exception as e:
            logging.error("EVAL WEIGHT: Couldn't evaluate %s conditional (%s)", self.value, e)
            new_value = 0

        return -2 * max(0, new_value - equations.parser.constitution(unit))

class Unavailable(ItemComponent):
    nid = 'unavailable'
    desc = 'Item is not available and cannot be used under any circumstance.'
    tag = ItemTags.USES

    expose = ComponentType.String

    def available(self, unit, item) -> bool:
        return False

class RestoreAfterCombat(ItemComponent):
    nid = 'restore_after_combat'
    desc = "Item removes all negative statuses from target after combat. No targeting restriction."
    tag = ItemTags.UTILITY

    def _can_be_restored(self, status):
        return status.negative

    def end_combat(self, playback, unit, item, target, item2, mode):
        for skill in target.all_skills[:]:
            if self._can_be_restored(skill):
                actions.append(action.RemoveSkill(target, skill))
                playback.append(pb.RestoreHit(unit, item, target))

class StackCost(ItemComponent):
    nid = 'stack_cost'
    desc = "Item requires and uses a stack of the specified skill. Stack is lost at start of combat."
    tag = ItemTags.USES

    expose = ComponentType.Skill  # Nid
    
    def available(self, unit, item) -> bool:
        return self.value in [s.nid for s in unit.skills]

    def start_combat(self, playback, unit, item, target, item2, mode):
        action.do(action.AddSkill(unit, self.value, unit))
    
    def reverse_use(self, unit, item):
        action.do(action.RemoveSkill(unit, self.value))

class IgnoreWeaponDisadvantage(ItemComponent):
    nid = 'ignore_weapon_disadvantage'
    desc = "Weapon disadvantage defined in the weapon types editor is ignored by this item."
    tag = ItemTags.EXTRA

    author = 'Beccarte'

    def ignore_weapon_disadvantage(self, unit, item):
        return True

class AddedCritDamage(ItemComponent):
    nid = 'added_crit_damage'
    desc = "Item grants additional damage with critical hits."
    tag = ItemTags.BASE

    author = 'Beccarte'

    expose = ComponentType.Int
    value = 10

    def added_crit_damage(self, unit, item):
        return self.value

class EvalGlanceDamage(ItemComponent):
    nid = 'eval_glance_damage'
    desc = "Gives +X additional damage on glance solved using evaluate"
    tag = ItemTags.CUSTOM

    expose = ComponentType.String

    def modify_glance_damage(self, unit, item):
        from app.engine import evaluate
        try:
            return int(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except Exception as e:
            logging.error("Couldn't evaluate %s conditional (%s)", self.value, e)
        return 0
    
class HitDamage(ItemComponent):
    nid = 'hit_damage'
    desc = "Gives +X additional damage on hit"
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int

    def modify_hit_damage(self, unit, item):
        return self.value

class EvalHitDamage(ItemComponent):
    nid = 'eval_hit_damage'
    desc = "Gives +X additional damage on hit solved using evaluate"
    tag = ItemTags.CUSTOM

    expose = ComponentType.String

    def modify_hit_damage(self, unit, item):
        from app.engine import evaluate
        try:
            return int(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except Exception as e:
            logging.error("Couldn't evaluate %s conditional (%s)", self.value, e)
        return 0

class MultiplyHitDamage(ItemComponent):
    nid = 'multiply_hit_damage'
    desc = "Multiplies additional damage on hit solved using evaluate"
    tag = ItemTags.CUSTOM

    expose = ComponentType.Float
    value = 1.0

    def hit_damage_multiplier(self, unit, item):
        return self.value
    
class EventOnTrueHit(ItemComponent):
    nid = 'event_on_true_hit'
    desc = "The selected event plays on a true hit, if the unit will hit with this item. The event is triggered with args (unit1=attacking unit, unit2=target, item=item, position=attacking unit's position, target_pos=position of target, mode='attack' or 'defense', attack_info=a tuple containing which attack this is as the first element, and which subattack this is as the second element)"
    tag = ItemTags.SPECIAL

    expose = ComponentType.Event

    def on_true_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        event_prefab = DB.events.get_from_nid(self.value)
        if event_prefab:
            local_args = {'target_pos': target_pos, 'mode': mode, 'attack_info': attack_info, 'item': item}
            game.events.trigger_specific_event(event_prefab.nid, unit, target, unit.position, local_args)
            
class EventOnGlancingHit(ItemComponent):
    nid = 'event_on_glancing_hit'
    desc = "The selected event plays on a glancing hit, if the unit will hit with this item. The event is triggered with args (unit1=attacking unit, unit2=target, item=item, position=attacking unit's position, target_pos=position of target, mode='attack' or 'defense', attack_info=a tuple containing which attack this is as the first element, and which subattack this is as the second element)"
    tag = ItemTags.SPECIAL

    expose = ComponentType.Event

    def on_glancing_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        event_prefab = DB.events.get_from_nid(self.value)
        if event_prefab:
            local_args = {'target_pos': target_pos, 'mode': mode, 'attack_info': attack_info, 'item': item}
            game.events.trigger_specific_event(event_prefab.nid, unit, target, unit.position, local_args)
            
class StatusOnTrueHit(ItemComponent):
    nid = 'status_on_true_hit'
    desc = "Target gains the specified status on true hit. Applies instantly, potentially causing values to change mid-combat."
    tag = ItemTags.SPECIAL

    expose = ComponentType.Skill  # Nid

    def on_true_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        act = action.AddSkill(target, self.value, unit)
        actions.append(act)
        playback.append(pb.StatusHit(unit, item, target, self.value))

    def ai_priority(self, unit, item, target, move):
        # Do I add a new status to the target
        return ai_status_priority(unit, target, item, move, self.value)

class SelfStatusOnTrueHit(ItemComponent):
    nid = 'self_status_on_true_hit'
    desc = "User gains the specified status on true hit. Applies instantly, potentially causing values to change mid-combat."
    tag = ItemTags.SPECIAL

    expose = ComponentType.Skill  # Nid

    def on_true_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        act = action.AddSkill(unit, self.value, unit)
        actions.append(act)
        playback.append(pb.StatusHit(unit, item, unit, self.value))

    def ai_priority(self, unit, item, target, move):
        # Do I add a new status to the target
        return ai_status_priority(unit, unit, item, move, self.value)
    
class StatusOnGlancingHit(ItemComponent):
    nid = 'status_on_glancing_hit'
    desc = "Target gains the specified status on true hit. Applies instantly, potentially causing values to change mid-combat."
    tag = ItemTags.SPECIAL

    expose = ComponentType.Skill  # Nid

    def on_glancing_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        act = action.AddSkill(target, self.value, unit)
        actions.append(act)
        playback.append(pb.StatusHit(unit, item, target, self.value))

    def ai_priority(self, unit, item, target, move):
        # Do I add a new status to the target
        return ai_status_priority(unit, target, item, move, self.value)

class SelfStatusOnGlancingHit(ItemComponent):
    nid = 'self_status_on_true_hit'
    desc = "User gains the specified status on true hit. Applies instantly, potentially causing values to change mid-combat."
    tag = ItemTags.SPECIAL

    expose = ComponentType.Skill  # Nid

    def on_glancing_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        act = action.AddSkill(unit, self.value, unit)
        actions.append(act)
        playback.append(pb.StatusHit(unit, item, unit, self.value))

    def ai_priority(self, unit, item, target, move):
        # Do I add a new status to the target
        return ai_status_priority(unit, unit, item, move, self.value)

class EventAfterTrueHit(ItemComponent):
    nid = 'event_after_true_hit'
    desc = "The selected event plays after a hit, if the unit will hit with this item. The event is triggered with args (unit1=attacking unit, unit2=target, item=item, position=attacking unit's position, target_pos=position of target, mode='attack' or 'defense', attack_info=a tuple containing which attack this is as the first element, and which subattack this is as the second element)"
    tag = ItemTags.SPECIAL

    expose = ComponentType.Event
            
    def after_strike(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        event_prefab = DB.events.get_from_nid(self.value)
        mark_playbacks = [p for p in playback if p.nid in (
            'mark_hit', 'mark_crit')]

        if target and any(p.attacker == unit for p in mark_playbacks):
            if event_prefab:
                local_args = {'target_pos': target_pos, 'mode': mode, 'attack_info': attack_info, 'item': item}
                game.events.trigger_specific_event(event_prefab.nid, unit, target, unit.position, local_args)

class EventAfterGlancingHit(ItemComponent):
    nid = 'event_after_glancing_hit'
    desc = "The selected event plays after a hit, if the unit will hit with this item. The event is triggered with args (unit1=attacking unit, unit2=target, item=item, position=attacking unit's position, target_pos=position of target, mode='attack' or 'defense', attack_info=a tuple containing which attack this is as the first element, and which subattack this is as the second element)"
    tag = ItemTags.SPECIAL

    expose = ComponentType.Event
            
    def after_strike(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        event_prefab = DB.events.get_from_nid(self.value)
        mark_playbacks = [p for p in playback if p.nid in (
            'mark_glancing_hit')]

        if target and any(p.attacker == unit for p in mark_playbacks):
            if event_prefab:
                local_args = {'target_pos': target_pos, 'mode': mode, 'attack_info': attack_info, 'item': item}
                game.events.trigger_specific_event(event_prefab.nid, unit, target, unit.position, local_args)

class ShoveFlexibleStopsEvent(ItemComponent):
    nid = 'shove_flex_stops_event'
    desc = "Item shoves target on hit up to X spaces, can be shortened by obstacles. Trigger an event if stopped."
    tag = ItemTags.CUSTOM

    expose = (ComponentType.NewMultipleOptions)
    options = {
        "magnitude": ComponentType.Int,
        "impact_event": ComponentType.Event,
    }
    
    def __init__(self, value=None):
        self.value = {
            "magnitude": 0,
            "impact_event": '',
        }
        if value:
            self.value.update(value)

    def _check_shove(self, unit_to_move, anchor_pos, magnitude):
        curr_magnitude = 0
        ret_position = None
        while(abs(curr_magnitude) < abs(magnitude)):
            if magnitude < 0:
                curr_magnitude -= 1
            else:
                curr_magnitude += 1
            offset_x = utils.clamp(unit_to_move.position[0] - anchor_pos[0], -1, 1)
            offset_y = utils.clamp(unit_to_move.position[1] - anchor_pos[1], -1, 1)
            new_position = (unit_to_move.position[0] + offset_x * curr_magnitude,
                            unit_to_move.position[1] + offset_y * curr_magnitude)

            mcost = movement_funcs.get_mcost(unit_to_move, new_position)
            if game.board.check_bounds(new_position) and \
                    not game.board.get_unit(new_position) and \
                    mcost <= equations.parser.movement(unit_to_move):
                ret_position = new_position
            else:
                magnitude = 0
                if game.board.get_unit(new_position):
                    game.events.trigger_specific_event(self.value.get('impact_event'), unit_to_move, game.board.get_unit(new_position), unit_to_move.position)
                else:
                    game.events.trigger_specific_event(self.value.get('impact_event'), unit_to_move, None, unit_to_move.position)
        if not ret_position:
            return False
        return ret_position

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        if target and not skill_system.ignore_forced_movement(target):
            new_position = self._check_shove(target, unit.position, self.value["magnitude"])
            if new_position:
                actions.append(action.ForcedMovement(target, new_position))
                playback.append(pb.ShoveHit(unit, item, target))

    def ai_status_priority(unit, target, item, move, status_nid) -> float:
        if target and status_nid not in [skill.nid for skill in target.skills]:
            accuracy_term = utils.clamp(combat_calcs.compute_hit(unit, target, item, target.get_weapon(), "attack", (0, 0))/100., 0, 1)
            num_attacks = combat_calcs.outspeed(unit, target, item, target.get_weapon(), "attack", (0, 0))
            accuracy_term *= num_attacks
            # Tries to maximize distance from target
            distance_term = 0.01 * utils.calculate_distance(move, target.position)
            if skill_system.check_enemy(unit, target):
                return 0.5 * accuracy_term + distance_term
            else:
                return -0.5 * accuracy_term
        return 0

class EvalMinimumRange(ItemComponent):
    nid = 'eval_min_range'
    desc = "Set the minimum_range of the item solved using evaluate"
    tag = ItemTags.CUSTOM

    expose = ComponentType.String
    value = 0

    def minimum_range(self, unit, item) -> int:
        from app.engine import evaluate
        try:
            return int(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except Exception as e:
            logging.error("Couldn't evaluate %s conditional (%s)", self.value, e)
        return 0

class StackCostMulti(ItemComponent):
    nid = 'stack_cost_multi'
    desc = "Item requires and uses the given number of stacks of the specified skill. Stacks are lost at start of combat."
    tag = ItemTags.USES

    expose = ComponentType.NewMultipleOptions
    
    options = {
        'skill': ComponentType.Skill,
        'amount': ComponentType.Int
    }

    def __init__(self, value=None):
        self.value = {
            'skill': 'Canto',
            'amount': 1
        }
        if value:
            self.value.update(value)
    
    def available(self, unit, item) -> bool:
        return len([s.nid for s in unit.skills if s.nid == self.value.get('skill')]) >= self.value.get('amount')

    def start_combat(self, playback, unit, item, target, item2, mode):
        action.do(action.RemoveSkill(unit, self.value.get('skill'), self.value.get('amount')))
    
    def reverse_use(self, unit, item):
        for x in range(self.value.get('amount')):
            action.do(action.AddSkill(unit, self.value.get('skill'), unit))

class SolomonHeal(ItemComponent):
    nid = 'solomon_heal'
    desc = "Very bespoke component for use in Solomon's Prf staff. Do not use anywhere else."
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 10

    def _get_heal_amount(self, unit, target):
        empower_heal = skill_system.empower_heal(unit, target)
        empower_heal_received = skill_system.empower_heal_received(target, unit)
        return max(0, self.value + empower_heal + empower_heal_received + unit.get_stat('RES') - target.get_stat('RES'))

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        if not 'Monster' in target.tags:
            heal = -1 * self._get_heal_amount(unit, target)
            is_heal = False
            true_heal = heal
        else:
            heal = 8
            is_heal = True
            true_heal = min(heal, target.get_max_hp() - target.get_hp())
        actions.append(action.ChangeHP(target, heal))

        # For animation
        if is_heal and true_heal > 0:
            playback.append(pb.HealHit(unit, item, target, heal, true_heal))
            playback.append(pb.HitSound('MapHeal', map_only=True))
            if heal >= 30:
                name = 'MapBigHealTrans'
            elif heal >= 15:
                name = 'MapMediumHealTrans'
            else:
                name = 'MapSmallHealTrans'
            playback.append(pb.HitAnim(name, target))
        else:
            playback.append(pb.DamageHit(unit, item, target, abs(heal), abs(true_heal)))
            playback.append(pb.HitSound('MapHeal', map_only=True))

class StatusAfterCombatOnHitFoeOnly(ItemComponent):
    nid = 'status_after_combat_on_hit_foe_only'
    desc = "If the target is hit they gain the specified status at the end of combat. Prevents changes being applied mid-combat. Only affects targets that are not allied."
    tag = ItemTags.SPECIAL

    expose = ComponentType.Skill  # Nid

    _did_hit = set()

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        if skill_system.check_enemy(unit, target):
            self._did_hit.add(target)

    def end_combat(self, playback, unit, item, target, item2, mode):
        for target in self._did_hit:
            act = action.AddSkill(target, self.value, unit)
            action.do(act)
        self._did_hit.clear()

    def ai_priority(self, unit, item, target, move):
        # Do I add a new status to the target
        return ai_status_priority(unit, target, item, move, self.value)

class EvalHit(ItemComponent):
    nid = 'eval_hit'
    desc = "Item has a chance to hit, based on evaluate. If left off, item will always hit."
    tag = ItemTags.WEAPON

    expose = ComponentType.String
    value = 0

    def hit(self, unit, item):
        from app.engine import evaluate
        try:
            return int(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except Exception as e:
            logging.error("EVAL HIT: Couldn't evaluate %s conditional (%s)", self.value, e)
            return 80

class SelfShoveFlexibleStops(ItemComponent):
    nid = 'self_shove_flex_stops'
    desc = "Item shoves self on hit up to X spaces, can be shortened by obstacles. Magnitude determined by eval cuz it's just always better that way"
    tag = ItemTags.CUSTOM

    expose = ComponentType.String
    value = 0

    def _check_shove(self, unit_to_move, anchor_pos, magnitude):
        curr_magnitude = 0
        ret_position = None
        while(abs(curr_magnitude) < abs(magnitude)):
            if magnitude < 0:
                curr_magnitude -= 1
            else:
                curr_magnitude += 1
            offset_x = utils.clamp(anchor_pos[0] - unit_to_move.position[0], -1, 1)
            offset_y = utils.clamp(anchor_pos[1] - unit_to_move.position[1], -1, 1)
            new_position = (unit_to_move.position[0] + offset_x * curr_magnitude,
                            unit_to_move.position[1] + offset_y * curr_magnitude)

            mcost = movement_funcs.get_mcost(unit_to_move, new_position)
            if game.board.check_bounds(new_position) and \
                    not game.board.get_unit(new_position) and \
                    mcost <= equations.parser.movement(unit_to_move):
                ret_position = new_position
            else:
                magnitude = 0
        if not ret_position:
            return False
        return ret_position

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        if not skill_system.ignore_forced_movement(unit):
            from app.engine import evaluate
            try:
                push_power = int(evaluate.evaluate(self.value, unit, local_args = {'item': item, 'item2': item2, 'mode': mode, 'target': target, 'target_pos': target_pos}))
            except Exception as e:
                logging.error("SELF SHOVE FLEXIBLE STOPS: Couldn't evaluate %s conditional (%s)", self.value, e)
                push_power = 0
            new_position = self._check_shove(unit, target_pos, push_power)
            if new_position:
                actions.append(action.ForcedMovement(unit, new_position))
                playback.append(pb.ShoveHit(unit, item, target))

class EnemyBigCleaveAOE(ItemComponent):
    nid = 'enemy_big_cleave_aoe'
    desc = "All enemies within two tiles (or diagonal within two tiles from the user) are affected by this attack's AOE."
    tag = ItemTags.AOE

    def splash(self, unit, item, position) -> tuple:
        from app.engine import skill_system
        pos = unit.position
        all_positions = set()
        for x in range(-2, 3):
            for y in range(-2, 3):
                all_positions.add((pos[0] + x, pos[1] + y))

        all_positions = {pos for pos in all_positions if game.tilemap.check_bounds(pos)}
        all_positions.discard(position)
        splash = all_positions
        splash = [game.board.get_unit(pos) for pos in splash]
        splash = [s.position for s in splash if s and skill_system.check_enemy(unit, s)]
        main_target = position if game.board.get_unit(position) else None
        return main_target, splash

    def splash_positions(self, unit, item, position) -> set:
        from app.engine import skill_system
        pos = unit.position
        all_positions = set()
        for x in range(-2, 3):
            for y in range(-2, 3):
                all_positions.add((pos[0] + x, pos[1] + y))

        all_positions = {pos for pos in all_positions if game.tilemap.check_bounds(pos)}
        all_positions.discard(position)
        splash = all_positions
        # Doesn't highlight allies positions
        splash = {pos for pos in splash if not game.board.get_unit(pos) or skill_system.check_enemy(unit, game.board.get_unit(pos))}
        return splash

class EventForEachAfterCombatOnHit(ItemComponent):
    nid = 'event_for_each_after_combat_on_hit'
    desc = "If the target is hit, trigger an event for each unit struck. The targetted units are passed into local args as 'target_foe'."
    tag = ItemTags.CUSTOM

    expose = ComponentType.Event

    _did_hit = set()

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        self._did_hit.add(target)

    def end_combat(self, playback, unit, item, target, item2, mode):
        event_prefab = DB.events.get_from_nid(self.value)
        if event_prefab:
            for target_foe in self._did_hit:
                local_args = {'target_foe': target_foe, 'item': item, 'item2': item2, 'mode': mode}
                game.events.trigger_specific_event(event_prefab.nid, unit, target, unit.position, local_args)
        self._did_hit.clear()

class StacksOnHit(ItemComponent):
    nid = 'stacks_on_hit'
    desc = "Target gains specified status on hit, X times. Applies instantly, potentially causing values to change mid-combat."
    tag = ItemTags.SPECIAL

    expose = ComponentType.NewMultipleOptions
    
    options = {
        'skill': ComponentType.Skill,
        'amount': ComponentType.Int
    }

    def __init__(self, value=None):
        self.value = {
            'skill': 'Canto',
            'amount': 1
        }
        if value:
            self.value.update(value)

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        for x in range(self.value.get('amount')):
            act = action.AddSkill(target, self.value.get('skill'), unit)
            actions.append(act)
            playback.append(pb.StatusHit(unit, item, target, self.value.get('skill')))

    def ai_priority(self, unit, item, target, move):
        # Do I add a new status to the target
        return ai_status_priority(unit, target, item, move, self.value.get('skill'))

class SelfRemoveSkill(ItemComponent):
    nid = 'self_remove_skill'
    desc = "Removes all stacks of the specified skill from self after combat."
    tag = ItemTags.CUSTOM

    expose = ComponentType.Skill

    def end_combat(self, playback, unit, item, target, item2, mode):
        remove_amount = len([s for s in unit.skills if s.nid == self.value])
        action.do(action.RemoveSkill(unit, self.value, remove_amount))

class EvalAllyBlastAOE(ItemComponent):
    nid = 'eval_ally_blast_aoe'
    desc = "Grants EVAL Ally AoE range."
    tag = ItemTags.CUSTOM

    expose = ComponentType.String

    def _get_power(self, unit) -> int:
        from app.engine import evaluate
        try:
            base_power = int(evaluate.evaluate(self.value, unit))
        except Exception as e:
            logging.error("Couldn't evaluate %s conditional (%s)", self.value, e)
            base_power = 0
        empowered_splash = skill_system.empower_splash(unit)
        return base_power + 1 + empowered_splash

    def splash(self, unit, item, position) -> tuple:
        ranges = set(range(self._get_power(unit)))
        splash = game.target_system.find_manhattan_spheres(ranges, position[0], position[1])
        splash = {pos for pos in splash if game.board.check_bounds(pos)}
        splash = [game.board.get_unit(s) for s in splash]
        splash = [s.position for s in splash if s and skill_system.check_ally(unit, s)]
        return None, splash

    def splash_positions(self, unit, item, position) -> set:
        ranges = set(range(self._get_power(unit)))
        splash = game.target_system.find_manhattan_spheres(ranges, position[0], position[1])
        splash = {pos for pos in splash if game.tilemap.check_bounds(pos)}
        return splash

class RestoreNoTargetRestrict(ItemComponent):
    nid = 'restore_no_target_restrict'
    desc = "Item removes all negative statuses from target on hit. Does not require the target to have negative statuses."
    tag = ItemTags.UTILITY

    def _can_be_restored(self, status):
        return status.negative

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        for skill in target.all_skills[:]:
            if self._can_be_restored(skill):
                actions.append(action.RemoveSkill(target, skill))
                playback.append(pb.RestoreHit(unit, item, target))

class EvalStackCost(ItemComponent):
    nid = 'eval_stack_cost'
    desc = "Item requires and uses the evaluated number of stacks of the specified skill. Stacks are lost at start of combat."
    tag = ItemTags.USES

    expose = ComponentType.NewMultipleOptions
    
    options = {
        'skill': ComponentType.Skill,
        'amount': ComponentType.String
    }

    def __init__(self, value=None):
        self.value = {
            'skill': 'Canto',
            'amount': 0
        }
        if value:
            self.value.update(value)
    
    def available(self, unit, item) -> bool:
        try:
            return len([s for s in unit.skills if s.nid == self.value.get('skill')]) >= int(evaluate.evaluate(self.value.get('amount'), unit, local_args={'item': item}))
        except Exception as e:
            logging.error("EVAL STACK COST: Couldn't evaluate %s conditional (%s)", self.value.get('amount'), e)
            return False

    #Below two are assuming validity of the eval, since if not valid it would already have failed the availability check. Might not be turnwheel safe though.
    def start_combat(self, playback, unit, item, target, item2, mode):
        rem_amount = int(evaluate.evaluate(self.value.get('amount'), unit, local_args={'item': item}))
        action.do(action.RemoveSkill(unit, self.value.get('skill'), rem_amount))
    
    def reverse_use(self, unit, item):
        rem_amount = int(evaluate.evaluate(self.value.get('amount'), unit, local_args={'item': item}))
        for x in range(rem_amount):
            action.do(action.AddSkill(unit, self.value.get('skill'), unit))
     
class EventOnBreak(ItemComponent):
    nid = 'event_on_break'
    desc = "The selected event plays at the when an item breaks."
    tag = ItemTags.SPECIAL

    expose = ComponentType.Event

    def on_broken(self, unit, item):
        event_prefab = DB.events.get_from_nid(self.value)
        if event_prefab:
            local_args = {'item': item}
            game.events.trigger_specific_event(event_prefab.nid, unit, local_args=local_args)

class RefreshNoTargetRestrict(ItemComponent):
    nid = 'refresh_no_target_restrict'
    desc = "It's like refresh but the target does not need to have moved already, wow"
    tag = ItemTags.UTILITY

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        actions.append(action.Reset(target))
        playback.append(pb.RefreshHit(unit, item, target))

class HealNoTargetRestrict(ItemComponent):
    nid = 'heal_no_target_restrict'
    desc = "Item heals this amount on hit, target does not need to be injured"
    tag = ItemTags.UTILITY

    expose = ComponentType.Int
    value = 10

    def _get_heal_amount(self, unit, target):
        empower_heal = skill_system.empower_heal(unit, target)
        empower_heal_received = skill_system.empower_heal_received(target, unit)
        return self.value + empower_heal + empower_heal_received

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        heal = self._get_heal_amount(unit, target)
        true_heal = min(heal, target.get_max_hp() - target.get_hp())
        actions.append(action.ChangeHP(target, heal))

        # For animation
        if true_heal > 0:
            playback.append(pb.HealHit(unit, item, target, heal, true_heal))
            playback.append(pb.HitSound('MapHeal', map_only=True))
            if heal >= 30:
                name = 'MapBigHealTrans'
            elif heal >= 15:
                name = 'MapMediumHealTrans'
            else:
                name = 'MapSmallHealTrans'
            playback.append(pb.HitAnim(name, target))

    def ai_priority(self, unit, item, target, move):
        if target and skill_system.check_ally(unit, target):
            max_hp = target.get_max_hp()
            missing_health = max_hp - target.get_hp()
            help_term = utils.clamp(missing_health / float(max_hp), 0, 1)
            heal = self._get_heal_amount(unit, target)
            heal_term = utils.clamp(min(heal, missing_health) / float(max_hp), 0, 1)
            return help_term * heal_term
        return 0

class EvalDamageAny(ItemComponent):
    nid = 'eval_damage_any'
    desc = "Item does damage on hit based on Eval. Can target allies."
    tag = ItemTags.CUSTOM

    expose = ComponentType.String
    value = 0

    def damage(self, unit, item):
        from app.engine import evaluate
        try:
            return int(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except Exception as e:
            logging.error("EVAL DAMAGE ANY: Couldn't evaluate %s conditional (%s)", self.value, e)
            return 0

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        playback_nids = [brush.nid for brush in playback]
        if 'attacker_partner_phase' in playback_nids or 'defender_partner_phase' in playback_nids:
            damage = combat_calcs.compute_assist_damage(unit, target, item, target.get_weapon(), mode, attack_info)
        else:
            damage = combat_calcs.compute_damage(unit, target, item, target.get_weapon(), mode, attack_info)

        # Reduce damage if in Grandmaster Mode
        if game.rng_mode == RNGOption.GRANDMASTER:
            hit = utils.clamp(combat_calcs.compute_hit(unit, target, item, target.get_weapon(), mode, attack_info), 0, 100)
            damage = int(damage * float(hit) / 100)

        true_damage = min(damage, target.get_hp())
        actions.append(action.ChangeHP(target, -damage))

        # For animation
        playback.append(pb.DamageHit(unit, item, target, damage, true_damage))
        if damage == 0:
            playback.append(pb.HitSound('No Damage'))
            playback.append(pb.HitAnim('MapNoDamage', target))

    def on_glancing_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        playback_nids = [brush.nid for brush in playback]
        if 'attacker_partner_phase' in playback_nids or 'defender_partner_phase' in playback_nids:
            damage = combat_calcs.compute_assist_damage(unit, target, item, target.get_weapon(), mode, attack_info)
        else:
            damage = combat_calcs.compute_damage(unit, target, item, target.get_weapon(), mode, attack_info)

        # Reduce damage if in Grandmaster Mode
        if game.rng_mode == RNGOption.GRANDMASTER:
            hit = utils.clamp(combat_calcs.compute_hit(unit, target, item, target.get_weapon(), mode, attack_info), 0, 100)
            damage = int(damage * float(hit) / 100)

        damage //= 2  # Because glancing hit

        true_damage = min(damage, target.get_hp())
        actions.append(action.ChangeHP(target, -damage))

        # For animation
        playback.append(pb.DamageHit(unit, item, target, damage, true_damage))
        if damage == 0:
            playback.append(pb.HitAnim('MapNoDamage', target))
        else:
            playback.append(pb.HitAnim('MapGlancingHit', target))

    def on_crit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        playback_nids = [brush.nid for brush in playback]
        if 'attacker_partner_phase' in playback_nids or 'defender_partner_phase' in playback_nids:
            damage = combat_calcs.compute_assist_damage(unit, target, item, target.get_weapon(), mode, attack_info, crit=True)
        else:
            damage = combat_calcs.compute_damage(unit, target, item, target.get_weapon(), mode, attack_info, crit=True)
 
        # Reduce damage if in Grandmaster Mode (although crit doesn't make much sense with Grandmaster mode)
        if game.rng_mode == RNGOption.GRANDMASTER:
            hit = utils.clamp(combat_calcs.compute_hit(unit, target, item, target.get_weapon(), mode, attack_info), 0, 100)
            damage = int(damage * float(hit) / 100)

        true_damage = min(damage, target.get_hp())
        actions.append(action.ChangeHP(target, -damage))

        playback.append(pb.DamageCrit(unit, item, target, damage, true_damage))
        if damage == 0:
            playback.append(pb.HitSound('No Damage'))
            playback.append(pb.HitAnim('MapNoDamage', target))

class TargetsAnythingExceptAllies(ItemComponent):
    nid = 'target_tile_unless_ally'
    desc = "Item targets any tile, unless an ally is on the targeted tile"
    tag = ItemTags.TARGET

    def valid_targets(self, unit, item) -> set:
        all_pos = {(x, y) for x in range(game.tilemap.width) for y in range(game.tilemap.height)}
        all_pos = {z for z in all_pos if not (game.board.get_unit(z) and skill_system.check_ally(unit, game.board.get_unit(z)))}
        return all_pos

class EvalHeal(ItemComponent):
    nid = 'eval_heal'
    desc = "Item heals evaluated amount on hit. Has no in-built targeting restriction."
    tag = ItemTags.UTILITY

    expose = ComponentType.String

    def _get_heal_amount(self, unit, target):
        try:
            heal_value = int(evaluate.evaluate(self.value, unit, local_args={'target': target}))
        except:
            logging.error("EvalHeal: Couldn't evaluate %s conditional" % self.value)
            heal_value = 0
        empower_heal = skill_system.empower_heal(unit, target)
        empower_heal_received = skill_system.empower_heal_received(target, unit)
        empower_heal_multiplier = skill_system.empower_heal_multiplier(unit, target)
        empower_heal_received_multiplier = skill_system.empower_heal_received_multiplier(target, unit)
        return int(empower_heal_multiplier * empower_heal_received_multiplier * (heal_value + empower_heal + empower_heal_received))

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        heal = self._get_heal_amount(unit, target)
        true_heal = min(heal, target.get_max_hp() - target.get_hp())
        actions.append(action.ChangeHP(target, heal))

        # For animation
        if true_heal > 0:
            playback.append(pb.HealHit(unit, item, target, heal, true_heal))
            playback.append(pb.HitSound('MapHeal', map_only=True))
            if heal >= 30:
                name = 'MapBigHealTrans'
            elif heal >= 15:
                name = 'MapMediumHealTrans'
            else:
                name = 'MapSmallHealTrans'
            playback.append(pb.HitAnim(name, target))

    def ai_priority(self, unit, item, target, move):
        if target and skill_system.check_ally(unit, target):
            max_hp = target.get_max_hp()
            missing_health = max_hp - target.get_hp()
            help_term = utils.clamp(missing_health / float(max_hp), 0, 1)
            heal = self._get_heal_amount(unit, target)
            heal_term = utils.clamp(min(heal, missing_health) / float(max_hp), 0, 1)
            return help_term * heal_term
        return 0

class GimmeThat(StealCon):
    nid = 'gimme_that'
    desc = "Boss's bespoke steal component. SPD must exceed foe, STR must be 5 higher, and CON check against item weight. Can steal equipped items."
    tag = ItemTags.CUSTOM

    def target_restrict(self, unit, item, def_pos, splash) -> bool:
        # Unit has item that can be stolen
        attack = equations.parser.steal_atk(unit)
        defender = game.board.get_unit(def_pos)
        defense = equations.parser.steal_def(defender)
        if attack >= defense and (unit.get_stat('STR') - 5) >= defender.get_stat('STR'):
            for def_item in defender.items:
                if self.item_restrict(unit, item, defender, def_item):
                    return True
        return False

    def item_restrict(self, unit, item, defender, def_item) -> bool:
        if item_system.unstealable(defender, def_item):
            return False
        if def_item.components.get('weight') and unit.get_stat('CON') < def_item.components.get('weight').value:
            return False
        if item_funcs.inventory_full(unit, def_item):
            return True if unit.team == 'player' else False
        return True

class AllUnitsAOE(ItemComponent):
    nid = 'all_units_aoe'
    desc = "Item affects all units on the map including user"
    tag = ItemTags.AOE

    def splash(self, unit, item, position) -> tuple:
        from app.engine import skill_system
        splash = [u.position for u in game.units if u.position]
        return None, splash

    def splash_positions(self, unit, item, position) -> set:
        # All positions
        splash = {(x, y) for x in range(game.tilemap.width) for y in range(game.tilemap.height)}
        return splash

class CopysafeStatusOnHit(ItemComponent):
    nid = 'copysafe_status_on_hit'
    desc = "Target gains the specified status on hit. Mainly used for learning a copysafe skill and its child skills. Do not use for non-copysafe skills."
    tag = ItemTags.SPECIAL

    expose = ComponentType.Skill  # Nid

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        act = action.AddSkill(target, self.value, unit)
        actions.append(act)
        playback.append(pb.StatusHit(unit, item, target, self.value))
        child_skills = [s for s in DB.skills.get(self.value).components.get('copysafe').value]
        for child_skill in child_skills:
            act = action.AddSkill(target, child_skill, unit)
            actions.append(act)
            playback.append(pb.StatusHit(unit, item, target, child_skill))

class ItemNameColor(ItemComponent):
    nid = 'item_name_color'
    desc = 'Special color for item name.'
    tag = ItemTags.AESTHETIC

    expose = (ComponentType.MultipleChoice, ['white','green','yellow'])
    value = 'white'

    def text_color(self, unit, item):
        if self.value not in ['white','green','yellow']:
            return 'white'
        return self.value

class UserLevelExp(ItemComponent):
    nid = 'user_level_exp'
    desc = "Item gives exp to user that declines with user's level"
    tag = ItemTags.EXP

    author = 'Beccarte'

    expose = ComponentType.Int
    value = 30

    def exp(self, playback, unit, item) -> int:
        level = unit.get_internal_level()
        exp_gain = max(5,(self.value-level))
        mult = skill_system.exp_multiplier(unit, unit)
        exp_gain *= mult
        exp_gain = utils.clamp(int(exp_gain), DB.constants.value('min_exp'), 100)
        return exp_gain

class UtilityExp(ItemComponent):
    nid = 'utility_exp'
    desc = "Item gives exp to user that declines with user's level and number of uses this chapter"
    tag = ItemTags.EXP

    author = 'Beccarte'

    expose = ComponentType.Int
    value = 30

    def exp(self, playback, unit, item) -> int:
        level = unit.get_internal_level()
        #Correct for unit's level
        exp_gain = max(5,(self.value-level))
        #Correct for previous uses
        varname = 'uexp_' + unit.nid + item.nid
        var = game.level_vars.get(varname)
        if var:
            exp_gain = max(0,(exp_gain - 5*var))
            action.do(action.SetLevelVar(varname, var + 1))
        else:
            action.do(action.SetLevelVar(varname, 1))
        mult = skill_system.exp_multiplier(unit, unit)
        exp_gain *= mult
        exp_gain = utils.clamp(int(exp_gain), DB.constants.value('min_exp'), 100)
        return exp_gain

class DanceExp(ItemComponent):
    nid = 'dance_exp'
    desc = "Item gives exp to user that declines only with number of uses this chapter"
    tag = ItemTags.EXP

    author = 'Beccarte'

    expose = ComponentType.Int
    value = 30

    def exp(self, playback, unit, item) -> int:
        exp_gain = self.value
        varname = 'uexp_' + unit.nid + item.nid
        var = game.level_vars.get(varname)
        if var:
            exp_gain = max(0,(exp_gain - 2*var))
            action.do(action.SetLevelVar(varname, var + 1))
        else:
            action.do(action.SetLevelVar(varname, 1))
        mult = skill_system.exp_multiplier(unit, unit)
        exp_gain *= mult
        exp_gain = utils.clamp(int(exp_gain), DB.constants.value('min_exp'), 100)
        return exp_gain

class HealOnGet(ItemComponent):
    nid = 'heal_on_get'
    desc = "If the base or prep menu, item will restore HP to full on acquire. Used for items that change max HP."
    tag = ItemTags.UTILITY

    author = 'Beccarte'

    def on_add_item(self, unit, item):
        if game.game_vars.get('InBase') or game.game_vars.get('InPrep'):
            unit.current_hp = unit.get_max_hp()

class PhantomUses(ItemComponent):
    nid = 'phantom_uses'
    desc = "No effect. Used to display a use in info menu for promotion items, etc."
    tag = ItemTags.USES

    author = 'Beccarte'

    expose = ComponentType.Int
    value = 1

    def init(self, item):
        item.data['phantom_uses'] = self.value

    def special_sort(self, unit, item):
        return item.data['phantom_uses']

class ChapterUsesRecalc(ItemComponent):
    nid = 'c_uses_recalc'
    desc = "As chapter uses, but forces a game boundary recalc on the unit when out of charges. Used with weapon abilities so range display updates."
    paired_with = ('uses_options',)
    tag = ItemTags.USES

    author = 'Beccarte'

    expose = ComponentType.Int
    value = 1

    _did_something = False

    def init(self, item):
        item.data['c_uses'] = self.value
        item.data['starting_c_uses'] = self.value

    def available(self, unit, item) -> bool:
        return item.data['c_uses'] > 0

    def is_unusable(self, unit, item) -> bool:
        return item.data['c_uses'] <= 0

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        if item.uses_options.one_loss_per_combat():
            self._did_something = True
        else:
            actions.append(action.SetObjData(item, 'c_uses', item.data['c_uses'] - 1))
            actions.append(action.UpdateRecords('item_use', (unit.nid, item.nid)))

    def on_miss(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        if item.uses_options.lose_uses_on_miss():
            if item.uses_options.one_loss_per_combat():
                self._did_something = True
            else:
                actions.append(action.SetObjData(item, 'c_uses', item.data['c_uses'] - 1))
                actions.append(action.UpdateRecords('item_use', (unit.nid, item.nid)))

    def on_unusable(self, unit, item):
        if unit.equipped_weapon is item:
            action.do(action.UnequipItem(unit, item))
        elif unit.equipped_accessory is item:
            action.do(action.UnequipItem(unit, item))
        # This is what's added vs. the standard c_uses component
        if unit.position and game.tilemap and game.boundary:
            game.boundary.recalculate_unit(unit)

    def end_combat(self, playback, unit, item, target, item2, mode):
        if self._did_something and 'c_uses' in item.data:
            action.do(action.SetObjData(item, 'c_uses', item.data['c_uses'] - 1))
            action.do(action.UpdateRecords('item_use', (unit.nid, item.nid)))
        self._did_something = False

    def on_end_chapter(self, unit, item):
        # Don't need to use action here because it will be end of chapter
        item.data['c_uses'] = item.data['starting_c_uses']

    def reverse_use(self, unit, item):
        action.do(action.SetObjData(item, 'c_uses', item.data['c_uses'] + 1))
        action.do(action.ReverseRecords('item_use', (unit.nid, item.nid)))

    def special_sort(self, unit, item):
        return item.data['c_uses']

class BreakSilently(ItemComponent):
    nid = 'break_silently'
    desc = "No banner is shown when item breaks."
    tag = ItemTags.AESTHETIC

    author = 'Beccarte'

    def alerts_when_broken(self, unit, item):
        return False

class MapSelfCastSFX(ItemComponent):
    nid = 'map_self_cast_sfx'
    desc = "When item is used the selected sound is played once on the user."
    tag = ItemTags.AESTHETIC

    author = 'Beccarte'

    expose = ComponentType.Sound
    value = 'Attack Hit 1'

    _cast_counter = 0

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        if self._cast_counter == 0:
            playback.append(pb.CastSound(self.value))
            self._cast_counter = 1
            
    def end_combat(self, playback, unit, item, target, item2, mode):
        self._cast_counter = 0
        
class MapSelfCastAnim(ItemComponent):
    nid = 'map_self_cast_anim'
    desc = "Adds a specific animation effect on the users's tile when the item is used. Relevant in map combat situations."
    tag = ItemTags.AESTHETIC

    author = 'Beccarte'

    expose = ComponentType.MapAnimation
    
    _cast_counter = 0

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        if self._cast_counter == 0:
            playback.append(pb.TargetCastAnim(self.value, unit.position))
            self._cast_counter = 1

    def end_combat(self, playback, unit, item, target, item2, mode):
        self._cast_counter = 0

class MagicNoCastAnim(ItemComponent):
    nid = 'magic_no_cast_anim'
    desc = 'Makes Item use magic damage formula. Uses the non-magic combat animation.'
    tag = ItemTags.WEAPON

    def damage_formula(self, unit, item):
        return 'MAGIC_DAMAGE'

    def resist_formula(self, unit, item):
        return 'MAGIC_DEFENSE'

class ChangeAnimation(ItemComponent):
    nid = 'change_animation'
    desc = "Change the unit's animation"
    tag = ItemTags.AESTHETIC

    author = 'Beccarte'

    expose = ComponentType.String
    value = ''

    def change_animation(self, unit, item):
        return self.value

class RefreshLite(ItemComponent):
    nid = 'refresh_lite'
    desc = "Use won't take up an action but won't restore movement. Use for free-use items or skills."
    tag = ItemTags.UTILITY

    author = 'Beccarte'

    def end_combat(self, playback, unit, item, target, item2, mode):
        action.do(action.ResetLite(unit))

class RestoreNoRestriction(ItemComponent):
    nid = 'restore_no_restriction'
    desc = "Item removes all negative statuses from target on hit. Can be used on targets with no status."
    tag = ItemTags.UTILITY

    def _can_be_restored(self, status):
        return status.negative

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        for skill in target.all_skills[:]:
            if self._can_be_restored(skill):
                actions.append(action.RemoveSkill(target, skill))
                playback.append(pb.RestoreHit(unit, item, target))

class BraveOnDefense(ItemComponent):
    nid = 'brave_on_defense'
    desc = "The weapon is only brave when the foe initiates combat, and acts as a normal weapon when attacking."
    tag = ItemTags.EXTRA

    author = 'Beccarte'

    def dynamic_multiattacks(self, unit, item, target, item2, mode, attack_info, base_value):
        return 1 if mode == 'defense' else 0

class OnlyOnAttackBattleAnimationMusic(ItemComponent):
    nid = 'only_on_attack_battle_anim_music'
    desc = "Uses custom battle music if user initiates combat"
    tag = ItemTags.AESTHETIC

    author = 'BBHood217'

    expose = ComponentType.Music
    value = None

    def battle_music(self, unit, item, target, item2, mode):
        if mode == 'attack':
            return self.value
        
class ModifyAIPriority(ItemComponent):
    nid = 'modify_ai_priority'
    desc = "Changes the chance that the AI will use this item."
    tag = ItemTags.BASE

    author = 'Beccarte'

    expose = ComponentType.Int
    value = 100

    def ai_priority(self, unit, item, target, move):
        return self.value

class EvalPermanentStatChange(ItemComponent):
    nid = 'eval_permanent_stat_change'
    desc = "As permanent_stat_change, but allows evals."
    tag = ItemTags.SPECIAL

    author = 'Beccarte'

    expose = (ComponentType.StringDict, ComponentType.Stat)
    value = []
    
    _hit_count = 0

    def _target_restrict(self, defender):
        klass = DB.classes.get(defender.klass)
        from app.engine import evaluate
        for stat, inc in self.value:
            try:
                eval_inc = int(evaluate.evaluate(inc, defender))
            except Exception as e:
                logging.error("Couldn't evaluate conditional %s", e)
            if eval_inc <= 0 or defender.stats[stat] < klass.max_stats.get(stat, 30):
                return True
        return False

    def target_restrict(self, unit, item, def_pos, splash) -> bool:
        # Ignore's splash
        defender = game.board.get_unit(def_pos)
        if not defender:
            return True
        return self._target_restrict(defender)

    def simple_target_restrict(self, unit, item):
        return self._target_restrict(unit)

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        self._hit_count += 1
        playback.append(pb.StatHit(unit, item, target))

    def end_combat(self, playback, unit, item, target, item2, mode):
        if self._hit_count > 0:
            from app.engine import evaluate
            try:
                stat_changes = {k: int(evaluate.evaluate(v, unit))*self._hit_count for (k, v) in self.value}
            except Exception as e:
                logging.error("Couldn't evaluate conditional %s", e)
            klass = DB.classes.get(target.klass)
            # clamp stat changes
            stat_changes = {k: utils.clamp(v, -target.stats[k], klass.max_stats.get(k, 30) - target.stats[k]) for k, v in stat_changes.items()}
            action.do(action.ApplyStatChanges(target, stat_changes))
            if any(v != 0 for v in stat_changes.values()):
                game.memory['stat_changes'] = stat_changes
                game.exp_instance.append((target, 0, None, 'stat_booster'))
                game.state.change('exp')
        self._hit_count = 0

class MapAttackVoice(ItemComponent):
    nid = 'map_attack_voice'
    desc = "When item is used the character plays a random attack voice clip."
    tag = ItemTags.AESTHETIC

    author = 'Beccarte'

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        #Determine whether to play a voice clip depending on game options.
        if unit and cf.SETTINGS['combat_voices']:
            #Get the unit's list of attack voice clips.
            sound_list = RESOURCES.sfx.keys()
            sound_name = unit.nid + 'Attack'
            unit_sounds = [i for i in sound_list if sound_name in i]
            #Randomly determine which voice clip to play.
            if len(unit_sounds) > 0:
                sound = sound_name + str(random.randint(1, len(unit_sounds)))
                playback.append(pb.AttackVoice(sound))

    def on_miss(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        #Determine whether to play a voice clip depending on game options.
        if unit and cf.SETTINGS['combat_voices']:
            #Get the unit's list of attack voice clips.
            sound_list = RESOURCES.sfx.keys()
            sound_name = unit.nid + 'Attack'
            unit_sounds = [i for i in sound_list if sound_name in i]
            #Randomly determine which voice clip to play.
            if len(unit_sounds) > 0:
                sound = sound_name + str(random.randint(1, len(unit_sounds)))
                playback.append(pb.AttackVoice(sound))

class EvalMaxRange(ItemComponent):
    nid = 'eval_max_range'
    desc = "Modifies the maximum_range of the item by a given equation"
    tag = ItemTags.TARGET

    expose = ComponentType.String
    author = 'Beccarte'
    
    def modify_maximum_range(self, unit, item) -> int:
        from app.engine import evaluate
        try:
            return int(evaluate.evaluate(self.value, unit, local_args={'item': item}))
        except Exception as e:
            logging.error("Couldn't evaluate %s conditional (%s)", self.value, e)
        return 1








class MapAttackVoice(ItemComponent):
    nid = 'map_attack_voice'
    desc = "When item is used the character plays a random attack voice clip."
    tag = ItemTags.AESTHETIC

    author = 'Beccarte'

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        #Determine whether to play a voice clip depending on game options.
        if unit and cf.SETTINGS['combat_voices']:
            #Get the unit's list of attack voice clips.
            sound_list = RESOURCES.sfx.keys()
            sound_name = unit.nid + 'Attack'
            unit_sounds = [i for i in sound_list if sound_name in i]
            #Randomly determine which voice clip to play.
            if len(unit_sounds) > 0:
                sound = sound_name + str(random.randint(1, len(unit_sounds)))
                get_sound_thread().play_sfx(sound)

    def on_miss(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        #Determine whether to play a voice clip depending on game options.
        if unit and cf.SETTINGS['combat_voices']:
            #Get the unit's list of attack voice clips.
            sound_list = RESOURCES.sfx.keys()
            sound_name = unit.nid + 'Attack'
            unit_sounds = [i for i in sound_list if sound_name in i]
            #Randomly determine which voice clip to play.
            if len(unit_sounds) > 0:
                sound = sound_name + str(random.randint(1, len(unit_sounds)))
                get_sound_thread().play_sfx(sound)

class RestoreNoRestriction(ItemComponent):
    nid = 'restore_no_restriction'
    desc = "Item removes all negative statuses from target on hit. Can be used on targets with no status."
    tag = ItemTags.UTILITY

    def _can_be_restored(self, status):
        return status.negative

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        for skill in target.all_skills[:]:
            if self._can_be_restored(skill):
                actions.append(action.RemoveSkill(target, skill))
                playback.append(pb.RestoreHit(unit, item, target))

class MultiDescSkill(ItemComponent):
    nid = 'multi_desc_skill'
    desc = "Define a list of Skill NIDs whose info boxes should be attached to this skill's multi desc info box."
    tag = ItemTags.UTILITY
    author = 'Eretein'
    
    expose = (ComponentType.List, ComponentType.Skill)
    
    def multi_desc(self, unit, skill) ->  tuple[list[str], ComponentType]:
        return self.value, self.expose[1]

class MultiDescItem(ItemComponent):
    nid = 'multi_desc_item'
    desc = "Define a list of Item NIDs whose info boxes should be attached to this skill's multi desc info box."
    tag = ItemTags.UTILITY
    
    author = "Eretein"
    
    expose = (ComponentType.List, ComponentType.Item)
    
    def multi_desc(self, unit, skill) ->  tuple[list[str], ComponentType]:
        return self.value, self.expose[1]
           
class StealPlus(Steal):
    nid = 'steal_plus'
    desc = "Steal items, weapons, staves if Con > Wt"
    tag = ItemTags.SPECIAL

    def item_restrict(self, unit, item, defender, def_item) -> bool:
        if unit.get_stat('SPD') <= defender.get_stat('SPD'):
            return False
        if item_system.unstealable(defender, def_item):
            return False
        if item_funcs.inventory_full(unit, def_item):
            return False
        if defender and defender.get_weapon() and def_item.uid == defender.get_weapon().uid:
            return False
        if item_system.is_weapon(defender, def_item) or item_system.is_spell(defender, def_item):
            return not def_item.weight or unit.get_stat('CON') >= def_item.weight.value
        return True
       
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
           
class StealImpossible(Steal):
    nid = 'steal_impossible'
    desc = "Steal equipped items if Con > Wt"
    tag = ItemTags.SPECIAL

    def item_restrict(self, unit, item, defender, def_item) -> bool:
        if unit.get_stat('SPD') <= defender.get_stat('SPD'):
            return False
        if item_system.unstealable(defender, def_item):
            return False
        if item_funcs.inventory_full(unit, def_item):
            return False
        if not defender or not defender.get_weapon() or def_item.uid != defender.get_weapon().uid:
            return False
        if item_system.is_weapon(defender, def_item) or item_system.is_spell(defender, def_item):
            return not def_item.weight or unit.get_stat('CON') >= def_item.weight.value
        return True
        
class EvalTargetRestrictOverride(ItemComponent):
    nid = 'eval_target_restrict_override'
    desc = \
            """
            Restricts which units or spaces can be targeted. These properties are accessible in the eval body:

            - `unit`: the unit using the item
            - `target`: the target of the item
            - `item`: the item itself
            - `position`: the position of the unit
            - `target_pos`: the position of the target
            """
    tag = ItemTags.TARGET

    expose = ComponentType.String
    value = 'True'

    def target_restrict(self, unit, item, def_pos, splash) -> bool:
        from app.engine import evaluate
        try:
            target = game.board.get_unit(def_pos)
            unit_pos = unit.position
            target_pos = def_pos
            if evaluate.evaluate(self.value, unit, target, unit_pos, local_args={'target_pos': target_pos, 'item': item}):
                return True
            for s_pos in splash:
                target = game.board.get_unit(s_pos)
                if evaluate.evaluate(self.value, unit, target, unit_pos, local_args={'target_pos': s_pos, 'item': item}):
                    return True
        except Exception as e:
            print("Could not evaluate %s (%s)" % (self.value, e))
            return True
        return False

    def simple_target_restrict(self, unit, item):
        from app.engine import evaluate
        try:
            if evaluate.evaluate(self.value, unit, local_args={'item': item}):
                return True
        except Exception as e:
            print("Could not evaluate %s (%s)" % (self.value, e))
            return True
        return False
                 
class EventOnHit(ItemComponent):
    nid = 'event_on_hit'
    desc = 'Calls event on a hit'
    tag = ItemTags.SPECIAL

    expose = ComponentType.Event
    value = ''
    
    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        game.events.trigger_specific_event(self.value, unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode, 'target_pos': target_pos})
        
class SuperEclipse(ItemComponent):
    nid = 'super_eclipse'
    desc = "Target loses all but 1 HP on hit"
    tag = ItemTags.EXTRA

    def on_hit(self, actions, playback, unit, item, target, item2, target_pos, mode, attack_info):
        true_damage = damage = target.get_hp() - 1
        actions.append(action.ChangeHP(target, -damage))

        # For animation
        playback.append(pb.DamageHit(unit, item, target, damage, true_damage))
        if true_damage == 0:
            playback.append(pb.HitSound('No Damage'))
            playback.append(pb.HitAnim('MapNoDamage', target))

       
class StealValuable(Steal):
    nid = 'steal_valuable'
    desc = "Steal unequipped items if Con > Wt and value >= 3000"
    tag = ItemTags.SPECIAL

    def item_restrict(self, unit, item, defender, def_item) -> bool:
        if unit.get_stat('SPD') <= defender.get_stat('SPD'):
            return False
        if item_system.unstealable(defender, def_item):
            return False
        if item_funcs.inventory_full(unit, def_item):
            return False
        if defender and defender.get_weapon() and def_item.uid == defender.get_weapon().uid:
            return False
        if item_system.is_weapon(defender, def_item) or item_system.is_spell(defender, def_item):
            return not def_item.weight or unit.get_stat('CON') >= def_item.weight.value
        return item_system.full_price(defender, def_item) >= 3000
    






# this component should define a list of weapon types where each is checked via the available hook, if a unit can use it
# should return whatever true weapon type you want for the weapon_type hook
# probably doesn't matter cause you'll override it anyway - but matters for convoy/storage


class WeaponTypes(ItemComponent):
    nid = 'weapon_types'
    desc = "Defines a list of weapon types, item is usable if the unit can use at least one of them."
    tag = ItemTags.WEAPON
    author = "zeonBPM"
    
    expose = (ComponentType.List, ComponentType.WeaponType)

    def weapon_type(self, unit, item) -> Optional[str]:
        klass = DB.classes.get(unit.klass)
        if not klass:
            return self.value[0]

        usable_types = unit_funcs.usable_wtypes(unit)
        for wtype in self.value:
            if wtype in usable_types:
                wexp_gain = klass.wexp_gain.get(wtype)
                unit_wexp = unit.wexp.get(wtype, 0)
                if wexp_gain and unit_wexp > 0:
                    return wtype

        return self.value[0]
        if not self.value:
            return 'Default'

    def available(self, unit, item) -> bool:
        if not self.value or not unit:
            return False

        klass = DB.classes.get(unit.klass)
        if not klass:
            return False

        usable_types = unit_funcs.usable_wtypes(unit)
        for wtype in self.value:
            if wtype in usable_types:
                wexp_gain = klass.wexp_gain.get(wtype)
                unit_wexp = unit.wexp.get(wtype, 0)
                if wexp_gain and unit_wexp > 0:
                    return True

        return False


#class EvalWeaponTriangleOverride:
# should check what eligible weapon type the unit is using to access the spell and return that type through the weapon_triangle_override hook
# complicated - because what if unit has access to all eligible weapon types?
# how to resolve?














