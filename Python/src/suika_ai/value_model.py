"""Small FP32 Deep Sets value model, isolated from live gameplay."""
import torch
from torch import nn
from .value_data import FRUIT_NAMES,GLOBAL_NAMES,encode,SCORE_SCALE

class ValueNetwork(nn.Module):
    def __init__(self,width=64,head_width=128):
        super().__init__()
        self.phi=nn.Sequential(nn.Linear(len(FRUIT_NAMES),width),nn.ReLU(),nn.Linear(width,width),nn.ReLU())
        self.head=nn.Sequential(nn.Linear(width*2+len(GLOBAL_NAMES),head_width),nn.ReLU(),nn.Linear(head_width,width),nn.ReLU(),nn.Linear(width,1),nn.Softplus())
    def forward(self,fruits,mask,global_features):
        z=self.phi(fruits);count=mask.sum(1,keepdim=True)
        mean=(z*mask.unsqueeze(-1)).sum(1)/count.clamp_min(1)
        maximum=z.masked_fill(~mask.unsqueeze(-1),-torch.inf).max(1).values
        maximum=torch.where(count>0,maximum,torch.zeros_like(maximum))
        value=self.head(torch.cat([mean,maximum,global_features],dim=1)).squeeze(-1)
        return value*(1-global_features[:,35]) # A known terminal state has no future reward.

def encoded_rows(samples):return [encode(s) for s in samples]
def batch(rows,indices,device='cpu'):
    selected=[rows[int(i)] for i in indices];n=max(1,max(len(r[0]) for r in selected))
    fruits=torch.zeros(len(selected),n,len(FRUIT_NAMES),dtype=torch.float32)
    mask=torch.zeros(len(selected),n,dtype=torch.bool)
    for i,(f,_) in enumerate(selected):
        if f:fruits[i,:len(f)]=torch.tensor(f,dtype=torch.float32);mask[i,:len(f)]=True
    globals=torch.tensor([g for _,g in selected],dtype=torch.float32)
    return fruits.to(device),mask.to(device),globals.to(device)

def predict(model,samples,device='cpu',batch_size=128):
    model.eval();rows=encoded_rows(samples);values=[]
    with torch.inference_mode():
        for start in range(0,len(rows),batch_size):values+= (model(*batch(rows,range(start,min(len(rows),start+batch_size)),device))*SCORE_SCALE).cpu().tolist()
    return values
