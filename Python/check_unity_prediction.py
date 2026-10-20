"""Short live STEP 4 comparison, with no search/evaluation policy.
Requires Unity Play. compare_step predicts then starts the real step in the SAME Update.
"""
import argparse
import itertools
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from suika_ai.unity_env import UnityEnv


def compare(prediction, state):
    predicted, actual = prediction['fruits'], state['fruits']
    types_match = sorted(f['type'] for f in predicted) == sorted(f['type'] for f in actual)
    errors = []
    if types_match:
        # Stable source IDs first; new/merged IDs are scoped to their physics world.
        remaining = list(actual)
        unmatched = []
        pairs = []
        for p in predicted:
            exact = [a for a in remaining if a['id'] == p['id'] and p['id'] > 0 and a['type'] == p['type']]
            if exact:
                pairs.append((p, exact[0])); remaining.remove(exact[0])
            else:
                unmatched.append(p)
        for kind in sorted({p['type'] for p in unmatched}):
            group = [p for p in unmatched if p['type'] == kind]
            candidates = [a for a in remaining if a['type'] == kind]
            if len(group) > 8:
                raise ValueError('Short comparator supports at most 8 unmatched fruit per type')
            best = min(itertools.permutations(candidates), key=lambda order:
                       sum((a['x']-p['x'])**2+(a['y']-p['y'])**2 for p,a in zip(group,order)))
            pairs.extend(zip(group,best))
        for p, a in pairs:
            errors.append((math.hypot(a['x']-p['x'], a['y']-p['y']),
                           math.hypot(a['vx']-p['vx'], a['vy']-p['vy']),
                           abs((a['angle']-p['angle']+180) % 360-180),
                           abs(a['angular_velocity']-p['angular_velocity'])))
    return dict(types_match=types_match, count=len(actual),
                score_match=prediction['score']==state['score'],
                game_over_match=prediction['game_over']==state['game_over'],
                ticks_match=prediction['physics_steps']==state['actual_total_physics_steps'],
                max_position_error=max((e[0] for e in errors), default=0 if types_match else None),
                max_velocity_error=max((e[1] for e in errors), default=0 if types_match else None),
                max_angle_error=max((e[2] for e in errors), default=0 if types_match else None),
                max_angular_velocity_error=max((e[3] for e in errors), default=0 if types_match else None))


def meets_tolerance(row):
    # Diagnostic acceptance criteria, not a claim of an official gameplay tolerance.
    return (all(row[k] for k in ('types_match', 'score_match', 'game_over_match', 'ticks_match'))
            and row['max_position_error'] <= 1e-3 and row['max_velocity_error'] <= 1e-2
            and row['max_angle_error'] <= 0.5 and row['max_angular_velocity_error'] <= 1.0)


def summarize_trace(diagnostics):
    errors = diagnostics['errors']
    selected = {0, 1, 5, 10, 25, errors[-1]['tick']} if errors else set()
    return {'first_numeric_tick': diagnostics['first_numeric_tick'],
            'first_tolerance_tick': diagnostics['first_tolerance_tick'],
            'ticks_match': diagnostics['actual_ticks'] == diagnostics['predicted_ticks'],
            'truncated': diagnostics['truncated'],
            'max_position_over_time': max((e['position'] for e in errors), default=0),
            'max_velocity_over_time': max((e['velocity'] for e in errors), default=0),
            'checkpoints': [e for e in errors if e['tick'] in selected]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--merge-case', action='store_true', help='Find a visible same-type NEXT and compare two centered drops')
    parser.add_argument('--post-drop-steps', type=int, default=0, choices=range(151), help='Diagnostic horizon; 0 keeps normal 0.5 seconds')
    parser.add_argument('--trace', action='store_true', help='Capture bounded per-physics-tick diagnostics')
    parser.add_argument('--output', type=Path, help='Save measured comparison report')
    args = parser.parse_args()
    with UnityEnv() as env:
        initial = env.reset(timeout=30)
        if args.merge_case:
            for attempt in range(10):
                if initial['current_fruit']['type'] == initial['next_fruit_type']:
                    break
                initial = env.reset(timeout=5)
            else:
                raise RuntimeError('No same-type visible NEXT in 10 resets; test not executed')
        original_send = env._send
        def send(message):
            if message.get('command') == 'step':
                message = dict(message, command='compare_step', trace_physics=args.trace, comparison_post_drop_steps=args.post_drop_steps)
            original_send(message)
        env._send = send
        results = []
        targets = (0.65, 0.65) if args.merge_case else (0.65, 0.65, 0.65, 0.65, 0.65, 0.65, 0.65, 0.65, 0, 1)
        for x in targets:
            try:
                state, reward, done, info = env.step(x, timeout=20)
            except (RuntimeError, TimeoutError) as error:
                results.append({'error': str(error), 'within_tolerance': False})
                break
            prediction = state['prediction']
            assert prediction['source_unchanged'], 'Prediction changed real state/RNG/score'
            row = compare(prediction, state)
            row.update(x=x, reward=reward, predicted_reward=prediction['reward'],
                       merges=prediction['merges'], elapsed_ms=prediction['elapsed_ms'],
                       initial_contacts=prediction['initial_contact_count'],
                       applied_x_error=abs(prediction['applied_x']-info['applied_x']),
                       predicted_ticks=prediction['physics_steps'], actual_ticks=state['actual_total_physics_steps'])
            row['within_tolerance'] = meets_tolerance(row)
            row['timing'] = {k:prediction[k] for k in ('scene_create_ms','copy_ms','simulation_ms','cleanup_schedule_ms')}
            if prediction.get('reference_elapsed_ms', -1) >= 0:
                reference = dict(prediction, fruits=prediction['reference_fruits'], score=prediction['reference_score'], game_over=prediction['reference_game_over'])
                row['reference_error'] = compare(reference, state)
                row['reference_elapsed_ms'] = prediction['reference_elapsed_ms']
                row['diagnostic_prediction_delta'] = compare(reference, dict(state,fruits=prediction['fruits'],score=prediction['score'],game_over=prediction['game_over']))
            diagnostics = prediction.get('diagnostics')
            if diagnostics:
                row['diagnostics'] = diagnostics
                row['diagnostic_summary'] = summarize_trace(diagnostics)
                print(json.dumps({'x':x,'first_numeric_tick':diagnostics['first_numeric_tick'],
                                  'first_tolerance_tick':diagnostics['first_tolerance_tick'],
                                  'final_error':diagnostics['errors'][-1] if diagnostics['errors'] else None}),flush=True)
            print(json.dumps({k:v for k,v in row.items() if k not in ('diagnostics','diagnostic_summary')}), flush=True)
            results.append(row)
            if done: break
        env.reset(timeout=10)
        report = {'all_within_tolerance': all(r['within_tolerance'] for r in results),
                  'position_unit': 'Unity world unit', 'velocity_unit': 'Unity world unit/s',
                  'angle_unit': 'degree', 'angular_velocity_unit': 'degree/s', 'summary': results}
        if args.output:
            args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({'all_within_tolerance': report['all_within_tolerance']}), flush=True)
        return 0 if report['all_within_tolerance'] else 2

if __name__ == '__main__':
    sys.exit(main())
