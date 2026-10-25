using System;
using System.Collections.Generic;
using UnityEngine;

// Geometric proposals only: no physics, scores, RNG, or hidden NEXT.
public static class DropCandidateGenerator {
    public struct Shape {public int type;public float center_x,min_x,max_x,top_y;}
    public sealed class Set {public float[] x;public string[] sources;}
    public static Set Generate(PlayerController.DropRange range,int heldType,float heldBottom,List<Shape> shapes) {
        if(!range.valid || range.max_x<=range.min_x)throw new ArgumentException("Invalid candidate range");
        float width=range.max_x-range.min_x,half=(range.fruit_left_extent+range.fruit_right_extent)*.5f;
        float offset=(range.fruit_right_extent-range.fruit_left_extent)*.5f;
        var result=new Set {x=new[]{0f,.25f,.5f,.75f,1f},sources=new[]{"left-anchor","grid-fallback","center-anchor","grid-fallback","right-anchor"}};
        // 10% of the original quarter-width spacing; proposal diversity, not a collision tolerance.
        const float spacing=.025f;
        for(int side=0;side<2;side++) {
            float lo=side==0?spacing:.5f+spacing,hi=side==0?.5f-spacing:1-spacing;
            float bestTop=float.NegativeInfinity,bestDistance=float.PositiveInfinity,bestX=result.x[side*2+1];bool found=false;
            foreach(var f in shapes) {
                if(f.type!=heldType || f.top_y>=heldBottom)continue;
                float x=Mathf.Clamp01((f.center_x-offset-range.min_x)/width);if(x<lo || x>hi)continue;
                float center=Mathf.Lerp(range.min_x,range.max_x,x)+offset;bool blocked=false;
                foreach(var other in shapes)if(other.top_y>f.top_y && other.min_x<center+half && other.max_x>center-half){blocked=true;break;}
                if(blocked)continue;
                float distance=Mathf.Abs(x-(side==0?.25f:.75f));
                if(!found || f.top_y>bestTop || (f.top_y==bestTop && (distance<bestDistance || (distance==bestDistance&&x<bestX)))) {
                    found=true;bestTop=f.top_y;bestDistance=distance;bestX=x;
                }
            }
            if(found){result.x[side*2+1]=bestX;result.sources[side*2+1]="visible-same-type";continue;}
            // Gaps in the upper band, inflated by the actual held horizontal footprint.
            float top=float.NegativeInfinity;foreach(var f in shapes)top=Mathf.Max(top,f.top_y);
            var upper=new List<Shape>();foreach(var f in shapes)if(f.top_y>=top-2*half)upper.Add(f);
            upper.Sort((a,b)=>a.min_x!=b.min_x?a.min_x.CompareTo(b.min_x):a.max_x.CompareTo(b.max_x));
            float end=range.left_wall_inner,bestWidth=0;
            foreach(var f in upper) {
                float left=end+half,right=f.min_x-half;
                float x=((left+right)*.5f-offset-range.min_x)/width;
                if(right>left && x>=lo && x<=hi && right-left>bestWidth){bestWidth=right-left;bestX=x;}
                end=Mathf.Max(end,f.max_x);
            }
            float gapLeft=end+half,gapRight=range.right_wall_inner-half;
            float finalX=((gapLeft+gapRight)*.5f-offset-range.min_x)/width;
            if(gapRight>gapLeft && finalX>=lo&&finalX<=hi && gapRight-gapLeft>bestWidth){bestWidth=gapRight-gapLeft;bestX=finalX;}
            if(bestWidth>0){result.x[side*2+1]=Mathf.Clamp01(bestX);result.sources[side*2+1]="upper-gap";}
        }
        return result;
    }
}
