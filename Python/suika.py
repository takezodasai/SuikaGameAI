import socket
import yaml
import json
import time
import numpy as np
import random
from collections import deque
import torch
import torch.nn as nn
import torch.optim as optim
import base64
import cv2

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

##############################################
# 1. CNNベースのDQNネットワークの定義（2ブランチ構造）
##############################################
class DQN_CNN(nn.Module):
    def __init__(self, non_image_dim, output_dim):
        """
        非画像特徴(non_image_dim): 例) 果物位置(3) + 次の果物のワンホット(11) + スコア(1) = 15
        output_dim: 出力アクション数
        """
        super(DQN_CNN, self).__init__()
        # CNNブランチ：画像から特徴抽出
        self.cnn = nn.Sequential(
            nn.Conv2d(3, 16, kernel_size=5, stride=2),  # 入力: (3,84,84)
            nn.ReLU(),
            nn.Conv2d(16, 32, kernel_size=5, stride=2),
            nn.ReLU(),
            nn.Conv2d(32, 32, kernel_size=5, stride=2),
            nn.ReLU(),
            nn.Flatten()
        )
        # ダミー入力でCNN出力次元を計算
        dummy_input = torch.zeros(1, 3, 84, 84)
        cnn_out_dim = self.cnn(dummy_input).shape[1]
        
        # 非画像ブランチ：数値データの処理
        self.fc_non_image = nn.Sequential(
            nn.Linear(non_image_dim, 64),
            nn.ReLU()
        )
        
        # 両ブランチの結合と最終出力層
        self.fc = nn.Sequential(
            nn.Linear(cnn_out_dim + 64, 128),
            nn.ReLU(),
            nn.Linear(128, output_dim)
        )
        
    def forward(self, image, non_image):
        """
        image: テンソル (B, 3, 84,84)
        non_image: テンソル (B, non_image_dim)
        """
        image_features = self.cnn(image)
        non_image_features = self.fc_non_image(non_image)
        combined = torch.cat([image_features, non_image_features], dim=1)
        return self.fc(combined)

##############################################
# 2. 優先度付き経験再生（PER）の実装
##############################################
class PrioritizedReplayBuffer:
    def __init__(self, capacity, alpha=0.6):
        self.capacity = capacity
        self.buffer = []
        self.priorities = []
        self.pos = 0
        self.alpha = alpha

    def push(self, experience):
        # experience: (state, action, reward, next_state, done)
        max_priority = max(self.priorities) if self.buffer else 1.0
        if len(self.buffer) < self.capacity:
            self.buffer.append(experience)
            self.priorities.append(max_priority)
        else:
            self.buffer[self.pos] = experience
            self.priorities[self.pos] = max_priority
            self.pos = (self.pos + 1) % self.capacity

    def sample(self, batch_size, beta=0.4):
        if len(self.buffer) == 0:
            return [], [], []
        priorities = np.array(self.priorities)
        probs = priorities ** self.alpha
        probs /= probs.sum()
        indices = np.random.choice(len(self.buffer), batch_size, p=probs)
        experiences = [self.buffer[idx] for idx in indices]
        total = len(self.buffer)
        weights = (total * probs[indices]) ** (-beta)
        weights /= weights.max()  # 正規化
        return experiences, indices, weights

    def update_priorities(self, indices, priorities):
        for idx, priority in zip(indices, priorities):
            self.priorities[idx] = priority

    def __len__(self):
        return len(self.buffer)

