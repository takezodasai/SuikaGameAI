using System;

// Final-action-only experimental adapter. Never changes MCTS or consumes RNG.
public static class AlternativeCandidateSelection {
    [Serializable] public sealed class Choice {
        public int recommended_index, alternative_index=-1, actual_index;
        public float recommended_x, alternative_x, actual_x;
        public string policy, reason;
        public bool has_alternative;
    }
    public static Choice Select(int recommended,float x,MctsPlanner.ActionMetric[] candidates,bool alternative) {
        var choice=new Choice{recommended_index=recommended,recommended_x=x,actual_index=recommended,actual_x=x,
            alternative_x=x,policy=alternative?"alternative":"legacy",reason="legacy_recommendation"};
        MctsPlanner.ActionMetric best=null;
        foreach(var c in candidates){
            if(c.index==recommended||c.visits<=0||!c.drop_success||c.immediate_go)continue;
            if(double.IsNaN(c.mean_points)||double.IsInfinity(c.mean_points))throw new InvalidOperationException("Non-finite root mean");
            if(best==null||c.mean_points>best.mean_points||
               (c.mean_points==best.mean_points&&(c.visits>best.visits||c.visits==best.visits&&c.index<best.index)))best=c;
        }
        if(best==null){choice.reason="no_eligible_alternative_fallback_legacy";return choice;}
        if(best.x==x){choice.reason="same_coordinate_fallback_legacy";return choice;}
        choice.has_alternative=true;choice.alternative_index=best.index;choice.alternative_x=best.x;
        if(alternative){choice.actual_index=best.index;choice.actual_x=best.x;choice.reason="fixed_highest_mean_other_eligible";}
        return choice;
    }
}
