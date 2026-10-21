using System;
using System.Reflection;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

// Short Play-mode regression against the actual grape prefab and wall callbacks.
public static class PreviewControlProbe
{
    static PlayerController player;
    static GameManager manager;
    static GameObject[] original;
    static Vector3 nextCenter;
    static float start;
    static GameObject oldHeld;
    static void Require(bool valid, string message)
    { if (!valid) throw new Exception("Preview control regression: " + message); }

    [MenuItem("Tools/Suika/Run Preview Control Probe %#F10")]
    public static void Run()
    {
        if (!Application.isPlaying || original != null)
            throw new InvalidOperationException("Requires idle Play mode");
        player = Object.FindObjectOfType<PlayerController>();
        manager = Object.FindObjectOfType<GameManager>();
        original = player.fruits;
        try
        {
            player.fruits = new[] { EvolutionDatabase.Instance.evolutionPrefabs[2] };
            manager.ResetGame("");
            oldHeld = player.currentFruit;
            nextCenter = player.nextFruitObject.GetComponent<SpriteRenderer>().bounds.center;
            var body = oldHeld.GetComponent<Rigidbody2D>();
            Require(body != null && body.gravityScale == 0 && body.velocity == Vector2.zero,
                "held grape starts with falling velocity");
            Require(!player.nextFruitObject.GetComponent<Rigidbody2D>().simulated,
                "NEXT grape is simulated");
            Require(player.nextPreviewBackground != null, "NEXT background anchor missing");
            var rect = player.nextPreviewBackground.rect;
            var expected = player.nextPreviewBackground.TransformPoint(new Vector3(
                rect.xMin + rect.width * player.nextPreviewAnchor.x,
                rect.yMin + rect.height * player.nextPreviewAnchor.y, 0));
            Require(Vector2.Distance(nextCenter, expected) < .001f, "NEXT not at circle centre");
            start = Time.fixedTime;
            EditorApplication.update += Tick;
        }
        catch { Restore(); throw; }
    }
    static void Tick()
    {
        if (!Application.isPlaying) { Restore(); return; }
        if (Time.fixedTime - start < .4f) return;
        try
        {
            Require(Vector3.Distance(nextCenter, player.nextFruitObject.GetComponent<SpriteRenderer>().bounds.center) < .001f,
                "NEXT grape moved during physics updates");
            Require(oldHeld.GetComponent<Rigidbody2D>().velocity == Vector2.zero, "held grape accumulated velocity");
            player.SetFruitCollidingWithWallRight(true);
            player.DropFruit();
            Require(oldHeld.GetComponent<Rigidbody2D>().gravityScale == 1 &&
                oldHeld.GetComponent<Rigidbody2D>().velocity == Vector2.zero,
                "drop did not start with normal gravity and zero velocity");
            Require(!player.isFruitCollidingWithWallRight, "new fruit retained previous wall flag");
            foreach (var wall in Object.FindObjectsOfType<Collider2D>())
                if (wall.CompareTag("Wall") && wall.transform.position.x > 0)
                    typeof(FruitCollisionHandler).GetMethod("OnTriggerEnter2D", BindingFlags.Instance | BindingFlags.NonPublic)
                        .Invoke(oldHeld.GetComponent<FruitCollisionHandler>(), new object[] { wall });
            player.MoveRight();
            Require(player.moveDirection > 0, "dropped grape still blocks right input");
            Debug.Log("PASS: grape held/NEXT stable across 0.4 game seconds; normal drop velocity; old-wall callbacks ignored; right movement; NEXT circle centre");
        }
        catch (Exception error) { Debug.LogException(error); }
        finally { Restore(); }
    }
    static void Restore()
    {
        EditorApplication.update -= Tick;
        if (player != null && original != null) player.fruits = original;
        original = null;
        if (Application.isPlaying && manager != null) manager.ResetGame("");
    }
}
