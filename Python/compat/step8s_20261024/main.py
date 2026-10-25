import socket                # 1. UDP通信に必要なソケットライブラリをインポート
import yaml                  # 2. YAMLファイルを読み込むためのライブラリをインポート
import json                  # 3. JSON形式のエンコード／デコードに必要なライブラリをインポート
import time                  # 4. ループ内の待機処理のためにインポート
import numpy as np           # 5. 数値計算や配列操作に利用するためにNumPyをインポート
import random                # 6. ランダムな選択を行うための標準ライブラリをインポート
from collections import deque  # 7. リプレイバッファ用にdequeをインポート
import torch                 # 8. PyTorch本体をインポート
import torch.nn as nn        # 9. ニューラルネットワーク構築用のモジュールをインポート
import torch.optim as optim  # 10. 最適化アルゴリズム用のモジュールをインポート
import base64                # 11. 画像データのBase64デコード用ライブラリをインポート
import cv2                   # 12. OpenCVによる画像復元用ライブラリをインポート

# 変更箇所: 指定された11種類の果物に対するワンホットエンコーディングマッピング
fruit_type_to_onehot = {
    "cherry":      [1,0,0,0,0,0,0,0,0,0,0],
    "storobary":   [0,1,0,0,0,0,0,0,0,0,0],
    "grap":        [0,0,1,0,0,0,0,0,0,0,0],
    "orange":      [0,0,0,1,0,0,0,0,0,0,0],
    "kaki":        [0,0,0,0,1,0,0,0,0,0,0],
    "apple":       [0,0,0,0,0,1,0,0,0,0,0],
    "nashi":       [0,0,0,0,0,0,1,0,0,0,0],
    "peach":       [0,0,0,0,0,0,0,1,0,0,0],
    "painaple":    [0,0,0,0,0,0,0,0,1,0,0],
    "melon":       [0,0,0,0,0,0,0,0,0,1,0],
    "watermelon":  [0,0,0,0,0,0,0,0,0,0,1]
}

# 13. DQN（Deep Q-Network）のネットワークアーキテクチャの定義
class DQN(nn.Module):
    def __init__(self, input_dim, output_dim):
        super(DQN, self).__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 128),  # 入力層から128ユニットの全結合層
            nn.ReLU(),                  # ReLU活性化関数
            nn.Linear(128, 128),         # 128ユニットから128ユニットの全結合層
            nn.ReLU(),                  # ReLU活性化関数
            nn.Linear(128, output_dim)   # 出力層：各アクションのQ値を出力
        )
    def forward(self, x):
        return self.net(x)              # 入力xをネットワークに通して出力を返す

# 14. リプレイバッファの定義（経験を保存するための構造）
class ReplayBuffer:
    def __init__(self, capacity):
        self.buffer = deque(maxlen=capacity)  # 指定容量まで経験を保持（容量超過時は古い経験を自動削除）
    def push(self, state, action, reward, next_state, done):
        self.buffer.append((state, action, reward, next_state, done))  # 経験タプルを追加
    def sample(self, batch_size):
        batch = random.sample(self.buffer, batch_size)  # ランダムにミニバッチをサンプリング
        states, actions, rewards, next_states, dones = map(np.array, zip(*batch))
        return states, actions, rewards, next_states, dones
    def __len__(self):
        return len(self.buffer)             # 現在のバッファ内のサンプル数を返す

