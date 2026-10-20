using UnityEngine;

public class FruitCollisionHandler : MonoBehaviour
{
    public PlayerController playerController;
    private bool isCollidingWithWall = false;
    private bool isCollidingWithLeftWall = false;
    private bool isCollidingWithRightWall = false;


    private void OnTriggerEnter2D(Collider2D collision)
    {
        if (collision.CompareTag("Wall"))
        {
            if (collision.transform.position.x < 0)  // 左の壁
            {
                isCollidingWithLeftWall = true;
                playerController.SetFruitCollidingWithWallLeft(true);
            }
            else  // 右の壁
            {
                isCollidingWithRightWall = true;
                playerController.SetFruitCollidingWithWallRight(true);
            }
        }
        //Debug.Log($"Left={isCollidingWithLeftWall}");
        //Debug.Log($"Right={isCollidingWithRightWall}");
    }

    private void OnTriggerExit2D(Collider2D collision)
    {
        if (collision.CompareTag("Wall"))
        {
            if (collision.transform.position.x < 0)  // 左の壁
            {
                isCollidingWithLeftWall = false;
                playerController.SetFruitCollidingWithWallLeft(false);
            }
            else  // 右の壁
            {
                isCollidingWithRightWall = false;
                playerController.SetFruitCollidingWithWallRight(false);
            }
        }
        //Debug.Log($"Left={isCollidingWithLeftWall}");
        //Debug.Log($"Right={isCollidingWithRightWall}");
        //Debug.Log("離れました");
    }

    public bool IsCollidingWithWall()
    {
        return isCollidingWithLeftWall || isCollidingWithRightWall;
    }

    public bool IsCollidingWithLeftWall()
    {
        return isCollidingWithLeftWall;
    }

    public bool IsCollidingWithRightWall()
    {
        return isCollidingWithRightWall;
    }
}
