from flask import Flask, request, jsonify
import json
import os
import signal
import sys
from datetime import datetime

app = Flask(__name__)
PORT = int(os.environ.get('PORT', 3000))
STATUS_KEY = 'latest_device_status'

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
with open(config_path, 'r', encoding='utf-8') as f:
    config = json.load(f)

# 尝试使用 Redis，如果失败则回退到内存存储
use_redis = False
redis_client = None
memory_storage = {}

try:
    import redis
    redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
    redis_client.ping()
    print('✅ Connected to Redis successfully')
    use_redis = True
except Exception as err:
    print(f'⚠️ Failed to connect to Redis: {err}')
    print('💡 Falling back to in-memory storage')
    use_redis = False

def get_storage():
    """获取当前的存储接口"""
    if use_redis:
        return redis_client
    else:
        return None

def set_status(value):
    """设置状态数据"""
    if use_redis:
        redis_client.set(STATUS_KEY, json.dumps(value))
    else:
        memory_storage[STATUS_KEY] = value

def get_status():
    """获取状态数据"""
    if use_redis:
        return redis_client.get(STATUS_KEY)
    else:
        return memory_storage.get(STATUS_KEY)

def graceful_shutdown(signum, frame):
    print(f'\nReceived {signal.Signals(signum).name}, shutting down gracefully...')
    print('Server shutdown complete')
    sys.exit(0)

signal.signal(signal.SIGINT, graceful_shutdown)
signal.signal(signal.SIGTERM, graceful_shutdown)

@app.errorhandler(Exception)
def handle_error(error):
    print(f'Server error: {error}')
    return jsonify({'error': 'Internal Server Error'}), 500

@app.route('/api/status', methods=['POST'])
def post_status():
    try:
        new_status = request.get_json()
        
        if not new_status or len(new_status) == 0:
            return jsonify({'error': 'Request body cannot be empty'}), 400
        
        new_status['receivedAt'] = datetime.utcnow().isoformat()
        
        set_status(new_status)
        print(f'[POST] Status updated at: {new_status["receivedAt"]}')
        
        return jsonify({
            'message': 'Status received and stored successfully',
            'data': new_status
        }), 200
    except Exception as error:
        print(f'Error storing data: {error}')
        return jsonify({'error': 'Internal Server Error'}), 500

@app.route('/api/status', methods=['GET'])
def get_status_endpoint():
    try:
        if use_redis:
            status_string = get_status()
            if not status_string:
                return jsonify({'error': 'No status data found.'}), 404
            latest_status = json.loads(status_string)
        else:
            latest_status = get_status()
            if not latest_status:
                return jsonify({'error': 'No status data found.'}), 404
        
        final_status = {'devices': {}}
        global_connection_status = 'online'
        
        for device_name, device_data in latest_status.get('devices', {}).items():
            if config.get('device_visibility', {}).get(device_name, False):
                device_connection_status = 'online'
                
                heartbeat_key = f'{device_name}_enabled'
                if config.get('heartbeat_check', {}).get(heartbeat_key, False):
                    last_update_time = datetime.fromisoformat(latest_status['receivedAt'].replace('Z', '+00:00')).timestamp()
                    current_time = datetime.utcnow().timestamp()
                    time_difference = (current_time - last_update_time) * 1000
                    
                    if time_difference >= config.get('timeout_ms', 30000):
                        device_connection_status = 'disconnect'
                        global_connection_status = 'partial_disconnect'
                
                final_status['devices'][device_name] = {
                    **device_data,
                    'connectionStatus': device_connection_status
                }
        
        return jsonify({
            'globalConnectionStatus': global_connection_status,
            'receivedAt': latest_status.get('receivedAt'),
            **final_status
        }), 200
    except Exception as error:
        print(f'Error retrieving or parsing data: {error}')
        return jsonify({'error': 'Internal Server Error'}), 500

def start_server():
    storage_type = 'Redis' if use_redis else 'In-Memory'
    print(f'📦 Using {storage_type} storage')
    print(f'🚀 Server running at http://localhost:{PORT}')
    print(f'⏱️ Timeout for enabled devices: {config.get("timeout_ms", 30000) / 1000} seconds')
    app.run(host='0.0.0.0', port=PORT)

if __name__ == '__main__':
    start_server()