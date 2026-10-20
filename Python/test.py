import socket        # UDP通信に必要なライブラリをインポート
import json          # JSONデータのエンコード／デコード用ライブラリをインポート

def main():
    udp_ip = "127.0.0.1"        # リッスンするIPアドレス（ローカルホスト）
    udp_port = 7889             # Unity側から送信されるポート番号（pythonPortと一致する必要があります）
    
    # UDPソケットを作成し、指定したIPとポートにバインドする
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((udp_ip, udp_port))
    
    print(f"Listening for UDP data on {udp_ip}:{udp_port}")
    
    while True:
        try:
            # 最大65535バイトまでのデータを受信
            data, addr = sock.recvfrom(65535)
            print(f"Received data from {addr}:")
            
            # 受信したバイト列をUTF-8でデコードしてJSONとして解析
            json_data = json.loads(data.decode("utf-8"))
            print("JSON Data:", json.dumps(json_data, indent=2))
        except Exception as e:
            print("Error:", e)

if __name__ == "__main__":
    main()
