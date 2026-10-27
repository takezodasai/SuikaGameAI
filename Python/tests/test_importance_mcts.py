import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from suika_ai.unity_env import UnityEnv, validate_planning_settings, PLANNING_DEFAULTS
from test_unity_env import state
from test_planning import planned_reply

class ImportanceModeTests(unittest.TestCase):
    def settings(self, **extra):
        return validate_planning_settings(dict(ai_mode='mcts',mcts_extended_budget=True,
            mcts_budget_mode='importance',mcts_max_iterations=32768,mcts_time_limit_seconds=120,
            mcts_widening=True,widening_policy='budgeted',**extra))

    def test_bounds_and_independent_depth_switch(self):
        for depth in (2,4,16,256):
            self.assertEqual(self.settings(mcts_max_depth=depth,mcts_auto_depth=False)['mcts_max_depth'],depth)
        for enabled in (True,False):
            self.assertEqual(self.settings(mcts_auto_depth=enabled)['mcts_auto_depth'],enabled)
        for cap in (32,64,128,256,512,32768):
            x=dict(self.settings());x['mcts_max_iterations']=cap
            self.assertEqual(validate_planning_settings(x)['mcts_max_iterations'],cap)
        for key,value in (('mcts_max_iterations',32769),('mcts_time_limit_seconds',121),('mcts_max_depth',257)):
            x=dict(self.settings());x[key]=value
            with self.assertRaises(ValueError):validate_planning_settings(x)

    def test_legacy_defaults_and_modes_preserved(self):
        self.assertEqual(PLANNING_DEFAULTS['mcts_budget_mode'],'fixed')
        self.assertFalse(PLANNING_DEFAULTS['mcts_extended_budget'])
        for mode in ('fixed','time','adaptive'):
            self.assertEqual(validate_planning_settings(dict(ai_mode='mcts',mcts_budget_mode=mode))['mcts_budget_mode'],mode)
        for extra in (dict(mcts_extended_budget=False),dict(widening_policy='legacy'),dict(execution_mode='frames')):
            x=dict(self.settings());x.update(extra)
            with self.assertRaises(ValueError):validate_planning_settings(x)

    def test_settings_are_sent_with_existing_step_ledger(self):
        with UnityEnv(local=('127.0.0.1',0)) as env:
            env._action_episode='episode1'
            with patch.object(env,'receive_state',side_effect=[state(),planned_reply()]),patch.object(env,'_send') as send:
                _,reward,_,info=env.plan_step(self.settings(mcts_auto_depth=True))
                sent=send.call_args.args[0]
                self.assertEqual(sent['planning_settings']['mcts_budget_mode'],'importance')
                self.assertEqual(sent['planning_settings']['mcts_time_limit_seconds'],120)
                self.assertEqual(sent['action_id'],1)
                self.assertEqual(reward,3)
                self.assertTrue(info['drop_success'])

    def test_gui_cli_passes_json_settings_and_actual_events(self):
        spec=importlib.util.spec_from_file_location('importance_cli',Path(__file__).parents[1]/'play_parallel_ai.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            settings=Path(tmp)/'settings.json';settings.write_text(json.dumps(self.settings()))
            argv=['play_parallel_ai.py','--games','1','--settings',str(settings),'--ai-mode','mcts','--mcts-max-depth','4','--require-metadata','--episode-events','--view-games','0']
            with patch.object(sys,'argv',argv),patch.object(module,'run_parallel',return_value={'workers':[]}) as run:
                self.assertEqual(module.main(),0)
            self.assertEqual(run.call_args.args[8]['mcts_budget_mode'],'importance')
            self.assertFalse(run.call_args.args[7])
            self.assertTrue(run.call_args.kwargs['episode_events'])
            self.assertTrue(run.call_args.kwargs['require_metadata'])