##############################################
# 3. DQNエージェントの定義（CNNモデル＆PER対応）
##############################################
class DQNAgent:
    def __init__(self, non_image_dim, output_dim, lr=1e-3, gamma=0.99, device="cpu"):
        self.device = device
        self.gamma = gamma
        self.epsilon = 1.0             # 初期探索率
        self.epsilon_decay = 0.999     # 減衰率をゆるやかにして初期段階の探索を多くする
        self.epsilon_min = 0.05
        self.batch_size = 64
        # CNNベースのポリシーネットワーク
        self.policy_net = DQN_CNN(non_image_dim, output_dim).to(device)
        self.target_net = DQN_CNN(non_image_dim, output_dim).to(device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=lr)
        self.replay_buffer = PrioritizedReplayBuffer(100000)
    
    def select_action(self, state):
        # stateは辞書 {"non_image": 非画像特徴, "image": 画像}
        if random.random() < self.epsilon:
            return random.randrange(self.policy_net.fc[-1].out_features)
        else:
            non_image = torch.FloatTensor(state["non_image"]).unsqueeze(0).to(self.device)  # shape: (1,15)
            # 画像は (H,W,3) → (3,H,W)
            image = torch.FloatTensor(state["image"]).permute(2, 0, 1).unsqueeze(0).to(self.device)  # shape: (1,3,84,84)
            with torch.no_grad():
                q_values = self.policy_net(image, non_image)
            return q_values.argmax().item()
    
    def update(self, beta=0.4):
        if len(self.replay_buffer) < self.batch_size:
            return
        
        experiences, indices, weights = self.replay_buffer.sample(self.batch_size, beta)
        # 各experience: (state, action, reward, next_state, done)
        # stateおよびnext_stateは辞書型
        actions = []
        rewards = []
        dones = []
        states_non_image = []
        states_image = []
        next_states_non_image = []
        next_states_image = []
        for exp in experiences:
            state, action, reward, next_state, done = exp
            states_non_image.append(state["non_image"])
            states_image.append(state["image"])
            next_states_non_image.append(next_state["non_image"])
            next_states_image.append(next_state["image"])
            actions.append(action)
            rewards.append(reward)
            dones.append(done)
        
        # それぞれnumpy配列に変換
        states_non_image = torch.FloatTensor(np.stack(states_non_image)).to(self.device)  # (B,15)
        # 画像は (B,84,84,3) → (B,3,84,84)
        states_image = torch.FloatTensor(np.stack(states_image)).permute(0, 3, 1, 2).to(self.device)
        next_states_non_image = torch.FloatTensor(np.stack(next_states_non_image)).to(self.device)
        next_states_image = torch.FloatTensor(np.stack(next_states_image)).permute(0, 3, 1, 2).to(self.device)
        actions = torch.LongTensor(actions).unsqueeze(1).to(self.device)
        rewards = torch.FloatTensor(rewards).unsqueeze(1).to(self.device)
        dones = torch.FloatTensor(dones).unsqueeze(1).to(self.device)
        weights = torch.FloatTensor(weights).unsqueeze(1).to(self.device)

        # 現在のQ値の計算
        current_q = self.policy_net(states_image, states_non_image).gather(1, actions)
        # 次状態のQ値（ターゲットネットワーク）
        with torch.no_grad():
            next_q = self.target_net(next_states_image, next_states_non_image).max(1, keepdim=True)[0]
        expected_q = rewards + self.gamma * next_q * (1 - dones)
        # TD誤差
        td_errors = (current_q - expected_q).abs() + 1e-6
        # PER用に優先度を更新
        new_priorities = td_errors.detach().cpu().numpy().squeeze()
        self.replay_buffer.update_priorities(indices, new_priorities)
        
        # 重み付き損失
        loss = (nn.MSELoss(reduction='none')(current_q, expected_q) * weights).mean()
        
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        
        # εの減衰
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
    
    def update_target(self):
        self.target_net.load_state_dict(self.policy_net.state_dict())

##############################################
# 4. 環境との通信および状態前処理
##############################################
# YAML設定ファイルの読み込み
with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# UnityサーバーのIPとポート番号の取得
unity_addr = config["Unity"]["server_addr"]
unity_port = config["Unity"]["server_port"]
python_addr = config["Unity"]["local_addr"]
python_port = config["Unity"]["local_port"]

# UDPソケットの設定
python_to_unity_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
python_to_unity_sock.settimeout(1.0)
python_to_unity_sock.connect((unity_addr, unity_port))
print("Connected to Unity via UDP at {}:{}".format(unity_addr, unity_port))
unity_to_python_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
unity_to_python_sock.bind((python_addr, python_port))
unity_to_python_sock.settimeout(1.0)
print(f"Listening for UDP data on {python_addr}:{python_port}")

# アクション送信関数（JSON形式）
def send_action(action):
    data = {"action": int(action)}
    message = json.dumps(data).encode("utf-8")
    try:
        python_to_unity_sock.send(message)
    except Exception as e:
        print("Error sending action:", e)

# 観測受信関数
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