# 15. DQNエージェントの定義
class DQNAgent:
    def __init__(self, input_dim, output_dim, lr=1e-3, gamma=0.99, device="cpu"):
        self.device = device               # 学習に使用するデバイス（CPUまたはGPU）
        self.gamma = gamma                 # 割引率
        self.epsilon = 1.0                 # 初期探索率
        self.epsilon_decay = 0.995         # 探索率減衰係数
        self.epsilon_min = 0.05            # 探索率下限
        self.batch_size = 64               # ミニバッチサイズ
        self.policy_net = DQN(input_dim, output_dim).to(device)  # ポリシーネットワークの初期化
        self.target_net = DQN(input_dim, output_dim).to(device)  # ターゲットネットワークの初期化
        self.target_net.load_state_dict(self.policy_net.state_dict())  # ターゲットネットワークのパラメータ同期
        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=lr)  # Adam最適化器の初期化
        self.replay_buffer = ReplayBuffer(100000)  # リプレイバッファの初期化（最大100,000件）
    def select_action(self, state):
        if random.random() < self.epsilon:
            return random.randrange(self.policy_net.net[-1].out_features)  # ランダム行動選択
        else:
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)  # 状態をテンソル化
            with torch.no_grad():
                q_values = self.policy_net(state_tensor)   # Q値の計算
            return q_values.argmax().item()                # 最大Q値の行動インデックスを返す
    def update(self):
        if len(self.replay_buffer) < self.batch_size:
            return
        states, actions, rewards, next_states, dones = self.replay_buffer.sample(self.batch_size)
        states = torch.FloatTensor(states).to(self.device)
        actions = torch.LongTensor(actions).unsqueeze(1).to(self.device)
        rewards = torch.FloatTensor(rewards).unsqueeze(1).to(self.device)
        next_states = torch.FloatTensor(next_states).to(self.device)
        dones = torch.FloatTensor(dones).unsqueeze(1).to(self.device)
        current_q = self.policy_net(states).gather(1, actions)  # 現在のQ値
        with torch.no_grad():
            next_q = self.target_net(next_states).max(1, keepdim=True)[0]
        expected_q = rewards + self.gamma * next_q * (1 - dones)
        loss = nn.MSELoss()(current_q, expected_q)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
    def update_target(self):
        self.target_net.load_state_dict(self.policy_net.state_dict())

# 16. YAML設定ファイルを読み込む
with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# 17. YAMLからUnityサーバーのIPとポート番号を取得
unity_addr = config["Unity"]["server_addr"]
unity_port = config["Unity"]["server_port"]
python_addr= config["Unity"]["local_addr"]
python_port= config["Unity"]["local_port"]
# 18. UDPソケットを作成（IPv4, UDP）
python_to_unity_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# 19. 受信タイムアウトを1秒に設定
python_to_unity_sock.settimeout(1.0)
# 20. UDPソケットの送信先を設定
python_to_unity_sock.connect((unity_addr, unity_port))
print("Connected to Unity via UDP at {}:{}".format(unity_addr, unity_port))
unity_to_python_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
unity_to_python_sock.bind((python_addr, python_port))
unity_to_python_sock.settimeout(1.0)
print(f"Listening for UDP data on {python_addr}:{python_port}")

# 21. アクション送信関数（JSON形式で送信）
def send_action(action):
    data = {"action": int(action)}
    message = json.dumps(data).encode("utf-8")
    try:
        python_to_unity_sock.send(message)
    except Exception as e:
        print("Error sending action:", e)

# 22. 観測受信関数：UDPで受信したJSONデータを辞書に変換して返す
# 22. 観測受信関数：UDPで受信したJSONデータを辞書に変換して返す
def receive_observation():
    try:
        data, addr = unity_to_python_sock.recvfrom(65535)
        obs_data = json.loads(data.decode("utf-8"))            
        return obs_data
    except socket.timeout:
        return None
    except Exception as e:
        print("Error receiving observation:", e)
        return None

