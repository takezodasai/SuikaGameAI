using System;
using System.Reflection;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

public static class PlayerBoundaryProbe
{
    static void Require(bool value, string message)
    { if (!value) throw new Exception("Boundary regression: " + message); }
    static void Safe(PlayerController player)
    {
        Physics2D.SyncTransforms();
        var range = player.GetDropRange();
        var shape = FruitColliderShape.Get(player.currentFruit);
        Require(range.valid, range.error);
        Require(shape.bounds.min.x >= range.left_wall_inner && shape.bounds.max.x <= range.right_wall_inner, "wall bounds overlap");
        foreach (var wall in Object.FindObjectsOfType<Collider2D>())
            if (wall.enabled && wall.CompareTag("Wall"))
            {
                var distance = shape.Distance(wall);
                Require(distance.isValid && !distance.isOverlapped, "wall distance: " + wall.name);
            }
    }
    [MenuItem("Tools/Suika/Run Player Boundary Probe %#F11")]
    public static void Run()
    {
        if (!Application.isPlaying) throw new InvalidOperationException("Requires Play");
        var player = Object.FindObjectOfType<PlayerController>();
        var manager = Object.FindObjectOfType<GameManager>();
        var original = player.fruits;
        var prefabs = EvolutionDatabase.Instance.evolutionPrefabs;
        var fixedTick = typeof(PlayerController).GetMethod("FixedUpdate", BindingFlags.Instance | BindingFlags.NonPublic);
        var choose = typeof(PlayerController).GetMethod("ChooseNextFruit", BindingFlags.Instance | BindingFlags.NonPublic);
        int cases = 0;
        try
        {
            for(int type=0;type<prefabs.Length;type++)
            foreach(bool left in new[]{true,false})
            {
                player.fruits = new[]{prefabs[type]}; manager.ResetGame(""); Safe(player);
                if(left) player.MoveLeft1(); else player.MoveRight1();
                // Execute the actual manual movement function with native Collider queries.
                // No fast-forward of the default physics scene is performed.
                for(int tick=0;tick<100;tick++) fixedTick.Invoke(player,null);
                Safe(player);
                var range=player.GetDropRange();
                float endpoint=left?range.min_x:range.max_x;
                Require(Mathf.Abs(player.currentFruit.transform.position.x-endpoint)<.00001f,"manual endpoint mismatch");
                Require(player.currentFruit.GetComponent<SpriteRenderer>().sortingOrder==31,"held fruit hidden by Player");
                var dropped=player.currentFruit; player.DropFruit();
                Require(dropped.GetComponent<SpriteRenderer>().sortingOrder==prefabs[type].GetComponent<SpriteRenderer>().sortingOrder,
                    "drop did not restore prefab render order");
                Require(player.currentFruit!=dropped && !dropped.GetComponent<FruitEvolution>().IsPreview,"drop failed");
                Require(!FruitColliderShape.Get(dropped).isTrigger,"drop collider still trigger");
                Safe(player); cases++;
            }
            // A tiny fruit at either edge followed by the largest fruit must also fit.
            foreach(bool left in new[]{true,false})
            {
                player.fruits=new[]{prefabs[0]};manager.ResetGame("");
                var range=player.GetDropRange();
                Require(player.TryMoveHeldTo(left?range.min_x:range.max_x,range,out _),"initial edge move");
                player.fruits=new[]{prefabs[10]}; choose.Invoke(player,null);
                player.DropFruit(); Safe(player);
                Require(player.currentFruit.GetComponent<FruitEvolution>().fruitType==10,"larger NEXT missing");
                cases++;
            }
            Debug.Log("PASS: Player boundary probe "+cases+" cases; all 11 types, both manual endpoints, drop guards and larger NEXT spawn; native Collider bounds/Distance safe");
        }
        finally { player.fruits=original; manager.ResetGame(""); }
    }
}
