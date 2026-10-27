"""Small geometry-augmented Deep Sets; all features are public current-state data."""
import numpy as np
import torch
from torch import nn
from .value_model import ValueNetwork

GEOMETRY_NAMES=([f'skyline_{i}' for i in range(8)]+[f'contacted_skyline_{i}' for i in range(8)]+
 [f'aabb_area_type_{i}' for i in range(11)]+[f'nearest_pair_distance_type_{i}' for i in range(11)]+[f'pair_known_type_{i}' for i in range(11)]+
 ['max_center_y','max_top_y','std_center_y','contacted_fraction','sleeping_fraction','mean_speed','size_known_fraction','geometry_known'])
FEATURE_SPEC=dict(version='geometry57-v1',names=GEOMETRY_NAMES,
 limitation='AABB area sums, not physical union area. Missing sizes remain flagged. No future/seed/policy/final score input.')

def geometry_features(f,g):
    result=np.zeros(57,dtype=np.float32)
    if not g[36]:return result
    result[-1]=1
    if len(f)==0:return result
    f=np.asarray(f);kind=np.argmax(f[:,:11],axis=1);size=f[:,22]>0
    centers=np.array(f[:,11:13],copy=True);centers[:,0]+=f[:,23]*f[:,25];centers[:,1]+=f[:,24]*f[:,25]
    top=centers[:,1]+np.where(size,f[:,21],0)
    for i in range(len(f)):
        left=centers[i,0]-(f[i,20] if size[i] else 0);right=centers[i,0]+(f[i,20] if size[i] else 0)
        for b in range(8):
            if right>=b/8 and left<=(b+1)/8:
                result[b]=max(result[b],float(np.clip(top[i],0,2))/2)
                if f[i,18] and f[i,19]:result[8+b]=max(result[8+b],float(np.clip(top[i],0,2))/2)
    for t in range(11):
        ids=np.flatnonzero(kind==t)
        result[16+t]=min(2,float(np.sum(4*f[ids,20]*f[ids,21]*size[ids])))/2
        if len(ids)>=2:
            xy=centers[ids];d=np.sqrt(((xy[:,None,:]-xy[None,:,:])**2).sum(2));np.fill_diagonal(d,np.inf)
            result[27+t]=min(2,float(np.min(d)))/2;result[38+t]=1
    result[49:]=[float(np.clip(f[:,12].max(),0,2))/2,float(np.clip(top.max(),0,2))/2,float(min(2,np.std(f[:,12])))/2,
        float(np.mean((f[:,18]>0)&(f[:,19]>0))),float(np.mean((f[:,28]>0)&(f[:,29]>0))),
        float(min(2,np.linalg.norm(f[:,13:15],axis=1).mean()))/2,float(size.mean()),1]
    return result

class GeometryValueNetwork(ValueNetwork):
    def __init__(self,width=64,head_width=128):
        super().__init__(width,head_width)
        self.head=nn.Sequential(nn.Linear(width*2+37+57,head_width),nn.ReLU(),nn.Linear(head_width,width),nn.ReLU(),nn.Linear(width,1),nn.Softplus())
    def forward(self,fruits,mask,global_features,geometry):
        z=self.phi(fruits);count=mask.sum(1,keepdim=True)
        mean=(z*mask.unsqueeze(-1)).sum(1)/count.clamp_min(1)
        maximum=z.masked_fill(~mask.unsqueeze(-1),-torch.inf).max(1).values
        maximum=torch.where(count>0,maximum,torch.zeros_like(maximum))
        return self.head(torch.cat([mean,maximum,global_features,geometry],dim=1)).squeeze(-1)*(1-global_features[:,35])

class PackedBoards:
    def __init__(self,data):
        self.manifest,self.records,self.offsets,self.globals,self.targets,self.fruits=data
        self.geometry=np.asarray([geometry_features(self.fruits[self.offsets[i]:self.offsets[i+1]],g) for i,g in enumerate(self.globals)],dtype=np.float32)
        self.groups={v:i for i,v in enumerate(sorted({r['group'] for r in self.records}))}
        self.group_ids=torch.tensor([self.groups[r['group']] for r in self.records])
    def batch(self,indices,hide_next=False):
        ids=[int(i) for i in indices];n=max(1,max(int(self.offsets[i+1]-self.offsets[i]) for i in ids))
        fruit=torch.zeros(len(ids),n,30);mask=torch.zeros(len(ids),n,dtype=torch.bool)
        for j,i in enumerate(ids):
            values=self.fruits[self.offsets[i]:self.offsets[i+1]]
            if len(values):fruit[j,:len(values)]=torch.from_numpy(np.array(values,copy=True));mask[j,:len(values)]=True
        g=torch.tensor(self.globals[ids]);extra=torch.tensor(self.geometry[ids])
        if hide_next:
            hidden=torch.rand(len(ids))<.5;g[hidden,11:22]=0;g[hidden,23]=0
        return fruit,mask,g,extra

def forward(model,kind,inputs):return model(*inputs[:3]) if kind=='v1' else model(*inputs)

def infer(model,kind,boards,indices,batch_size=128):
    model.eval();result=[]
    with torch.inference_mode():
        for start in range(0,len(indices),batch_size):result.extend((forward(model,kind,boards.batch(indices[start:start+batch_size]))*1000).tolist())
    return np.asarray(result,dtype=np.float64)
