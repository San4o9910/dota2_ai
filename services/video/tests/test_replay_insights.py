"""Analytics regressions for double counting, source isolation and item claims."""
import unittest

from narma_video.replay_insights import gold_facts, item_facts, pace_facts
import test_replay_report as report_fixture


class VisualFactTests(unittest.TestCase):
    def test_earned_gold_excludes_sales_losses_and_starting_gold(self):
        events = [dict(time=-10, gold=600, reason=0), dict(time=10, gold=100, reason=12),
                  dict(time=20, gold=70, reason=6), dict(time=30, gold=-20, reason=1),
                  dict(time=40, gold=15, reason=999)]
        samples = [dict(time=-1, gold=0), dict(time=15, gold=25), dict(time=65, gold=100)]
        gold, ledger = gold_facts(events, samples, 60, 215)
        self.assertEqual(gold['recorded_income'], 215)
        self.assertEqual(gold['recorded_loss'], 20)
        self.assertEqual(gold['reconciliation_difference'], 0)
        self.assertTrue(gold['reconciled'])
        self.assertEqual({r['key']: r['gold'] for r in gold['other_flows']}, {'pregame': 600, 'sale': 70})
        self.assertEqual(next(r['gold'] for r in gold['sources'] if r['key'] == 'unclassified_999'), 15)
        self.assertEqual(sum(row['income'] for row in gold['bins']), 215)
        self.assertEqual(sum(row['gold'] for row in ledger), 215)

    def test_passive_tick_events_are_not_added_again_as_counter_deltas(self):
        gold, _ = gold_facts([dict(time=12, gold=100, reason=10)],
                            [dict(time=-1, gold=0), dict(time=30, gold=100)], 60, 100)
        self.assertEqual(gold['recorded_income'], 100)
        self.assertTrue(gold['reconciled'])

    def test_missing_counter_baseline_and_unknown_difference_stay_visible(self):
        gold, _ = gold_facts([dict(time=12, gold=50, reason=13)],
                            [dict(time=30, gold=100), dict(time=50, gold=130)], 60, 300)
        self.assertEqual(gold['recorded_income'], 80)
        self.assertEqual(gold['reconciliation_difference'], 220)
        self.assertFalse(gold['reconciled'])
        self.assertIn('не установлен', gold['coverage_note'])

    def test_minute_pace_never_treats_missing_observation_as_zero_farm(self):
        economy = [dict(time=55, last_hits=10, earned_gold=200, xp=250),
                   dict(time=115, last_hits=18, earned_gold=400, xp=600)]
        rows = pace_facts(economy, [dict(time=60, type='kill')], 120)
        self.assertIsNone(rows[0]['last_hits'])
        self.assertEqual(rows[1]['last_hits'], 8)
        self.assertEqual(rows[0]['kills'], 0)
        self.assertEqual(rows[1]['kills'], 1)
        self.assertEqual((rows[1]['sample_start'], rows[1]['sample_end']), (55, 115))

    def test_delivered_later_and_used_later_is_not_claimed_immediate_or_failed(self):
        items = item_facts([dict(time=100, item='item_cyclone', event_id='event-1')],
            [dict(time=101, event_id='event-2', items=[dict(slot=9, itemName='item_cyclone')]),
             dict(time=160, event_id='event-3', items=[dict(slot=6, itemName='item_cyclone')]),
             dict(time=280, event_id='event-4', items=[dict(slot=3, itemName='item_cyclone')])],
            [dict(time=310, item='item_cyclone', event_id='event-5')],
            [dict(time=150, type='kill', id='event-6'), dict(time=330, type='death', id='event-7')], [], 400)
        item = items[0]
        self.assertEqual(item['first_hero_inventory_time'], 160)
        self.assertEqual(item['first_active_inventory_time'], 280)
        self.assertEqual(item['realization']['first_use_time'], 310)
        self.assertEqual(item['realization']['delay_seconds'], 210)
        self.assertEqual(item['realization']['delay_from_active_seconds'], 30)
        self.assertEqual(item['realization']['status'], 'used_later')
        self.assertEqual(item['realization']['casts'], 0)
        self.assertEqual(item['realization']['kills'], 1)
        self.assertEqual(item['realization']['deaths'], 0)
        self.assertIn('не доказанный', item['realization']['note'])
        self.assertEqual(item['timing']['status'], 'no_reference')

    def test_passive_item_and_truncated_window_are_not_marked_as_misplays(self):
        items = item_facts([dict(time=590, item='item_radiance', event_id='event-1')], [], [], [], [], 600)
        self.assertEqual(items[0]['realization']['status'], 'passive_item')
        self.assertEqual(items[0]['realization']['observed_seconds'], 10)
        self.assertEqual(items[0]['realization']['window_seconds'], 120)
        self.assertIn('нельзя оценить', items[0]['realization']['note'])

    def test_funding_boundary_award_counted_once_and_components_collapsed(self):
        inventory = [dict(time=100, item='item_black_king_bar', event_id='event-1'),
            dict(time=200, item='item_shivas_guard', event_id='event-2'),
            dict(time=300, item='item_kaya', event_id='event-3'),
            dict(time=305, item='item_sange', event_id='event-4'),
            dict(time=305, item='item_kaya_and_sange', event_id='event-5')]
        ledger = [dict(time=0, gold=20, key='passive'), dict(time=100, gold=100, key='heroes'),
                  dict(time=200, gold=80, key='lane_creeps')]
        items = item_facts(inventory, [], [], [], ledger, 600)
        self.assertEqual([r['item'] for r in items], ['item_black_king_bar', 'item_shivas_guard', 'item_kaya_and_sange'])
        self.assertEqual([r['funding']['income'] for r in items], [120, 80, 0])
        self.assertEqual(sum(r['funding']['income'] for r in items), 200)


