from __future__ import annotations

from app.data.database.components import ComponentType
from app.data.database.database import DB
from app.data.database.item_components import ItemComponent, ItemTags
from app.engine import (action, banner, combat_calcs, engine, equations,
                        image_mods, item_funcs, item_system, skill_system)
from app.engine.game_state import game
from app.engine.objects.unit import UnitObject
from app.utilities import utils, static_random

from app.engine.item_components.hit_components import Steal
from app.engine.combat import playback as pb
from app.utilities import utils


class DoNothing(ItemComponent):
    nid = 'do_nothing'
    desc = 'does nothing'
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 1
    
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