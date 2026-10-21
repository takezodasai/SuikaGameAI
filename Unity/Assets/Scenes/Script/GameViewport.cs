using UnityEngine;

// Keep the authored board/UI composition visible at any window aspect.
// No world transforms, camera zoom or physics settings are changed here.
[ExecuteAlways, RequireComponent(typeof(Camera))]
public sealed class GameViewport : MonoBehaviour
{
    public Vector2 referenceSize = new Vector2(800, 436.9686f);
    private Camera view;
    void OnEnable() { view = GetComponent<Camera>(); Apply(); }
    void Update() { Apply(); }
    void OnPreCull() { Apply(); }
    void OnDisable() { if (view != null) view.rect = new Rect(0, 0, 1, 1); }

    public static Rect Fit(float width, float height, Vector2 reference)
    {
        if (width <= 0 || height <= 0 || reference.x <= 0 || reference.y <= 0)
            return new Rect(0, 0, 1, 1);
        float ratio = (width / height) / (reference.x / reference.y);
        return ratio > 1 ? new Rect((1 - 1 / ratio) / 2, 0, 1 / ratio, 1)
                         : new Rect(0, (1 - ratio) / 2, 1, ratio);
    }
    void Apply()
    {
        if (view == null) return;
        float width = view.targetTexture != null ? view.targetTexture.width : Screen.width;
        float height = view.targetTexture != null ? view.targetTexture.height : Screen.height;
        Rect rect = Fit(width, height, referenceSize);
        if (view.rect != rect) view.rect = rect;
    }
}