# 状態前処理：盤面全体の画像と非画像特徴の抽出
def preprocess_observation(obs, min_score, max_score):
    # 非画像特徴：果物位置(3)、次の果物のワンホット(11)、スコア(1) → 合計15次元
    non_image_features = []
    fruit = obs.get("fruitPos", {"x": 0.0, "y": 0.0, "z": 0.0})
    non_image_features.append(float(fruit.get("x", 0.0)))
    non_image_features.append(float(fruit.get("y", 0.0)))
    non_image_features.append(float(fruit.get("z", 0.0)))
    fruit_name = obs.get("nextFruitInfo", "").lower()
    onehot = fruit_type_to_onehot.get(fruit_name, [0]*11)
    non_image_features.extend(onehot)
    score = float(obs.get("score", 0))
    if max_score - min_score != 0:
        norm_score = (score - min_score) / (max_score - min_score)
    else:
        norm_score = 0.0
    non_image_features.append(norm_score)
    non_image_features = np.array(non_image_features, dtype=np.float32)
    
    # 画像データの前処理：Base64デコード→OpenCVで画像復元→リサイズ(84x84)→RGB変換→正規化
    image_data_base64 = obs.get("imageData", "")
    if image_data_base64:
        try:
            img_bytes = base64.b64decode(image_data_base64)
            img_array = np.frombuffer(img_bytes, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is not None:
                img = cv2.resize(img, (84, 84))
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                img = img.astype(np.float32) / 255.0
            else:
                img = np.zeros((84, 84, 3), dtype=np.float32)
        except Exception:
            img = np.zeros((84, 84, 3), dtype=np.float32)
    else:
        img = np.zeros((84, 84, 3), dtype=np.float32)
    
    # stateは辞書で保持
    state = {"non_image": non_image_features, "image": img}
    return state

##############################################
# 5. 学習パラメータとエージェントの初期化
##############################################
num_episodes = config["RLTrainer"]["num_episodes"]
max_steps = config["RLTrainer"].get("max_steps", 200)
action_interval = config["Unity"]["action_interval"]
max_score = config["RLTrainer"]["score_max"]
min_score = config["RLTrainer"]["score_min"]

# 非画像特徴の次元は15（3+11+1）
non_image_dim = 15
output_dim = config["Action"]["binary_dim"]
if output_dim == 0:
    output_dim = 3

agent = DQNAgent(non_image_dim, output_dim, device="cpu")

prev_gameset_score = 4000
episode_count = 0
step = 0

##############################################
# 6. エピソードループ（UDPで環境と通信しながら学習）
##############################################
while True:
    episode_count += 1
    obs = receive_observation()
    if obs is None:
        obs = {"fruitPos": {"x":0.0, "y":0.0, "z":0.0},
               "nextFruitInfo": "",
               "imageData": "",
               "score": 0,
               "done": False}
    state = preprocess_observation(obs, min_score, max_score)
    episode_reward = 0
    
    while True:
        step += 1
        action = agent.select_action(state)
        send_action(action)
        time.sleep(action_interval)
        
        next_obs = receive_observation()
        if next_obs is None:
            next_obs = {"fruitPos": {"x":0.0, "y":0.0, "z":0.0},
                        "nextFruitInfo": "",
                        "imageData": "",
                        "score": obs["score"],
                        "done": False}
            print("next_obs is empty")
        next_state = preprocess_observation(next_obs, min_score, max_score)
        current_score = next_obs.get("score", 0)
        done = next_obs.get("done", False)
        
        # 報酬設計例（合成成功時や特定の果物獲得時に報酬を与える）
        if done:
            reward = current_score - prev_gameset_score
            if (current_score > prev_gameset_score) and current_score <= 10000:
                prev_gameset_score = current_score
            elif current_score > 10000:
                prev_gameset_score = 10000
            reward -= 1000
            print("Game over!")
        else:
            reward = 0
        
        # 追加報酬（例：各果物の獲得）
        if next_obs.get("nashi", False):
            reward += 10
            print("なし")
        if next_obs.get("peach", False):
            reward += 500
            print("もも")
        if next_obs.get("pin", False):
            reward += 1000
            print("ぱいな")
        if next_obs.get("melon", False):
            reward += 5000
            print("めろん")
        if next_obs.get("waterMelon", False):
            reward += 50000
            print("すいか")
        
        # 優先度付き経験再生バッファに経験を追加
        agent.replay_buffer.push((state, action, reward, next_state, done))
        state = next_state
        episode_reward += reward
        
        agent.update()  # PERに基づく更新
        
        if step % 50 == 0:
            agent.update_target()
        
        if done:
            step = 0
            break

    print(f"Episodes: {episode_count} ,Total Reward: {episode_reward}")

python_to_unity_sock.close()
unity_to_python_sock.close()
