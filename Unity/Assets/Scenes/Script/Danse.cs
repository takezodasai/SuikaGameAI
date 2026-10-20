using UnityEngine;

public class Danse : MonoBehaviour
{
    public bool isHeld = false;
    public Rigidbody2D rb;
    public Collider2D coll;

    void Start() { InitializePhysicsMaterial(); }

    // Shared initialization for a newly generated prediction fruit.
    public PhysicsMaterial2D InitializePhysicsMaterial()
    {
        // Rigidbody2DとCollider2Dの設定
        //rb = GetComponent<Rigidbody2D>();
        coll = GetComponent<Collider2D>();

        // 物理マテリアルを適用
        if (coll != null)
        {
            PhysicsMaterial2D material = new PhysicsMaterial2D();
            material.friction = 0.5f;  // 摩擦を0に設定
            material.bounciness = 0.01f;  // 反発力を設定
            coll.sharedMaterial = material;  // コライダーにマテリアルを適用
        }

        return coll != null ? coll.sharedMaterial : null;

        // Rigidbody2Dの設定
        //rb.interpolation = RigidbodyInterpolation2D.Interpolate;
        //rb.collisionDetectionMode = CollisionDetectionMode2D.Continuous;
    }
}
