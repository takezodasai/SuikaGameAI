using UnityEngine;

// Only enabled colliders participate: disabled legacy Polygon shapes stay disabled.
public static class FruitColliderShape
{
    public static Collider2D Get(GameObject fruit)
    {
        foreach (var collider in fruit.GetComponents<Collider2D>())
            if (collider.enabled) return collider;
        return null;
    }
}
