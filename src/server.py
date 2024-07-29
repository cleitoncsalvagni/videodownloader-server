from flask import Flask, request, jsonify
from flask_socketio import SocketIO
import yt_dlp
import threading
import os
import subprocess

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")


# Function to find ffmpeg and ffprobe in the directory tree
def find_ffmpeg_and_ffprobe(start_dir):
    ffmpeg_path = None
    ffprobe_path = None
    for root, dirs, files in os.walk(start_dir):
        if 'ffmpeg.exe' in files:
            ffmpeg_path = os.path.join(root, 'ffmpeg.exe')
        if 'ffprobe.exe' in files:
            ffprobe_path = os.path.join(root, 'ffprobe.exe')
        if ffmpeg_path and ffprobe_path:
            break
    return ffmpeg_path, ffprobe_path


# Get the directory where the script is running
script_dir = os.path.dirname(os.path.abspath(__file__))
FFMPEG_PATH, FFPROBE_PATH = find_ffmpeg_and_ffprobe(script_dir)


def fetch_video_info(url):
    ydl_opts = {
        'listformats': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0'
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(url, download=False)
    return result


def download_video(url, download_path, format_id, postprocessors, progress_callback):
    ydl_opts = {
        'outtmpl': f'{download_path}/%(title)s.%(ext)s',
        'format': format_id,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0'
        },
        'progress_hooks': [progress_callback],
        'ffmpeg_location': FFMPEG_PATH,
        'postprocessors': postprocessors,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        socketio.emit('download_error', {'error': str(e)})


def start_download(url, download_path, format_id, postprocessors):
    thread = threading.Thread(target=download_video,
                              args=(url, download_path, format_id, postprocessors, update_progress))
    thread.start()


def update_progress(data):
    if data['status'] == 'downloading':
        total = data.get('total_bytes', data.get('total_bytes_estimate', 0))
        downloaded = data.get('downloaded_bytes', 0)
        if total > 0:
            percent = downloaded / total * 100
            print(percent)
            socketio.emit('download_progress', {'progress': percent})


def compress_video(file_path, quality):
    output_path = os.path.splitext(file_path)[0] + f"_compressed_{quality}.mp4"
    if quality == 'whatsapp':
        command = [
            FFMPEG_PATH, '-i', file_path, '-vf', 'scale=640:480', '-c:v', 'libx264', '-preset', 'slow', '-crf', '28',
            '-c:a', 'aac', '-b:a', '64k', '-y', output_path
        ]
    else:
        crf = '28' if quality == 'medium' else '23'
        command = [
            FFMPEG_PATH, '-i', file_path, '-vf', 'scale=640:480', '-c:v', 'libx264', '-preset', 'slow', '-crf', crf,
            '-c:a', 'aac', '-b:a', '64k', '-y', output_path
        ]
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for line in process.stderr:
            socketio.emit('compress_progress', {'line': line.decode('utf-8')})
        process.wait()
        if process.returncode == 0:
            socketio.emit('compress_success', {'message': f'Vídeo compactado com sucesso para: {output_path}'})
        else:
            socketio.emit('compress_error', {'error': process.stderr.read().decode('utf-8')})
    except Exception as e:
        socketio.emit('compress_error', {'error': str(e)})


@app.route('/', methods=['GET'])
def health_status():
    return jsonify({
        'error': 0,
        'message': 'Working!'
    }), 200


@app.route('/fetch_video_info', methods=['POST'])
def api_fetch_video_info():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({'error': 1, 'message': 'URL is required'}), 200
    info = fetch_video_info(url)
    return jsonify(info)


@app.route('/download_video', methods=['POST'])
def api_download_video():
    data = request.get_json()
    url = data.get('url')
    download_path = data.get('download_path')
    format_id = data.get('format_id', 'best')
    postprocessors = data.get('postprocessors', [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}])
    if not url or not download_path:
        return jsonify({'error': 1, 'message': 'URL and download_path are required'}), 200
    start_download(url, download_path, format_id, postprocessors)
    return jsonify({'error': 0, 'message': 'Download started'}), 200


@app.route('/compress_video', methods=['POST'])
def api_compress_video():
    data = request.get_json()
    file_path = data.get('file_path')
    quality = data.get('quality')
    if not file_path or not quality:
        return jsonify({'error': 1, 'message': 'File path and quality are required'}), 200
    thread = threading.Thread(target=compress_video, args=(file_path, quality))
    thread.start()
    return jsonify({'error': 0, 'message': 'Compression started'}), 200


if __name__ == '__main__':
    if not FFMPEG_PATH or not FFPROBE_PATH:
        print("error: ffmpeg.exe e ffprobe.exe não encontrados. Verifique o diretório.")
    else:
        socketio.run(app, host='0.0.0.0', port=5000)