# 23. 状態前処理関数（変更箇所）
# Unityから送られてくるデータは fruitPos, nextFruitInfo, imageData, score のみを使用する
# 状態ベクトルは、fruitPos(3) + nextFruitInfo(11) + imageData(1: 平均輝度) + score(1) の合計16次元
def preprocess_observation(obs, min_score, max_score):
    features = []
    
    # fruitPos: x, y, z の3要素（変更箇所）
    fruit = obs.get("fruitPos", {"x": 0.0, "y": 0.0, "z": 0.0})
    features.append(float(fruit.get("x", 0.0)))
    features.append(float(fruit.get("y", 0.0)))
    features.append(float(fruit.get("z", 0.0)))
    
    # nextFruitInfo: 果物の種類をワンホットエンコーディング（変更箇所）
    fruit_name = obs.get("nextFruitInfo", "").lower()
    onehot = fruit_type_to_onehot.get(fruit_name, [0]*11)
    features.extend(onehot)
    
    # imageData: Base64エンコードされた画像から平均輝度を計算（変更箇所）
    image_data_base64 = obs.get("imageData", "")
    if image_data_base64:
        try:
            img_bytes = base64.b64decode(image_data_base64)
            img_array = np.frombuffer(img_bytes, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is not None:
                avg_brightness = float(np.mean(img))
            else:
                avg_brightness = 0.0
        except Exception:
            avg_brightness = 0.0
    else:
        avg_brightness = 0.0
    features.append(avg_brightness)
    
    # score: スコアを取得し、正規化（変更箇所）
    score = float(obs.get("score", 0))
    if max_score - min_score != 0:
        norm_score = (score - min_score) / (max_score - min_score)
    else:
        norm_score = 0.0
    features.append(norm_score)
    
    return np.array(features, dtype=np.float32)

def normalize_data(data, new_min, new_max):
    """
    データを新しい範囲 [new_min, new_max] に正規化する関数。

    Parameters:
        data (array-like): 正規化するデータ
        new_min (float): 正規化後の最小値
        new_max (float): 正規化後の最大値

    Returns:
        np.ndarray: 正規化されたデータ
    """
    data = np.array(data, dtype=np.float32)
    old_min = np.min(data)
    old_max = np.max(data)
    
    # 正規化処理
    normalized = (data - old_min) / (old_max - old_min + 1e-8)  # 1e-8はゼロ割防止用
    normalized = normalized * (new_max - new_min) + new_min
    
    return normalized

# 24. 学習パラメータ等をYAMLから取得
num_episodes = config["RLTrainer"]["num_episodes"]
max_steps = config["RLTrainer"].get("max_steps", 200)
action_interval = config["Unity"]["action_interval"]
max_score = config["RLTrainer"]["score_max"]
min_score = config["RLTrainer"]["score_min"]

# 25. 観測空間と行動空間の次元を設定
# 入力次元は固定で16（fruitPos:3 + nextFruitInfo:11 + imageData:1 + score:1）
input_dim = 16
output_dim = config["Action"]["binary_dim"]
if output_dim == 0:
    output_dim = 3

# 26. DQNエージェントを初期化（CPU使用）
agent = DQNAgent(input_dim, output_dim, device="cpu")

# 27. スコア計算用の変数初期化
prev_score = 0
prev_gameset_score = 4000
num_episodes =0
step=0

# 28. エピソードループ開始
#for episode in range(num_episodes):
while True:
    num_episodes+=1
    obs = receive_observation()
    if obs is None:
        obs = {"fruitPos": {"x":0.0, "y":0.0, "z":0.0}, "nextFruitInfo": "", "imageData": "", "score": 0, "done": False}
    state = preprocess_observation(obs, min_score, max_score)  # 前処理で状態ベクトルを構築（変更箇所）
    episode_reward = 0
    #for step in range(max_steps):
    while True:
        step+=1
        action = agent.select_action(state)  # 状態から行動選択
        send_action(action)                  # 選択した行動をUnityへ送信
        time.sleep(action_interval)          # 待機
        next_obs = receive_observation()
        if next_obs is None:
            next_obs = {"fruitPos": {"x":0.0, "y":0.0, "z":0.0}, "nextFruitInfo": "", "imageData": "", "score": obs["score"], "done": False}
            print("next_bsは空")
        next_state = preprocess_observation(next_obs, min_score, max_score)  # 次状態の前処理
        current_score = next_obs.get("score", 0)
        #current_score = normalize_data(current_score,min_score,max_score)
        #print(f"current_score={current_score}")
        done = next_obs.get("done", False)
        nashi=next_obs.get("nashi",False)
        peach=next_obs.get("peach",False)
        pin =next_obs.get("pin",False)
        melon = next_obs.get("melon",False)
        waterMelon = next_obs.get("waterMelon",False)
        if done:
            reward = current_score - prev_gameset_score
            if (current_score > prev_gameset_score) and current_score <= 10000:
                prev_gameset_score = current_score
            elif current_score > 10000:
                prev_gameset_score = 10000
            prev_score=0
            reward -= 1000
            print("おめでとうございます！ーーーーーーーーーーーーーーー")
        else:
            reward = 0
            prev_score = 0
        if nashi:
            reward += 10
            print("なし")
        if peach:
            reward += 500
            print("もも")
        if pin:
            reward += 1000
            print("ぱいな")
        if melon:
            reward += 5000
            print("めろん")
        if waterMelon:
            reward += 50000
            print("すいか")
        agent.replay_buffer.push(state, action, reward, next_state, done)
        state = next_state
        episode_reward += reward
        agent.update()
        if step % 50 == 0:
            agent.update_target()
        if done:
            step=0
            break
    #print("Episode {}: Total Reward: {}".format(episode, episode_reward))
    print(f"Episodes: {num_episodes} ,Total Reward: {episode_reward}")

python_to_unity_sock.close()
unity_to_python_sock.close()
