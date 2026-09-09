"""Synthetic counts exercise outcome accounting, not claims about actual heroes."""
from copy import deepcopy
import unittest

from narma_video.build_statistics import GUIDES, SourceError, catalog, purchases, suggestions, wilson


def bucket(**changes):
    return {"heroId":47,"position":"POSITION_2","bracketBasicIds":"HERALD_GUARDIAN",
            "week":2957,"itemId":1,"instance":0,"time":10,"matchCount":100,"winCount":50,**changes}


class PurchaseAccounting(unittest.TestCase):
    def setUp(self):
        self.items={1:{"id":"black_king_bar","name":"Black King Bar","eligible":True,"cost":4000,"components":[]}}

    def test_first_instance_minute_buckets_are_combined_without_repurchase_inflation(self):
        rows=[bucket(),bucket(time=20,matchCount=300,winCount=180),bucket(instance=1,matchCount=1000,winCount=900)]
        evidence,week=purchases(rows,self.items,47,2,"HERALD_GUARDIAN")
        self.assertEqual(week,2957)
        self.assertEqual(evidence['black_king_bar']['matches'],400)
        self.assertEqual(evidence['black_king_bar']['winrate'],57.5)
        self.assertEqual(evidence['black_king_bar']['average_minute'],17.5)

    def test_invalid_or_cross_cohort_data_is_rejected(self):
        cases=[[bucket(),bucket()], [bucket(),bucket(week=2956,time=11)],
               [bucket(heroId=8)],[bucket(position='POSITION_1')],
               [bucket(bracketBasicIds='DIVINE_IMMORTAL')],[bucket(winCount=101)],
               [bucket(matchCount=True)],[bucket(time=76)]]
        for rows in cases:
            with self.subTest(rows=rows),self.assertRaises(SourceError):
                purchases(rows,self.items,47,2,'HERALD_GUARDIAN')

    def test_no_joint_build_winrate_is_derived(self):
        evidence,_=purchases([bucket()],self.items,47,2,'HERALD_GUARDIAN')
        self.assertEqual(set(evidence),{'black_king_bar'})
        self.assertLess(wilson(1,1),wilson(600,1000))

    def test_null_component_metadata_does_not_make_recipes_eligible(self):
        raw={'constants':{'items':[{'id':1,'name':'item_blink','displayName':'Blink Dagger',
              'stat':{'cost':2250,'isRecipe':False,'isPurchasable':True},'components':None},
             {'id':2,'name':'item_recipe_blink','stat':{'cost':200,'isRecipe':True,'isPurchasable':True}}],
             'gameVersions':[{'name':'7.40b','asOfDateTime':1766534400}]}}
        items,patch=catalog(raw)
        self.assertEqual(items[1]['id'],'blink')
        self.assertFalse(items[2]['eligible'])
        self.assertEqual(patch,'7.40b')


class SixSlotSelection(unittest.TestCase):
    def fixtures(self,guide):
        pool={r['id']:r for k in ('core_items','situational_items','final_items') for r in guide[k]}
        items={i:{'id':key,'name':key,'eligible':True,'cost':2000,'components':[]} for i,key in enumerate(pool,1)}
        evidence={key:{'id':key,'matches':200,'wins':120,'winrate':60,'average_minute':20,
                       'lower_bound':wilson(120,200)} for key in pool}
        return items,evidence

    def test_all_authored_hero_pools_produce_six_compatible_slots(self):
        forbidden=[{'maelstrom','mjollnir'},{'dragon_lance','hurricane_pike'},
                   {'witch_blade','devastator'},{'cyclone','wind_waker'},
                   {'blink','overwhelming_blink'},{'urn_of_shadows','spirit_vessel'}]
        for guide in GUIDES.values():
            items,evidence=self.fixtures(guide)
            for mode in ('popular','winrate'):
                with self.subTest(guide=guide['id'],mode=mode):
                    rows=suggestions(guide,evidence,items,mode)
                    self.assertEqual(len(rows),6)
                    names={r['id'] for r in rows}
                    self.assertEqual(len(names),6)
                    self.assertFalse(any(pair<=names for pair in forbidden))

    def test_missing_evidence_is_not_filled_with_invented_items(self):
        guide=GUIDES['viper-mid-pressure'];items,evidence=self.fixtures(guide)
        evidence={key:row for key,row in list(evidence.items())[:3]}
        self.assertEqual(suggestions(guide,evidence,items,'popular'),[])

    def test_tiny_perfect_winrate_does_not_displace_supported_option(self):
        guide=GUIDES['viper-mid-pressure'];items,evidence=self.fixtures(guide)
        evidence['pipe'].update(matches=2,wins=2,winrate=100,lower_bound=wilson(2,2))
        rows=suggestions(guide,evidence,items,'winrate')
        self.assertEqual(len(rows),6)
        self.assertNotIn('pipe',{r['id'] for r in rows})

    def test_unknown_hero_items_cannot_enter_a_plan(self):
        guide=GUIDES['viper-mid-pressure'];items,evidence=self.fixtures(guide)
        items[999]={'id':'rapier','name':'Divine Rapier','cost':6000,'eligible':True,'components':[]}
        evidence['rapier']={'id':'rapier','matches':10000,'wins':9999,'lower_bound':.99}
        self.assertNotIn('rapier',{r['id'] for r in suggestions(guide,evidence,items,'winrate')})


if __name__=='__main__':
    unittest.main()
