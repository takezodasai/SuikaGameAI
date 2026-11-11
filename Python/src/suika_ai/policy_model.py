"""Small candidate-conditioned Deep Sets; isolated from the game and MCTS."""
import torch
from torch import nn

# Legacy descriptor name "distance_from_held" is a dimensionless coordinate
# difference: candidate x uses the legal drop range, held x uses board width.
# It is not a physical world-space distance. Keep the schema stable for saved models.
CANDIDATE_SPEC=['normalized_x','x_squared','distance_from_held','left_endpoint','right_endpoint']

class PolicyNetwork(nn.Module):
    def __init__(self,kind='deepsets',width=64):
        super().__init__();self.kind=kind
        if kind not in ('deepsets','globals'):raise ValueError('Unknown policy model')
        self.phi=nn.Sequential(nn.Linear(30,width),nn.ReLU(),nn.Linear(width,width),nn.ReLU()) if kind=='deepsets' else None
        self.head=nn.Sequential(nn.Linear(37+len(CANDIDATE_SPEC)+(2*width if self.phi is not None else 0),128 if self.phi is not None else 64),nn.ReLU(),nn.Linear(128 if self.phi is not None else 64,64),nn.ReLU(),nn.Linear(64,1))
    def forward(self,fruits,mask,globals_,xs,candidate_mask):
        context=globals_
        if self.phi is not None:
            z=self.phi(fruits);count=mask.sum(1,keepdim=True)
            mean=(z*mask.unsqueeze(-1)).sum(1)/count.clamp_min(1)
            maximum=z.masked_fill(~mask.unsqueeze(-1),-torch.inf).max(1).values
            maximum=torch.where(count>0,maximum,torch.zeros_like(maximum));context=torch.cat([mean,maximum,globals_],-1)
        features=torch.stack([xs,xs.square(),(xs-globals_[:,24,None]).abs(),(xs==0).float(),(xs==1).float()],-1)
        logits=self.head(torch.cat([context[:,None,:].expand(-1,xs.shape[1],-1),features],-1)).squeeze(-1)
        return logits.masked_fill(~candidate_mask,-1e9)

class PolicyBoards:
    def __init__(self,dataset):
        self.manifest,self.records,self.arrays=dataset
    def batch(self,ids):
        r=self.records;a=self.arrays;off=a['offsets'];n=max(1,max(int(off[i+1]-off[i]) for i in ids));k=max(len(r[i]['candidate_x']) for i in ids)
        fruits=torch.zeros(len(ids),n,30);mask=torch.zeros(len(ids),n,dtype=torch.bool);xs=torch.zeros(len(ids),k);cm=torch.zeros(len(ids),k,dtype=torch.bool);targets=torch.zeros(len(ids),k)
        for j,i in enumerate(ids):
            f=a['fruits'][off[i]:off[i+1]];m=len(f);c=len(r[i]['candidate_x'])
            if m:fruits[j,:m]=torch.from_numpy(f.copy());mask[j,:m]=True
            xs[j,:c]=torch.tensor(r[i]['candidate_x']);cm[j,:c]=True
            v=torch.tensor(r[i]['visits'],dtype=torch.float32);targets[j,:c]=v/v.sum()
        g=torch.from_numpy(a['globals'][ids].copy())
        return (fruits,mask,g,xs,cm),targets,torch.tensor([r[i]['selected_index'] for i in ids]),torch.tensor([r[i]['quality_weight'] for i in ids])

def losses(logits,target,selected):
    logp=torch.log_softmax(logits,-1)
    soft=-(target*logp).sum(-1);hard=-logp.gather(1,selected[:,None]).squeeze(1)
    return soft+.25*hard

def infer(model,boards,ids,batch_size=128):
    result=[];model.eval()
    with torch.inference_mode():
        for start in range(0,len(ids),batch_size):
            group=ids[start:start+batch_size];inputs,_,_,_=boards.batch(group);prob=torch.softmax(model(*inputs),-1).tolist()
            result.extend([p[:len(boards.records[i]['candidate_x'])] for i,p in zip(group,prob)])
    return result
