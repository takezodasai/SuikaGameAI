"""Small candidate scoring policy for experimental MCTS rollout only."""
import math
import numpy as np

VERSION='candidate-linear213-v1'
GRID=[0.,.25,.5,.75,1.]

def features(sample):
    s=sample['state'];left,right,bottom,top=sample.get('geometry',s.get('geometry'));w=right-left;h=top-bottom
    if w<=0 or h<=0 or s.get('game_over'):raise ValueError('Invalid nonterminal public geometry')
    held=s['current_fruit']['type'];nxt=s['next_fruit_type'];fs=s['fruits']
    if not 0<=held<=10 or not -1<=nxt<=10:raise ValueError('Unknown fruit')
    ys=[(f['y']-bottom)/h for f in fs]
    base=[1,len(fs)/40,max(ys,default=0),sum(ys)/max(1,len(fs)),sum(math.hypot(f['vx'],f['vy']) for f in fs)/max(1,len(fs))/10,s['score']/3000]
    base += [sum(f['type']==t for f in fs)/10 for t in range(11)]
    base += [float(held==t) for t in range(11)]+[float(nxt==t) for t in range(-1,11)]
    out=[]
    for i,x in enumerate(GRID):
        b=[0.]*200;b[i*40:(i+1)*40]=base
        kernel=lambda f:math.exp(-.5*(((f['x']-left)/w-x)/.2)**2)
        b += [sum(kernel(f) for f in fs if f['type']==t)/10 for t in range(11)]
        b += [min([abs((f['x']-left)/w-x) for f in fs if f['type']==held]+[1.]),max([((f['y']-bottom)/h)*kernel(f) for f in fs]+[0.])]
        out.append(b)
    a=np.asarray(out,dtype=np.float64)
    if a.shape!=(5,213) or not np.isfinite(a).all():raise ValueError('Invalid features')
    return np.clip(a,-10,10)

def probabilities(model,sample):
    if model['version']!=VERSION:raise ValueError('Wrong model')
    logits=features(sample)@np.asarray(model['weights']);logits-=logits.max();p=np.exp(logits);return p/p.sum()
