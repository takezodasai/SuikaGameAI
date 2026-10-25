using System;
using System.Collections.Generic;
using UnityEngine;

public partial class PlayerController
{
    public bool StepControlLocked { get; set; }
    [Header("AI Step Movement")]
    [Tooltip("Automatically use Speed times the normal keyboard input coefficient. Applies to live AI and prediction.")]
    public bool matchKeyboardMoveSpeed = true;
    public const float NormalMoveInput = 0.5f;
    public float EffectiveAIMoveSpeed { get { return matchKeyboardMoveSpeed ? Mathf.Abs(speed * NormalMoveInput) : aiMoveSpeed; } }
    [Tooltip("World units/game second, used only when Match Keyboard Move Speed is disabled.")]
    [Min(0.01f)]
    public float aiMoveSpeed = 2.5f;
    // Must match the existing keyboard hand-follow/spawn offset; no new movement rule.
    float HandOffsetX { get { return heldFruitOffset.x; } }

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
        return GetDropRangeForFruit(currentFruit, FindObjectsOfType<Collider2D>());
    }

    // Prediction supplies its own held clone/walls; it must never swap live references.
    public DropRange GetDropRangeForFruit(GameObject heldFruit, IEnumerable<Collider2D> walls)
    {
        var range = new DropRange();
        if (heldFruit == null) { range.error = "no_current_fruit"; return range; }
        Physics2D.SyncTransforms();
        Collider2D fruit = FruitColliderShape.Get(heldFruit);
        if (fruit == null || !fruit.enabled || !fruit.isTrigger)
        { range.error = "unsupported_held_collider"; return range; }
        Bounds shape = fruit.bounds; // Includes actual Circle/Capsule/Polygon offset, scale and rotation.
        float origin = heldFruit.transform.position.x;
        BoxCollider2D left = null, right = null;
        foreach (Collider2D collider in walls)
        {
            if (!collider.enabled || collider.gameObject.scene!=heldFruit.scene || !collider.CompareTag("Wall")) continue;
            Bounds bounds = collider.bounds;
            if (bounds.max.y < shape.min.y || bounds.min.y > shape.max.y) continue;
            BoxCollider2D box = collider as BoxCollider2D;
            // Fail closed for layouts outside the inspected scene's two straight walls.
            if (box == null || box.isTrigger || Mathf.Abs(box.transform.right.y) > 0.00001f)
            { range.error = "unsupported_wall_geometry"; return range; }
            if (left == null) left = box;
            else if (right == null)
            {
                right = box;
                if (left.bounds.center.x > right.bounds.center.x)
                { BoxCollider2D swap = left; left = right; right = swap; }
            }
            else { range.error = "ambiguous_side_walls"; return range; }
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
        range.min_x = range.left_wall_inner + range.fruit_left_extent + range.clearance;
        range.max_x = range.right_wall_inner - range.fruit_right_extent - range.clearance;
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
        if (!CanDropFruit) { error = "drop_cooldown"; return false; }
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
        Collider2D shape = FruitColliderShape.Get(currentFruit);
        bool safe = shape.bounds.min.x >= range.left_wall_inner &&
                    shape.bounds.max.x <= range.right_wall_inner;
        error = "wall_bounds_overlap";
        foreach (Collider2D wall in FindObjectsOfType<Collider2D>())
            if (wall.enabled && wall.gameObject.scene==currentFruit.scene && wall.CompareTag("Wall"))
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

    public bool EnsureHeldWithinRange(out string error)
    {
        DropRange range = GetDropRange();
        error = range.error;
        if (!range.valid) return false;
        float target = Mathf.Clamp(currentFruit.transform.position.x, range.min_x, range.max_x);
        float input = moveDirection;
        bool safe = TryMoveHeldTo(target, range, out error);
        if (safe) moveDirection = input;
        return safe;
    }

    public void InitializeStepPreview()
    {
        if (!EnsureHeldWithinRange(out string error))
            Debug.LogError("Cannot initialize held fruit safely: " + error);
    }
}
