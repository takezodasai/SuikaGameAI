using System;
using UnityEngine;

public partial class PlayerController
{
    public bool StepControlLocked { get; set; }
    [Header("AI Step Movement")]
    [Tooltip("World units per game second. Default 2.5 matches speed=5 times keyboard input=0.5. Captured at step start.")]
    [Min(0.01f)]
    public float aiMoveSpeed = 2.5f;
    // Must match the existing keyboard hand-follow/spawn offset; no new movement rule.
    const float HandOffsetX = -0.7f;

    [Serializable]
    public class DropRange
    {
        public bool valid;
        public string error = "";
        public float min_x, max_x, left_wall_inner, right_wall_inner;
        public float fruit_left_extent, fruit_right_extent, clearance;
    }

    public DropRange GetDropRange()
    {
        var range = new DropRange();
        if (currentFruit == null) { range.error = "no_current_fruit"; return range; }
        Physics2D.SyncTransforms();
        PolygonCollider2D fruit = currentFruit.GetComponent<PolygonCollider2D>();
        if (fruit == null || !fruit.enabled || !fruit.isTrigger)
        { range.error = "unsupported_held_collider"; return range; }
        Bounds shape = fruit.bounds; // Includes actual polygon offset, scale and rotation.
        float origin = currentFruit.transform.position.x;
        float anchor = spawnPosition.x + HandOffsetX;
        BoxCollider2D left = null, right = null;
        foreach (Collider2D collider in FindObjectsOfType<Collider2D>())
        {
            if (!collider.enabled || !collider.CompareTag("Wall")) continue;
            Bounds bounds = collider.bounds;
            if (bounds.max.y < shape.min.y || bounds.min.y > shape.max.y) continue;
            BoxCollider2D box = collider as BoxCollider2D;
            // Fail closed for layouts outside the inspected scene's two straight walls.
            if (box == null || box.isTrigger || Mathf.Abs(box.transform.right.y) > 0.00001f)
            { range.error = "unsupported_wall_geometry"; return range; }
            if (bounds.center.x < anchor)
            {
                if (left != null) { range.error = "ambiguous_left_wall"; return range; }
                left = box;
            }
            else
            {
                if (right != null) { range.error = "ambiguous_right_wall"; return range; }
                right = box;
            }
        }
        if (left == null || right == null)
        { range.error = "missing_side_walls"; return range; }
        // Reserve contact space for both colliders plus one contact offset of clearance.
        // Collider2D.Distance remains the final authority (bounds alone missed contact skin).
        range.clearance = 3 * Physics2D.defaultContactOffset;
        range.left_wall_inner = left.bounds.max.x;
        range.right_wall_inner = right.bounds.min.x;
        range.fruit_left_extent = origin - shape.min.x;
        range.fruit_right_extent = shape.max.x - origin;
        range.min_x = Mathf.Max(range.left_wall_inner + range.fruit_left_extent + range.clearance,
            eftWarpThreshold + HandOffsetX + range.clearance);
        range.max_x = Mathf.Min(range.right_wall_inner - range.fruit_right_extent - range.clearance,
            rightWarpThreshold + HandOffsetX - range.clearance);
        // Include Player collisions too if a scene enables its collider (disabled in gameDisplay).
        foreach (Collider2D collider in GetComponents<Collider2D>())
        {
            if (!collider.enabled || collider.isTrigger) continue;
            Bounds bounds = collider.bounds;
            range.min_x = Mathf.Max(range.min_x, range.left_wall_inner +
                (transform.position.x - bounds.min.x) + HandOffsetX + range.clearance);
            range.max_x = Mathf.Min(range.max_x, range.right_wall_inner -
                (bounds.max.x - transform.position.x) + HandOffsetX - range.clearance);
        }
        range.valid = range.min_x <= range.max_x;
        if (!range.valid) range.error = "fruit_does_not_fit";
        return range;
    }

    public bool TryDropAt(float normalizedX, out float appliedX, out long fruitId,
        out DropRange range, out string error)
    {
        appliedX = 0; fruitId = 0;
        range = GetDropRange();
        error = range.error;
        if (float.IsNaN(normalizedX) || float.IsInfinity(normalizedX) || normalizedX < 0 || normalizedX > 1)
        { error = "x_out_of_range"; return false; }
        if (!range.valid) return false;
        float target = Mathf.Lerp(range.min_x, range.max_x, normalizedX);
        if (!TryMoveHeldTo(target, range, out error)) return false;
        GameObject dropped = currentFruit;
        fruitId = dropped.GetComponent<FruitEvolution>().ObservationId;
        appliedX = dropped.transform.position.x;
        DropFruit();
        bool success = currentFruit != dropped && !dropped.GetComponent<FruitEvolution>().IsPreview;
        error = success ? "" : "drop_failed";
        return success;
    }

    // Shared by each movement tick and the final drop; never changes collider/physics settings.
    public bool TryMoveHeldTo(float target, DropRange range, out string error)
    {
        error = "";
        if (currentFruit == null || !range.valid || target < range.min_x || target > range.max_x)
        { error = "unsafe_movement_position"; return false; }
        Vector3 oldPlayer = transform.position, oldFruit = currentFruit.transform.position;
        float oldDirection = moveDirection;
        Vector2 oldVelocity = rb.velocity;
        Vector3 destination = oldPlayer;
        destination.x = target - HandOffsetX;
        transform.position = destination;
        rb.position = new Vector2(destination.x, destination.y);
        rb.velocity = new Vector2(0, rb.velocity.y);
        moveDirection = 0;
        Vector3 position = oldFruit;
        position.x = target;
        currentFruit.transform.position = position;
        Physics2D.SyncTransforms();
        PolygonCollider2D shape = currentFruit.GetComponent<PolygonCollider2D>();
        bool safe = shape.bounds.min.x >= range.left_wall_inner &&
                    shape.bounds.max.x <= range.right_wall_inner;
        error = "wall_bounds_overlap";
        foreach (Collider2D wall in FindObjectsOfType<Collider2D>())
            if (wall.enabled && wall.CompareTag("Wall"))
            {
                ColliderDistance2D distance = shape.Distance(wall);
                if (!distance.isValid || distance.isOverlapped)
                { safe = false; error = "wall_overlap_or_invalid_distance:" + wall.name; }
            }
        if (!safe)
        {
            transform.position = oldPlayer;
            rb.position = new Vector2(oldPlayer.x, oldPlayer.y);
            rb.velocity = oldVelocity;
            moveDirection = oldDirection;
            currentFruit.transform.position = oldFruit;
            Physics2D.SyncTransforms();
            return false;
        }
        error = "";
        return true;
    }

    public void InitializeStepPreview()
    {
        // A larger NEXT spawned at the old small fruit's edge can start inside a wall.
        // Initialize the NEW object safely before its first rendered frame, never snap
        // an already moving fruit. Keyboard spawning remains unchanged.
        DropRange range = GetDropRange();
        if (!range.valid) return;
        float x = currentFruit.transform.position.x;
        float safeX = Mathf.Clamp(x, range.min_x, range.max_x);
        string error;
        if (!TryMoveHeldTo(safeX, range, out error))
            Debug.LogError("Cannot initialize step preview safely: " + error);
    }
}