class ReportVisualIntegrationTests(unittest.TestCase):
    def with_events(self, additions):
        fixture = report_fixture.ReplayReportTests()
        events, summary, job = fixture.fixture()
        events[-1:-1] = additions
        for index, event in enumerate(events, 1):
            event['eventId'] = index
        return fixture.run_report(events, summary, job)

    def test_selected_handle_and_resource_index_guard_inventory_and_gold(self):
        base = dict(type='hero_inventory', gameTimeDerivedFromServerTicks=150, heroHandle=900,
                    selectedPlayerIndex=7, playerId=14, team=2, items=[dict(slot=3, itemName='item_blink')])
        wrong_handle = dict(base, heroHandle=901, items=[dict(slot=2, itemName='item_rapier')])
        wrong_index = dict(base, selectedPlayerIndex=0, items=[dict(slot=2, itemName='item_heart')])
        gold = dict(type='combat', combatType='DOTA_COMBATLOG_GOLD', target='npc_dota_hero_necrolyte',
                    combatTimestamp=130, value=2**32 - 20, goldReason=1)
        enemy_gold = dict(gold, target='npc_dota_hero_lina', value=999)
        report = self.with_events([base, wrong_handle, wrong_index, gold, enemy_gold])
        self.assertEqual(report['insights']['gold']['recorded_loss'], 20)
        self.assertEqual(report['insights']['gold']['recorded_income'], 0)
        self.assertIn('item_blink', [r['item'] for r in report['insights']['items']])
        self.assertNotIn('item_rapier', [r['item'] for r in report['insights']['items']])
        self.assertNotIn('item_heart', [r['item'] for r in report['insights']['items']])

    def test_multiple_first_inventory_items_share_one_evidence_but_unique_cards(self):
        report = self.with_events([dict(type='hero_inventory', gameTimeDerivedFromServerTicks=150,
            heroHandle=900, selectedPlayerIndex=7, team=2,
            items=[dict(slot=3, itemName='item_blink'), dict(slot=2, itemName='item_heart')])])
        evidence = report['evidence']
        self.assertEqual(len({r['id'] for r in evidence}), len(evidence))
        observations = [r for r in evidence if r['type'] == 'item_observed']
        self.assertEqual(len(observations), 1)
        self.assertEqual(len(observations[0]['data']['items']), 2)
        cards = report['insights']['items']
        self.assertEqual(len({r['id'] for r in cards}), len(cards))
        for item in cards:
            self.assertIn(item['event_id'], {r['id'] for r in evidence})

    def test_first_cast_for_each_repurchase_has_evidence(self):
        def purchase(time):
            return dict(type='combat', combatType='DOTA_COMBATLOG_PURCHASE', target='npc_dota_hero_necrolyte',
                        combatTimestamp=time, valueName='item_black_king_bar')
        def cast(time):
            return dict(type='combat', combatType='DOTA_COMBATLOG_ITEM', attacker='npc_dota_hero_necrolyte',
                        combatTimestamp=time, inflictor='item_black_king_bar')
        report = self.with_events([purchase(160), cast(170), cast(180), purchase(260), cast(270)])
        rows = [r for r in report['insights']['items'] if r['item'] == 'item_black_king_bar']
        self.assertEqual(len(rows), 2)
        evidence = {r['id']: r for r in report['evidence']}
        for row in rows:
            self.assertEqual(evidence[row['realization']['first_use_event_id']]['type'], 'item_used')
            self.assertEqual(row['realization']['delay_seconds'], 10)
        self.assertEqual(sum(r['type'] == 'item_used' for r in evidence.values()), 2)


if __name__ == '__main__':
    unittest.main()
